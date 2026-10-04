"""F11's physical on/off night light (not dimmable)."""

from typing import ClassVar

from homeassistant.components.light import ColorMode, LightEntity

from .entity import F11Entity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([F11NightLight(entry.runtime_data, entry)])


class F11NightLight(F11Entity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.ONOFF}

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "night_light", (3, 5))

    @property
    def is_on(self):
        return self.property_value == 1 if self.property_value is not None else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_write_property(3, 5, 1)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write_property(3, 5, 0)
