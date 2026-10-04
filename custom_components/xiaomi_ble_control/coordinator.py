"""One authenticated connection per config entry, independent of entity lifecycle."""

import asyncio
import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_TOKEN, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .protocol import F11Session

_LOGGER = logging.getLogger(__name__)


async def connect(hass, address, disconnected_callback=None):
    """Use HA's routing for local adapters and active Bluetooth Proxies."""
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise ConnectionError("No connectable Bluetooth advertisement")
    return await establish_connection(
        BleakClientWithServiceCache,
        device,
        address,
        disconnected_callback=disconnected_callback,
        ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        ),
    )


class F11Coordinator(DataUpdateCoordinator):
    """Receive real state; writes never set optimistic entity state."""

    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=entry.title, update_interval=None)
        self.entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self._token = bytes.fromhex(entry.data[CONF_TOKEN])
        self._session = None
        self._task = None
        self._removers = []
        self._properties = {}
        self._ready = False
        self._last_report = 0
        self._status = "waiting_for_advertisement"
        self._source = None
        self._rssi = None
        self.data = self._state()

    def _state(self):
        return {
            "available": self._ready and (3, 2) in self._properties,
            "properties": self._properties.copy(),
            "bluetooth_status": self._status,
            "bluetooth_source": self._source,
            "rssi": self._rssi,
        }

    def _publish(self):
        self.async_set_updated_data(self._state())

    def _advertisement(self, info, _change):
        self._source = info.source
        self._rssi = info.rssi

    def _report(self, properties):
        self._last_report = asyncio.get_running_loop().time()
        self._properties.update(properties)
        if self._ready:
            self._status = "connected"
            self._publish()

    async def async_start(self):
        self._removers.append(
            bluetooth.async_register_callback(
                self.hass,
                self._advertisement,
                {"address": self.address, "connectable": True},
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        self._removers.append(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.async_stop)
        )
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"Xiaomi BLE Control {self.address}"
        )

    async def async_stop(self, _event=None):
        for remove in self._removers:
            remove()
        self._removers.clear()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self):
        delay = 5
        while True:
            client = session = None
            try:
                if (
                    bluetooth.async_ble_device_from_address(
                        self.hass, self.address, connectable=True
                    )
                    is None
                ):
                    self._status = "waiting_for_advertisement"
                    await asyncio.sleep(10)
                    continue
                self._status = "connecting"
                self._publish()
                disconnected = asyncio.Event()
                client = await connect(
                    self.hass, self.address, lambda _, event=disconnected: event.set()
                )
                session = F11Session(client, self._token, self._report)
                self._status = "authenticating"
                self._publish()
                # Never carry stale state across authentication sessions.
                self._properties.clear()
                await session.start()
                self._session = session
                self._ready = True
                self._last_report = asyncio.get_running_loop().time()
                self._status = "connected"
                self._publish()
                deadline = self._last_report + 3600
                delay = 5
                while not disconnected.is_set():
                    if session.worker_done:
                        session.raise_worker_error()
                    now = asyncio.get_running_loop().time()
                    if now > deadline or now - self._last_report > 30:
                        self._status = "reconnecting"
                        break
                    try:
                        await asyncio.wait_for(disconnected.wait(), 5)
                    except TimeoutError:
                        pass
                if disconnected.is_set():
                    self._status = "disconnected"
            except asyncio.CancelledError:
                self._status = "stopped"
                raise
            except Exception as err:
                self._status = type(err).__name__
                _LOGGER.debug("%s connection failed (%s)", self.address, self._status)
            finally:
                self._session = None
                self._ready = False
                self._publish()
                if session:
                    await session.close()
                if client and client.is_connected:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def async_write_speed(self, value):
        await self.async_write_property(3, 2, value)

    async def async_write_property(self, siid, piid, value):
        limits = {(3, 2): 100, (3, 3): 480, (3, 5): 1}
        if (
            (siid, piid) not in limits
            or not isinstance(value, int)
            or not 0 <= value <= limits[siid, piid]
        ):
            raise HomeAssistantError("Unsupported F11 property or value")
        if not self.data["available"] or self._session is None:
            raise HomeAssistantError("F11 Bluetooth connection unavailable")
        try:
            await self._session.write(siid, piid, value)
        except Exception:
            # Do not include upstream exception reprs or protocol credentials.
            raise HomeAssistantError("F11 property command failed") from None
