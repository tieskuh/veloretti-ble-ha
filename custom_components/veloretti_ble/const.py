"""Constants for the Veloretti BLE integration."""

from __future__ import annotations

DOMAIN = "veloretti_ble"

# --- BLE identity -----------------------------------------------------------
# The bike advertises its GAP name as "VELORETTI" (appearance 0x0480, Generic
# Cycling). We match on this local-name prefix for auto-discovery.
BLE_LOCAL_NAME_PREFIX = "VELORETTI"
MANUFACTURER = "Veloretti"

# --- GATT (Comodule telematics module) --------------------------------------
# All Comodule characteristics share the Nordic-style base UUID below; only the
# 2nd 16-bit block differs per characteristic.
_BASE = "-1212-efde-1523-785feabcd123"

# Metrics service: telemetry registers.
METRICS_SERVICE_UUID = f"00001554{_BASE}"
METRICS_NOTIFIER_UUID = f"0000155e{_BASE}"  # notify: pushes registers on change
METRICS_REGISTER_UUID = f"0000155f{_BASE}"  # r/w: the selected register's value
METRICS_REGISTER_ID_UUID = f"00001564{_BASE}"  # r/w: which register to read

# Security service: the app-level auth handshake (unlocks telemetry).
SECURITY_CHALLENGE_UUID = f"00002556{_BASE}"  # read: 20-byte challenge
SECURITY_AUTH_UUID = f"00002557{_BASE}"  # write: SHA1(challenge + key)
SECURITY_STATUS_UUID = f"00002558{_BASE}"  # read: isAuthenticated

# --- Polling ----------------------------------------------------------------
# The bike sleeps and only advertises/accepts connections when awake. We poll
# only while it is actually being advertised (handled by the active-bluetooth
# coordinator), so a sleeping bike never produces errors. Once connected we STAY
# connected and stream change-pushes on the notifier for as long as the bike is
# on; this interval only governs how soon we reconnect after the link drops.
DEFAULT_POLL_INTERVAL_SECONDS = 15

# While streaming, read the battery this often to keep the link verified (and the
# battery fresh) even when nothing else is changing.
KEEPALIVE_SECONDS = 30

# --- Config entry -----------------------------------------------------------
CONF_ADDRESS = "address"
