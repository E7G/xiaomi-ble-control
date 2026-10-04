"""Five levels, independent stepless speed and device-side off timer."""

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.exceptions import HomeAssistantError

from .entity import F11Entity
from .helpers import LEVEL_SPEEDS, speed_to_level
from .protocol import speed_percentage


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            F11Number(entry.runtime_data, entry, "speed_level", (3, 2), 5),
            F11Number(entry.runtime_data, entry, "stepless_speed", (3, 2), 100, PERCENTAGE),
            F11Number(entry.runtime_data, entry, "off_timer", (3, 3), 480, UnitOfTime.MINUTES),
        ]
    )


class F11Number(F11Entity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, key, prop, maximum, unit=None):
        super().__init__(coordinator, entry, key, prop)
        self.key = key
        self._attr_native_max_value = maximum
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = "mdi:timer-outline" if key == "off_timer" else "mdi:fan"

    @property
    def native_value(self):
        value = self.property_value
        if value is None:
            return None
        if self.key == "speed_level":
            return speed_to_level(speed_percentage(value))
        if self.key == "stepless_speed":
            return speed_percentage(value)
        return value

    async def async_set_native_value(self, value):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value):
            raise HomeAssistantError("F11 controls require an integer value")
        if not 0 <= value <= self._attr_native_max_value:
            raise HomeAssistantError("F11 control value out of range")
        value = int(value)
        if self.key == "speed_level":
            value = LEVEL_SPEEDS[value]
        await self.coordinator.async_write_property(*self.prop, value)
