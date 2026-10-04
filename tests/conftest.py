"""Small HA API doubles; production imports are also smoke-tested on real HA."""

import importlib.util
import sys
import types
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace

import pytest

BASE = Path(__file__).parents[1] / "custom_components/xiaomi_ble_control"


@pytest.fixture
def modules(monkeypatch):
    package = types.ModuleType("xbctest")
    package.__path__ = [str(BASE)]
    monkeypatch.setitem(sys.modules, "xbctest", package)

    def register(name, **attrs):
        module = types.ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    register("homeassistant")
    register("homeassistant.components")
    register("homeassistant.helpers")
    register(
        "homeassistant.const",
        CONF_ADDRESS="address",
        CONF_TOKEN="token",
        CONF_NAME="name",
        EVENT_HOMEASSISTANT_STOP="stop",
        PERCENTAGE="%",
        UnitOfTime=SimpleNamespace(MINUTES="min", SECONDS="s"),
    )
    register("homeassistant.exceptions", HomeAssistantError=RuntimeError)
    register(
        "homeassistant.helpers.entity", EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic")
    )
    register(
        "homeassistant.components.light",
        LightEntity=type("LightEntity", (), {}),
        ColorMode=SimpleNamespace(ONOFF="onoff"),
    )
    register(
        "homeassistant.components.number",
        NumberEntity=type("NumberEntity", (), {}),
        NumberMode=SimpleNamespace(BOX="box"),
    )
    register(
        "homeassistant.components.sensor",
        SensorEntity=type("SensorEntity", (), {}),
        SensorDeviceClass=SimpleNamespace(BATTERY="battery", ENUM="enum", DURATION="duration"),
        SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
    )
    register(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=type("BinarySensorEntity", (), {}),
        BinarySensorDeviceClass=SimpleNamespace(
            CONNECTIVITY="connectivity", BATTERY_CHARGING="battery_charging"
        ),
    )
    register("homeassistant.helpers.config_validation", string=str)
    register(
        "homeassistant.helpers.selector",
        TextSelector=lambda _: str,
        TextSelectorConfig=lambda **kwargs: kwargs,
        TextSelectorType=SimpleNamespace(PASSWORD="password"),
    )
    register(
        "homeassistant.helpers.device_registry",
        CONNECTION_BLUETOOTH="bluetooth",
        DeviceInfo=lambda **kwargs: kwargs,
    )

    class Feature(IntFlag):
        SET_SPEED = 1
        TURN_ON = 16
        TURN_OFF = 32

    class FanEntity:
        @property
        def is_on(self):
            return (self.percentage or 0) > 0

    class Coordinator:
        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
            self.data = None
            self.published = []

        def async_set_updated_data(self, data):
            self.data = data
            self.published.append(data)

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    register("homeassistant.components.fan", FanEntity=FanEntity, FanEntityFeature=Feature)
    register(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=Coordinator,
        CoordinatorEntity=CoordinatorEntity,
    )
    register(
        "homeassistant.components.bluetooth",
        BluetoothScanningMode=SimpleNamespace(ACTIVE="active"),
        async_ble_device_from_address=lambda *_args, **_kwargs: None,
    )
    register("bleak_retry_connector", BleakClientWithServiceCache=object, establish_connection=None)

    class Flow:
        @property
        def context(self):
            if not hasattr(self, "_context"):
                self._context = {}
            return self._context

        def __init_subclass__(cls, domain=None):
            pass

        async def async_set_unique_id(self, uid):
            self.unique_id = uid

        def _abort_if_unique_id_configured(self):
            pass

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

    register("homeassistant.config_entries", ConfigFlow=Flow)

    def load(name):
        fullname = "xbctest." + name
        # Relative imports may have loaded the module already.
        if fullname in sys.modules:
            return sys.modules[fullname]
        spec = importlib.util.spec_from_file_location(fullname, BASE / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, module)
        spec.loader.exec_module(module)
        return module

    yield load
    for name in list(sys.modules):
        if name.startswith("xbctest."):
            sys.modules.pop(name)
