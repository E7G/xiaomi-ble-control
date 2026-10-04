"""Charging and live connection status for automations."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import F11Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            F11BinarySensor(entry.runtime_data, entry, "charging", (2, 1034)),
            F11BinarySensor(entry.runtime_data, entry, "connection"),
        ]
    )


class F11BinarySensor(F11Entity, BinarySensorEntity):
    def __init__(self, coordinator, entry, key, prop=None):
        super().__init__(coordinator, entry, key, prop)
        self._attr_device_class = (
            BinarySensorDeviceClass.CONNECTIVITY
            if prop is None
            else BinarySensorDeviceClass.BATTERY_CHARGING
        )
        if prop is None:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        return True if self.prop is None else super().available

    @property
    def is_on(self):
        return self.coordinator.data["available"] if self.prop is None else self.property_value == 1
