"""Shared F11 identity and authenticated property availability."""

from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL


class F11Entity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, prop=None):
        super().__init__(coordinator)
        self.prop = prop
        address = coordinator.address
        self._attr_unique_id = address.replace(":", "").lower() + "_" + key
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=entry.data[CONF_NAME],
            manufacturer="AIVI",
            model=MODEL,
        )

    @property
    def available(self):
        return self.coordinator.data["available"] and (
            self.prop is None or self.prop in self.coordinator.data["properties"]
        )

    @property
    def property_value(self):
        return self.coordinator.data["properties"].get(self.prop)
