"""Diagnostics intentionally exclude config-entry data and all credentials."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "address": coordinator.address,
        "available": data["available"],
        "bluetooth_status": data["bluetooth_status"],
        "bluetooth_source": data["bluetooth_source"],
        "rssi": data["rssi"],
        "properties": {
            f"{siid}.p.{piid}": value for (siid, piid), value in data["properties"].items()
        },
    }
