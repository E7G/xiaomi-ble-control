"""Discover F11 and validate the Mi Standard BLE token through a real login."""

import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_TOKEN
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import connect
from .helpers import normalize_address, normalize_token, supported_advertisement
from .protocol import AuthenticationError, F11Session


class UnsupportedDevice(ValueError):
    """The selected address is not an F11."""


async def validate_connection(hass, address, token):
    """Temporary connection is always released, including failed authentication."""
    client = session = None
    remove = bluetooth.async_register_callback(
        hass,
        lambda *_: None,
        {"address": address, "connectable": True},
        bluetooth.BluetoothScanningMode.ACTIVE,
    )
    try:
        async with asyncio.timeout(45):
            if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
                await bluetooth.async_process_advertisements(
                    hass,
                    lambda _: True,
                    {"address": address, "connectable": True},
                    bluetooth.BluetoothScanningMode.ACTIVE,
                    15,
                )
            info = bluetooth.async_last_service_info(hass, address, connectable=True)
            if info is None or not supported_advertisement(info.service_data):
                raise UnsupportedDevice("Only szxzh.fan.f11 is supported")
            client = await connect(hass, address)
            session = F11Session(client, bytes.fromhex(token), lambda _: None)
            await session.start()
    finally:
        remove()
        if session:
            await session.close()
        if client and client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass


def schema(address=None, name=DEFAULT_NAME):
    fields = {}
    if address is None:
        fields[vol.Required(CONF_ADDRESS)] = cv.string
    fields[vol.Required(CONF_TOKEN)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    fields[vol.Optional(CONF_NAME, default=name)] = cv.string
    return vol.Schema(fields)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._address = None

    async def async_step_bluetooth(self, discovery_info):
        if not supported_advertisement(discovery_info.service_data):
            return self.async_abort(reason="not_supported")
        self._address = normalize_address(discovery_info.address)
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": DEFAULT_NAME}
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                address = normalize_address(self._address or user_input[CONF_ADDRESS])
            except ValueError:
                errors[CONF_ADDRESS] = "invalid_address"
            try:
                token = normalize_token(user_input[CONF_TOKEN])
            except ValueError:
                errors[CONF_TOKEN] = "invalid_token"
            if not errors:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                try:
                    await validate_connection(self.hass, address, token)
                except UnsupportedDevice:
                    errors["base"] = "not_supported"
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    name = user_input.get(CONF_NAME, DEFAULT_NAME)
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_ADDRESS: address,
                            CONF_TOKEN: token,
                            CONF_NAME: name,
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=schema(self._address), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                token = normalize_token(user_input[CONF_TOKEN])
            except ValueError:
                errors[CONF_TOKEN] = "invalid_token"
            if not errors:
                # Unload first so the existing session releases the one device
                # connection. A failed validation reloads the unchanged entry.
                unloaded = await self.hass.config_entries.async_unload(entry.entry_id)
                if not unloaded:
                    errors["base"] = "cannot_connect"
                else:
                    try:
                        await validate_connection(self.hass, entry.data[CONF_ADDRESS], token)
                    except asyncio.CancelledError:
                        await asyncio.shield(self.hass.config_entries.async_reload(entry.entry_id))
                        raise
                    except UnsupportedDevice:
                        errors["base"] = "not_supported"
                    except AuthenticationError:
                        errors["base"] = "invalid_auth"
                    except Exception:
                        errors["base"] = "cannot_connect"
                    if errors:
                        await self.hass.config_entries.async_reload(entry.entry_id)
                    else:
                        name = user_input.get(CONF_NAME, entry.title)
                        self.hass.config_entries.async_update_entry(entry, title=name)
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                CONF_TOKEN: token,
                                CONF_NAME: name,
                            },
                        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema(entry.data[CONF_ADDRESS], entry.title),
            errors=errors,
        )
