"""F11 fan platform."""

import math

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.const import CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .helpers import percentage_to_speed, speed_to_level
from .protocol import speed_percentage


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([F11Fan(entry.runtime_data, entry), F11BemfaFan(entry.runtime_data, entry)])


class F11Fan(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_speed_count = 5
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_unique_id = address.replace(":", "").lower() + "_fan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=entry.data[CONF_NAME],
            manufacturer="AIVI",
            model=MODEL,
        )

    @property
    def available(self):
        return self.coordinator.data["available"]

    @property
    def percentage(self):
        raw = self.coordinator.data["properties"].get((3, 2))
        return speed_to_level(speed_percentage(raw)) * 20 if raw is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        attrs = {key: data[key] for key in ("bluetooth_status", "bluetooth_source", "rssi")}
        raw = data["properties"].get((3, 2))
        if raw is not None:
            attrs["device_percentage"] = speed_percentage(raw)
            attrs["speed_level"] = speed_to_level(speed_percentage(raw))
        for prop, attr in {
            (3, 1): "work_status",
            (3, 3): "timer_minutes",
            (3, 4): "remaining_seconds",
            (3, 5): "night_light",
            (3, 6): "battery",
            (2, 1034): "charging_status",
        }.items():
            if prop in data["properties"]:
                attrs[attr] = data["properties"][prop]
        return attrs

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        if percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self.coordinator.async_write_speed(1)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write_speed(0)

    async def async_set_percentage(self, percentage):
        try:
            speed = percentage_to_speed(percentage)
        except ValueError:
            raise HomeAssistantError("F11 percentage must be between 0 and 100") from None
        await self.coordinator.async_write_speed(speed)


class F11BemfaFan(F11Fan):
    """Optional four-level cloud view: skip physical level one, share one session."""

    _attr_name = "Bemfa fan"
    _attr_translation_key = "bemfa_fan"
    _attr_speed_count = 4
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = coordinator.address.replace(":", "").lower() + "_bemfa_fan"

    @property
    def percentage(self):
        raw = self.coordinator.data["properties"].get((3, 2))
        if raw is None:
            return None
        speed = speed_percentage(raw)
        # Preserve real readback, including HA-only physical level one. The
        # cloud then reports level zero rather than falsely reporting level two.
        return speed

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        await self.async_set_percentage(25 if percentage is None else percentage)

    async def async_set_percentage(self, percentage):
        if not math.isfinite(percentage) or not 0 <= percentage <= 100:
            raise HomeAssistantError("F11 percentage must be between 0 and 100")
        await self.coordinator.async_write_speed(math.ceil(percentage / 25) * 25)
