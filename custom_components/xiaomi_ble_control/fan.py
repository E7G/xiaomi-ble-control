"""F11 fan platform."""

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.const import CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .protocol import speed_percentage


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([F11Fan(entry.runtime_data, entry)])


class F11Fan(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_speed_count = 100
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
        return speed_percentage(raw) if raw is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        attrs = {key: data[key] for key in ("bluetooth_status", "bluetooth_source", "rssi")}
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
        if not 0 <= percentage <= 100:
            raise HomeAssistantError("F11 percentage must be between 0 and 100")
        await self.coordinator.async_write_speed(max(1, round(percentage)) if percentage else 0)
