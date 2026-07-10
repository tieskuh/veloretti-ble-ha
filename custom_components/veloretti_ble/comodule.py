"""Pure Comodule BLE protocol layer for Veloretti e-bikes.

This module knows how to talk to the Comodule telematics module that Veloretti
(and many other e-bike brands) use. It is deliberately free of any Home
Assistant imports so it can be unit-tested and reused.

Protocol, reverse-engineered from the decompiled Comodule SDK and live captures:

1. The Metrics/Security characteristics require a BLE bond ("Just Works", no PIN).
2. App-level auth handshake: read a 20-byte challenge from the Security service,
   compute ``SHA1(challenge + private_key)`` and write it back. This unlocks the
   telemetry registers. The private key is Comodule's shared default key; it only
   grants **read access to telemetry** (battery, speed, assist) — it does not
   touch the separate, encrypted lock/security channel.
3. On-demand register read: write a 2-byte register id to the REGISTER_ID
   characteristic, then read the REGISTER characteristic. The reply is a 10-byte
   packet ``[id0][id1][8 payload bytes]`` with the register's current value.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from bleak import BleakClient

from .const import (
    METRICS_REGISTER_ID_UUID,
    METRICS_REGISTER_UUID,
    SECURITY_AUTH_UUID,
    SECURITY_CHALLENGE_UUID,
)

_LOGGER = logging.getLogger(__name__)

# Comodule's shared "defaultPrivateKey": the SDK constant "FFFFFFFFFFFFFFFF"
# (8 bytes) padded to 20 bytes. Read-only telemetry auth; see module docstring.
DEFAULT_PRIVATE_KEY = bytes([0xFF] * 20)

# Register ids (this module = BLE profile "comodule-2020").
REG_BATTERY = bytes([0x00, 0xC1])
REG_ASSIST = bytes([0x00, 0xC0])
REG_SPEED = bytes([0x02, 0x50])
REG_MOTION = bytes([0x00, 0xC3])

# Keys used across the integration (data dict + sensor descriptions).
KEY_BATTERY = "battery_soc"
KEY_ASSIST = "assist_level"
KEY_LIGHTS = "lights"
KEY_SPEED = "speed"
KEY_MOTION = "motion_raw"


@dataclass(slots=True)
class ComoduleData:
    """Decoded telemetry from one poll."""

    battery_soc: int | None = None
    assist_level: int | None = None
    lights: bool | None = None
    speed_kmh: int | None = None
    motion_raw: int | None = None
    # Raw 10-byte register packets (hex) keyed by register key — for diagnostics
    # and for calibrating the experimental values later.
    raw: dict[str, str] = field(default_factory=dict)

    def has_any(self) -> bool:
        """Return True if at least one value was decoded."""
        return any(
            v is not None
            for v in (
                self.battery_soc,
                self.assist_level,
                self.lights,
                self.speed_kmh,
                self.motion_raw,
            )
        )


def _u16_be(packet: bytes, i: int) -> int:
    return (packet[i] << 8) | packet[i + 1]


def _decode(reg_id: bytes, packet: bytes) -> tuple[str, int | None]:
    """Decode a 10-byte register packet into (key, value)."""
    if reg_id == REG_BATTERY:
        # byte 7 = state-of-charge %, plain 0..100. Confirmed against the app.
        soc = packet[7]
        return KEY_BATTERY, soc if 0 <= soc <= 100 else None
    if reg_id == REG_ASSIST:
        # {00,C0} is the combined settings register: byte 2 = assist level 0..4,
        # byte 3 = lights (handled in async_poll). Confirmed live on the bike.
        # Bound at 5 (one over the known max) so a glitch byte reads as unknown.
        lvl = packet[2]
        return KEY_ASSIST, lvl if 0 <= lvl <= 5 else None
    if reg_id == REG_SPEED:
        # byte 2 = speed in km/h (~1:1). Calibrated against a live ride: ~20 km/h
        # top speed matched a byte-2 peak of 21. Confirmed 0 at rest.
        return KEY_SPEED, packet[2]
    if reg_id == REG_MOTION:
        # uint16(b2,b3) — fine motion / wheel-RPM indicator (experimental).
        return KEY_MOTION, _u16_be(packet, 2)
    return "", None


def _apply(data: ComoduleData, reg_id: bytes, packet: bytes) -> bool:
    """Decode one register packet into ``data``. Returns True if a field was set."""
    key, value = _decode(reg_id, packet)
    if key == KEY_BATTERY:
        data.battery_soc = value
    elif key == KEY_ASSIST:
        data.assist_level = value
        # The {00,C0} register carries the light state in byte 3 (0=off, 1=on).
        data.lights = bool(packet[3])
    elif key == KEY_SPEED:
        data.speed_kmh = value
    elif key == KEY_MOTION:
        data.motion_raw = value
    else:
        return False
    data.raw[key] = packet.hex(" ")
    return True


def apply_notification(data: ComoduleData, packet: bytes) -> bool:
    """Apply a raw 10-byte notifier push (``[id0][id1][8 payload]``) to ``data``.

    The module pushes a register on the notifier the moment its value changes, so
    this is how live assist/light/speed changes reach us while connected.
    """
    if len(packet) < 10:
        return False
    return _apply(data, packet[0:2], packet)


# Register key -> id, in poll order (battery first — the most valuable value).
POLL_REGISTERS: dict[str, bytes] = {
    KEY_BATTERY: REG_BATTERY,
    KEY_ASSIST: REG_ASSIST,
    KEY_SPEED: REG_SPEED,
    KEY_MOTION: REG_MOTION,
}


class ComoduleAuthError(Exception):
    """Raised when the auth handshake with the module fails."""


class ComoduleClient:
    """Stateless helper that authenticates and polls a connected bike."""

    def __init__(self, private_key: bytes = DEFAULT_PRIVATE_KEY) -> None:
        self._key = private_key

    async def async_authenticate(self, client: BleakClient) -> None:
        """Perform the SHA1 challenge/response handshake to unlock telemetry."""
        try:
            challenge = bytes(await client.read_gatt_char(SECURITY_CHALLENGE_UUID))
        except Exception as err:  # noqa: BLE001 - surfaced as a typed error
            raise ComoduleAuthError(f"reading challenge failed: {err}") from err
        auth_hash = hashlib.sha1(challenge + self._key).digest()  # noqa: S324
        try:
            await client.write_gatt_char(SECURITY_AUTH_UUID, auth_hash, response=True)
        except Exception as err:  # noqa: BLE001
            raise ComoduleAuthError(f"writing auth hash failed: {err}") from err

    async def async_read_register(
        self, client: BleakClient, reg_id: bytes
    ) -> bytes | None:
        """Select a register and read its current 10-byte packet.

        Returns None if the module did not answer with the requested register
        (e.g. transient, or the value is unavailable in this state).
        """
        await client.write_gatt_char(METRICS_REGISTER_ID_UUID, reg_id, response=True)
        packet = bytes(await client.read_gatt_char(METRICS_REGISTER_UUID))
        if len(packet) < 10 or packet[0:2] != reg_id:
            return None
        return packet

    async def async_poll(
        self, client: BleakClient, want: Iterable[str] | None = None
    ) -> ComoduleData:
        """Authenticate (if needed) and read the requested registers."""
        await self.async_authenticate(client)

        keys = list(want) if want is not None else list(POLL_REGISTERS)
        data = ComoduleData()
        for key in keys:
            reg_id = POLL_REGISTERS.get(key)
            if reg_id is None:
                continue
            try:
                packet = await self.async_read_register(client, reg_id)
            except Exception as err:  # noqa: BLE001 - one bad register != whole poll
                _LOGGER.debug("register %s read failed: %s", key, err)
                continue
            if packet is None:
                continue
            _apply(data, reg_id, packet)
        return data
