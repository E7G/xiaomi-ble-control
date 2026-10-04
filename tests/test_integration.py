import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def entry():
    return SimpleNamespace(
        title="F11",
        data={"address": "AA:BB:CC:DD:EE:FF", "token": "00" * 12, "name": "F11"},
        entry_id="entry",
    )


def test_validation_and_discovery(modules):
    helpers = modules("helpers")
    assert helpers.normalize_address(" aa:bb:cc:dd:ee:ff ") == "AA:BB:CC:DD:EE:FF"
    assert helpers.normalize_token(" AB" + "00" * 11 + " ") == "ab" + "00" * 11
    for value in ("not-a-mac", "11:22:33:44:55", "GG:22:33:44:55:66"):
        with pytest.raises(ValueError):
            helpers.normalize_address(value)
    for value in ("", "00" * 16, "z" * 24):
        with pytest.raises(ValueError):
            helpers.normalize_token(value)
    service = {"0000fe95-0000-1000-8000-00805f9b34fb": bytes.fromhex("1059925f0041aa02573fc0")}
    assert helpers.supported_advertisement(service)
    assert not helpers.supported_advertisement({})
    assert not helpers.supported_advertisement({next(iter(service)): bytes.fromhex("1059341200")})


@pytest.mark.asyncio
async def test_flow_validates_before_creating_entry(modules, monkeypatch):
    module = modules("config_flow")
    validate = AsyncMock()
    monkeypatch.setattr(module, "validate_connection", validate)
    flow = module.ConfigFlow()
    flow.hass = object()
    result = await flow.async_step_user(
        {"address": "aa:bb:cc:dd:ee:ff", "token": "00" * 12, "name": "F11"}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["address"] == "AA:BB:CC:DD:EE:FF"
    validate.assert_awaited_once_with(flow.hass, "AA:BB:CC:DD:EE:FF", "00" * 12)


@pytest.mark.asyncio
async def test_flow_bad_input_does_not_connect(modules, monkeypatch):
    module = modules("config_flow")
    validate = AsyncMock()
    monkeypatch.setattr(module, "validate_connection", validate)
    flow = module.ConfigFlow()
    result = await flow.async_step_user({"address": "bad", "token": "00" * 16})
    assert result["errors"] == {"address": "invalid_address", "token": "invalid_token"}
    validate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,error",
    [("auth", "invalid_auth"), ("connect", "cannot_connect"), ("model", "not_supported")],
)
async def test_flow_errors(modules, monkeypatch, kind, error):
    module = modules("config_flow")
    exception = {
        "auth": module.AuthenticationError,
        "connect": TimeoutError,
        "model": module.UnsupportedDevice,
    }[kind]
    monkeypatch.setattr(module, "validate_connection", AsyncMock(side_effect=exception()))
    flow = module.ConfigFlow()
    flow.hass = object()
    result = await flow.async_step_user({"address": "AA:BB:CC:DD:EE:FF", "token": "00" * 12})
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}


@pytest.mark.asyncio
async def test_discovery_filters_other_xiaomi_devices(modules):
    module = modules("config_flow")
    flow = module.ConfigFlow()
    result = await flow.async_step_bluetooth(
        SimpleNamespace(service_data={}, address="AA:BB:CC:DD:EE:FF")
    )
    assert result == {"type": "abort", "reason": "not_supported"}


@pytest.mark.asyncio
async def test_fan_encoding_and_feedback_not_optimistic(modules):
    module = modules("fan")
    coordinator = SimpleNamespace(
        address=entry().data["address"],
        data={
            "available": True,
            "properties": {(3, 2): 168},
            "bluetooth_status": "connected",
            "bluetooth_source": "proxy",
            "rssi": -50,
        },
        async_write_speed=AsyncMock(),
    )
    fan = module.F11Fan(coordinator, entry())
    assert fan.percentage == 60
    assert fan.available and fan.is_on
    await fan.async_turn_on()
    await fan.async_set_percentage(20)
    await fan.async_turn_off()
    assert [call.args[0] for call in coordinator.async_write_speed.await_args_list] == [1, 1, 0]
    assert fan.percentage == 60  # no optimistic mutation
    coordinator.data["properties"][3, 2] = 148
    assert fan.percentage == 40
    coordinator.data["properties"][3, 2] = 1
    assert fan.percentage == 0 and not fan.is_on
    with pytest.raises(RuntimeError):
        await fan.async_set_percentage(101)


