"""Shared API with single-attempt writes and live TSL validation."""
import json
from . import protocol as p
from .model import parse_extras, parse_model, plan

# Fork: kettle properties plus the Nobleza litter box settings that are read-write in its live TSL.
WRITABLE = {'Target_temperature', 'Mode', 'HeatingSwitch', 'heatpreservation',
            'mode', 'autoDelay', 'dndSwitch', 'led', 'childlock', 'replaceTime', 'language'}


class AigoClient(p.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._permission = None
        self._security_code = None

    def login_with_code(self, email, password, code=None):
        self._security_code = code
        try:
            return self.login(email, password, interactive=code is not None)
        finally:
            self._security_code = None

    def security_verification(self, username):
        return self._security_code

    def send_security_code(self, email):
        self.uc(p.SEND_CODE, {'send_to': email.strip(), 'account_type': 'email',
            'action': 'LoginSecurity', 're_send_count': 0, 'captcha_token': ''}, smart=True)

    def model(self, device):
        data = self.signed(p.IOT, p.TSL, {'iotId': p.required(device, 'iotId')}, '1.0.4')['data']
        result = {'source': 'live-tsl', 'properties': parse_model(data)}
        try:
            result.update(parse_extras(data))
        except Exception:
            result.update({'services': [], 'events': []})
        return result

    def authorize_property_write(self, method, url, body):
        permission, self._permission = self._permission, None
        invoke, self._invoke_permission = getattr(self, '_invoke_permission', None), None
        if method != 'POST':
            return False
        if permission is not None and url == p.IOT + '/thing/properties/set':
            return json.loads(body).get('params') == permission
        if invoke is not None and url == p.IOT + '/thing/service/invoke':
            return json.loads(body).get('params') == invoke
        return False

    def write(self, device, model, identifier, value, *, dry_run=False):
        if identifier not in WRITABLE:
            raise ValueError('Property blocked by safety policy')
        output = plan(model, identifier, value)
        if dry_run:
            return output
        params = {'iotId': p.required(device, 'iotId'), 'items': {identifier: value}}
        self._permission = params
        try:
            self.signed(p.IOT, '/thing/properties/set', params)
        finally:
            self._permission = None
        return 'accepted_unconfirmed'

    def invoke(self, device, model, identifier, args):
        """Fork addition: call a TSL service (e.g. clean now). One attempt, only identifiers and argument names declared in the live TSL."""
        rows = [s for s in (model or {}).get('services', []) if s.get('id') == identifier]
        if model.get('source') != 'live-tsl' or len(rows) != 1:
            raise ValueError('Unknown service')
        args = args if isinstance(args, dict) else {}
        declared = {f['id'] for f in rows[0].get('input', [])}
        if set(args) - declared:
            raise ValueError('Argument not declared in TSL')
        for value in args.values():
            if type(value) not in (int, float, bool, str):
                raise ValueError('Unsupported argument type')
        params = {'iotId': p.required(device, 'iotId'), 'identifier': identifier, 'args': args}
        self._invoke_permission = params
        try:
            self.signed(p.IOT, '/thing/service/invoke', params, '1.0.2')
        finally:
            self._invoke_permission = None
        return 'accepted_unconfirmed'


def is_auth_error(exc):
    return isinstance(exc, p.NeedSecurityCodeError) or (
        isinstance(exc, p.APIError) and (exc.status in (401, 403) or exc.code in {
            '401', '403', '2062', '100001', '100003', '100004', '100005', 'invalid_grant', 'access_denied', 'invalid_client'}))
