"""Input and advertisement validation without Home Assistant dependencies."""

import math
import re

from .const import PRODUCT_ID, SERVICE_UUID

# Mi Home F11's actual five buttons; HA's fan percentages are logical levels.
LEVEL_SPEEDS = (0, 1, 25, 50, 75, 100)


def percentage_to_speed(percentage: float) -> int:
    if not math.isfinite(percentage) or not 0 <= percentage <= 100:
        raise ValueError("Percentage must be between 0 and 100")
    return LEVEL_SPEEDS[math.ceil(percentage / 20)]


def speed_to_level(speed: int) -> int:
    if speed <= 0:
        return 0
    return min(range(1, 6), key=lambda level: abs(LEVEL_SPEEDS[level] - speed))


def normalize_address(address: str) -> str:
    address = address.strip().upper()
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise ValueError("Invalid Bluetooth MAC address")
    return address


def normalize_token(token: str) -> str:
    token = token.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{24}", token):
        raise ValueError("Expected a 12-byte BLE token")
    return token


def supported_advertisement(service_data: dict[str, bytes]) -> bool:
    """MiBeacon product ID follows the two-byte frame-control field."""
    data = service_data.get(SERVICE_UUID, b"")
    return len(data) >= 5 and int.from_bytes(data[2:4], "little") == PRODUCT_ID