@pytest.mark.asyncio
async def test_coordinator_authentication_gate_and_stop(modules):
    module = modules("coordinator")
    coordinator = module.F11Coordinator(object(), entry())
    coordinator._report({(3, 2): 148})
    assert not coordinator.data["available"]
    coordinator._ready = True
    coordinator._report({(3, 2): 168})
    assert coordinator.data["available"]
    coordinator._session = SimpleNamespace(write=AsyncMock())
    await coordinator.async_write_speed(20)
    coordinator._session.write.assert_awaited_once_with(3, 2, 20)
    coordinator._ready = False
    coordinator._publish()
    with pytest.raises(RuntimeError):
        await coordinator.async_write_speed(20)
    coordinator._task = asyncio.create_task(asyncio.sleep(100))
    removed = []
    coordinator._removers = [lambda: removed.append(True)]
    await coordinator.async_stop()
    assert removed == [True] and coordinator._task is None


@pytest.mark.asyncio
async def test_diagnostics_never_include_token(modules):
    module = modules("diagnostics")
    coordinator = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        data={
            "available": False,
            "bluetooth_status": "waiting",
            "bluetooth_source": None,
            "rssi": None,
            "properties": {(3, 6): 43},
        },
    )
    data = await module.async_get_config_entry_diagnostics(
        None, SimpleNamespace(runtime_data=coordinator, data={"token": "secret"})
    )
    assert data["properties"] == {"3.p.6": 43}
    assert "token" not in str(data) and "secret" not in str(data)


@pytest.mark.parametrize("level,raw", [(0, 0), (1, 1), (2, 25), (3, 50), (4, 75), (5, 100)])
def test_five_levels_match_mi_home(modules, level, raw):
    helpers = modules("helpers")
    assert helpers.percentage_to_speed(level * 20) == raw
    assert helpers.speed_to_level(raw) == level


@pytest.mark.asyncio
async def test_bemfa_bridge_skips_lowest_level_without_affecting_main_fan(modules):
    module = modules("fan")
    coordinator = SimpleNamespace(
        address=entry().data["address"],
        data={"available": True, "properties": {(3, 2): 129}},
        async_write_speed=AsyncMock(),
    )
    main = module.F11Fan(coordinator, entry())
    bridge = module.F11BemfaFan(coordinator, entry())
    assert main._attr_speed_count == 5 and bridge._attr_speed_count == 4
    assert main.percentage == 20 and bridge.percentage == 1
    await bridge.async_turn_on()
    for percentage in (25, 50, 75, 100):
        await bridge.async_set_percentage(percentage)
        coordinator.data["properties"][3, 2] = 128 + percentage
        assert bridge.percentage == percentage
    await bridge.async_turn_off()
    assert [call.args[0] for call in coordinator.async_write_speed.await_args_list] == [
        25,
        25,
        50,
        75,
        100,
        0,
    ]


@pytest.mark.asyncio
async def test_all_controls_are_real_non_optimistic_properties(modules):
    light_module = modules("light")
    numbers = modules("number")
    sensors = modules("sensor")
    binary = modules("binary_sensor")
    coordinator = SimpleNamespace(
        address=entry().data["address"],
        data={
            "available": True,
            "properties": {
                (3, 2): 153,
                (3, 3): 60,
                (3, 5): 0,
                (3, 6): 80,
                (3, 1): 1,
                (3, 4): 3580,
                (2, 1034): 1,
            },
        },
        async_write_property=AsyncMock(),
    )
    light = light_module.F11NightLight(coordinator, entry())
    await light.async_turn_on()
    assert light.available and not light.is_on
    coordinator.data["properties"][3, 5] = 1
    assert light.is_on
    await light.async_turn_off()
    for key, prop, maximum, write in [
        ("speed_level", (3, 2), 5, 5),
        ("stepless_speed", (3, 2), 100, 37),
        ("off_timer", (3, 3), 480, 480),
    ]:
        number = numbers.F11Number(coordinator, entry(), key, prop, maximum)
        before = number.native_value
        await number.async_set_native_value(write)
        assert number.native_value == before
        for invalid in (-1, maximum + 1, 1.5, float("nan"), float("inf")):
            with pytest.raises(RuntimeError):
                await number.async_set_native_value(invalid)
    assert [call.args for call in coordinator.async_write_property.await_args_list] == [
        (3, 5, 1),
        (3, 5, 0),
        (3, 2, 100),
        (3, 2, 37),
        (3, 3, 480),
    ]
    assert [
        sensors.F11Sensor(coordinator, entry(), *d).native_value for d in sensors.DEFINITIONS
    ] == [80, "charging", "on", 3580]
    connected = binary.F11BinarySensor(coordinator, entry(), "connection")
    charging = binary.F11BinarySensor(coordinator, entry(), "charging", (2, 1034))
    assert connected.available and connected.is_on and charging.is_on
    coordinator.data["available"] = False
    assert (
        connected.available
        and not connected.is_on
        and not light.available
        and not charging.available
    )


