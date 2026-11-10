"""AigoSmart HA integration; protocol imports also work without HA installed."""
async def async_setup_entry(hass, entry):
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from .api import AigoClient, is_auth_error
    from .const import PLATFORMS
    from .coordinator import AigoCoordinator
    from .recovery import RecoveryError, failure
    client = AigoClient()
    stage = 'session_restore'
    try:
        client.restore_session(entry.data)
        coordinator = AigoCoordinator(hass, entry, client)
        coordinator.session.require_credentials()
        stage = 'model_tsl_fetch'
        coordinator.model = await coordinator.session.read(client.model, coordinator.device, stage=stage)
    except BaseException as exc:
        if 'coordinator' in locals():
            await coordinator.session.close()
        if not isinstance(exc, Exception):
            raise
        reason = failure(stage, exc)
        stage = exc.stage if isinstance(exc, RecoveryError) else stage
        if isinstance(exc, ConfigEntryAuthFailed):
            raise
        if is_auth_error(exc):
            raise ConfigEntryAuthFailed('Authentication required') from None
        raise ConfigEntryNotReady(f'{stage}: {reason}') from None
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.session.close()
        raise
    coordinator.session.schedule()
    coordinator._entry_options = dict(entry.options)
    entry.runtime_data = coordinator
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_reload))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.session.close()
        raise
    try:
        from .frontend import async_schedule_frontend
        async_schedule_frontend(hass)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            'Integrated card setup failed; cloud integration remains available'
        )
    return True

async def _reload(hass, entry):
    if dict(entry.options) != entry.runtime_data._entry_options:
        await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass, entry):
    from .const import PLATFORMS
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if result:
        await entry.runtime_data.session.close()
        entry.runtime_data.client.token = None
        entry.runtime_data.client.session.clear()
    return result


async def async_migrate_entry(hass, entry):
    """Keep legacy device/options; setup requests one-time reauth for missing fields."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


def _register_services(hass):
    """Fork addition: set_property and invoke_service (single entry; guarded by the live TSL)."""
    import voluptuous as vol
    from homeassistant.exceptions import HomeAssistantError
    from .const import DOMAIN

    def coordinator():
        entries = [e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, 'runtime_data', None)]
        if len(entries) != 1:
            raise HomeAssistantError('Exactly one loaded AigoSmart entry is required')
        return entries[0].runtime_data

    async def set_property(call):
        return {'result': await coordinator().async_write(call.data['identifier'], call.data['value'])}

    async def invoke_service(call):
        return {'result': await coordinator().async_invoke(call.data['identifier'], call.data.get('args') or {})}

    if not hass.services.has_service(DOMAIN, 'set_property'):
        from homeassistant.core import SupportsResponse
        hass.services.async_register(DOMAIN, 'set_property', set_property,
            vol.Schema({vol.Required('identifier'): str, vol.Required('value'): vol.Any(int, float)}),
            supports_response=SupportsResponse.OPTIONAL)
        hass.services.async_register(DOMAIN, 'invoke_service', invoke_service,
            vol.Schema({vol.Required('identifier'): str, vol.Optional('args'): dict}),
            supports_response=SupportsResponse.OPTIONAL)
