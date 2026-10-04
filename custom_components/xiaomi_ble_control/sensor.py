"""F11 battery, charging, work state and remaining timer notifications."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTime

from .entity import F11Entity

DEFINITIONS = (
    ("battery", (3, 6), SensorDeviceClass.BATTERY, PERCENTAGE, None),
    (
        "charging_state",
        (2, 1034),
        SensorDeviceClass.ENUM,
        None,
        ("not_charging", "charging", "full"),
    ),
    ("work_status", (3, 1), SensorDeviceClass.ENUM, None, ("off", "on", "idle")),
    ("remaining_time", (3, 4), SensorDeviceClass.DURATION, UnitOfTime.SECONDS, None),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [F11Sensor(entry.runtime_data, entry, *definition) for definition in DEFINITIONS]
    )


class F11Sensor(F11Entity, SensorEntity):
    def __init__(self, coordinator, entry, key, prop, device_class, unit, options):
        super().__init__(coordinator, entry, key, prop)
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_options = list(options) if options else None
        if key == "battery":
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        value = self.property_value
        if self._attr_options is not None:
            return (
                self._attr_options[value]
                if value is not None and 0 <= value < len(self._attr_options)
                else None
            )
        return value
