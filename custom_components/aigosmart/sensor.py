from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from .entity import AigoEntity
from .enum_labels import enum_key, enum_label, enum_labels
from .diagnostic_state import SENSOR_NAMES, TIMESTAMP_KEYS, diagnostic_values, utc_datetime

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AigoSensor(entry.runtime_data, key) for key in
        ('status', 'Target_temperature', 'Time', 'heatpreservation')] + [
        AigoSessionSensor(entry.runtime_data, key) for key in
        SENSOR_NAMES] + [AigoEnumDescriptionSensor(entry.runtime_data, key)
                        for key in ('Mode', 'status')] + [AigoPropertiesSensor(entry.runtime_data)])

class AigoSensor(AigoEntity, SensorEntity):
    @property
    def native_value(self):
        return self.value

    @property
    def native_unit_of_measurement(self):
        return {'Target_temperature': '°C', 'Time': 'min', 'heatpreservation': 'h'}.get(self.key)

    @property
    def extra_state_attributes(self):
        attributes = super().extra_state_attributes
        if self.key == 'status':
            attributes = {**attributes,
                'status_labels': enum_labels(self.coordinator.model, 'status'),
                'status_label': enum_label(self.coordinator.model, 'status', self.value)}
        return attributes


class AigoEnumDescriptionSensor(AigoEntity, SensorEntity):
    """Add readable values without changing existing machine states or IDs."""
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._attr_name = None
        self._attr_translation_key = f'{key.lower()}_description'

    @property
    def native_value(self):
        return enum_label(self.coordinator.model, self.key, self.value)

    @property
    def extra_state_attributes(self):
        return {'raw_value': enum_key(self.value)}


class AigoSessionSensor(AigoEntity, SensorEntity):
    """Fixed diagnostic vocabulary, never tokens or identity IDs."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._attr_name = SENSOR_NAMES[key]
        if key in TIMESTAMP_KEYS:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        value = diagnostic_values(self.coordinator.session)[self.key]
        return utc_datetime(value) if self.key in TIMESTAMP_KEYS else value

    @property
    def native_unit_of_measurement(self):
        return 's' if self.key == 'session_time_remaining' else None

    @property
    def extra_state_attributes(self):
        return None


class AigoPropertiesSensor(AigoEntity, SensorEntity):
    """Fork addition (Nobleza litter box): every property the device reports plus its live TSL.

    Read-only discovery aid; no commands are sent. State = number of reported properties.
    """
    _attr_icon = 'mdi:format-list-bulleted'

    def __init__(self, coordinator):
        super().__init__(coordinator, 'all_properties')
        self._attr_name = 'All properties'

    @property
    def available(self):
        return bool(self.coordinator.last_update_success and self.coordinator.data is not None)

    @property
    def native_value(self):
        return len(self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        values = {}
        for ident, item in (self.coordinator.data or {}).items():
            if isinstance(item, dict):
                values[ident] = {'value': item.get('value'), 'time': item.get('time')}
        model = self.coordinator.model or {}
        rows = []
        for row in model.get('properties', []):
            rows.append({'id': row.get('identifier'), 'name': row.get('name'), 'access': row.get('access'),
                         'type': row.get('data_type'), 'constraints': row.get('constraints')})
        return {'values': values, 'model': rows}