@pytest.mark.asyncio
async def test_write_property_allowlist(modules):
    module = modules("coordinator")
    coordinator = module.F11Coordinator(object(), entry())
    coordinator._session = SimpleNamespace(write=AsyncMock())
    coordinator._ready = True
    coordinator._report({(3, 2): 129})
    await coordinator.async_write_property(3, 5, 1)
    await coordinator.async_write_property(3, 3, 480)
    for args in ((3, 1, 1), (3, 5, 2), (3, 3, 481), (3, 2, 101), (3, 3, 1.5)):
        with pytest.raises(RuntimeError):
            await coordinator.async_write_property(*args)
    assert [call.args for call in coordinator._session.write.await_args_list] == [
        (3, 5, 1),
        (3, 3, 480),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "authentication", "cancelled"])
async def test_connection_validation_always_releases_client(modules, monkeypatch, failure):
    module = modules("config_flow")
    removed = []
    monkeypatch.setattr(
        module.bluetooth,
        "async_register_callback",
        lambda *_args: lambda: removed.append(True),
        raising=False,
    )
    monkeypatch.setattr(
        module.bluetooth, "async_ble_device_from_address", lambda *_a, **_k: object()
    )
    info = SimpleNamespace(
        service_data={"0000fe95-0000-1000-8000-00805f9b34fb": bytes.fromhex("1059925f00")}
    )
    monkeypatch.setattr(
        module.bluetooth, "async_last_service_info", lambda *_a, **_k: info, raising=False
    )
    client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
    session = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(module, "connect", AsyncMock(return_value=client))
    monkeypatch.setattr(module, "F11Session", lambda *_a: session)
    if failure:
        error = (
            module.AuthenticationError if failure == "authentication" else asyncio.CancelledError
        )
        session.start.side_effect = error()
        with pytest.raises(error):
            await module.validate_connection(object(), "AA:BB:CC:DD:EE:FF", "00" * 12)
    else:
        await module.validate_connection(object(), "AA:BB:CC:DD:EE:FF", "00" * 12)
    session.close.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert removed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["authentication", "cancelled", "unload"])
async def test_failed_reconfigure_preserves_old_entry(modules, monkeypatch, failure):
    module = modules("config_flow")
    current = entry()
    manager = SimpleNamespace(
        async_unload=AsyncMock(return_value=failure != "unload"), async_reload=AsyncMock()
    )
    flow = module.ConfigFlow()
    flow.hass = SimpleNamespace(config_entries=manager)
    monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: current, raising=False)
    error = asyncio.CancelledError if failure == "cancelled" else module.AuthenticationError
    validate = AsyncMock(side_effect=error())
    monkeypatch.setattr(module, "validate_connection", validate)
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await flow.async_step_reconfigure({"token": "11" * 12})
    else:
        result = await flow.async_step_reconfigure({"token": "11" * 12})
        assert result["type"] == "form"
        assert result["errors"]["base"] == (
            "cannot_connect" if failure == "unload" else "invalid_auth"
        )
    assert current.data["token"] == "00" * 12
    if failure == "unload":
        validate.assert_not_awaited()
        manager.async_reload.assert_not_awaited()
    else:
        manager.async_reload.assert_awaited_once_with(current.entry_id)
