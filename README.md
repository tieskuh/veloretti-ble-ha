# Veloretti BLE — Home Assistant integration

Local **Bluetooth Low Energy** integration for **Veloretti e-bikes**. It reads
your bike's telemetry (battery, charging, assist level, …) directly over
Bluetooth — **no cloud, no account, no Veloretti subscription**, and it never
touches the lock or motor.

> Veloretti bikes use a telematics module made by [Comodule](https://comodule.com),
> the same platform behind several other e-bike brands. This integration talks
> to that module, so it may work on other Comodule-based bikes too (see
> [Compatibility](#compatibility)).

---

## Features

| Entity | Description | Enabled by default |
|---|---|---|
| **Battery** | State of charge, 0–100 % (`device_class: battery`). Keeps showing the last-known value while the bike sleeps, and survives a Home Assistant restart. | ✅ |
| **Connectivity** | On when the bike is currently awake and reachable over Bluetooth, off when it is asleep/out of range (`binary_sensor`, `connectivity`) | ✅ |
| **Last seen** | Timestamp of the last successful readout (`device_class: timestamp`) | ✅ |
| **Assist level** | Pedal-assist level 0–4 | ✅ |
| **Lights** | Headlight on/off (`binary_sensor`, `light`) | ✅ |
| **Speed** | Wheel speed in km/h (roughly calibrated) — only moves while the bike is riding and in range | ⬜️ |
| **Motion (raw)** | Fine motion / wheel-RPM register — experimental | ⬜️ |

> **Not available: total odometer / trip distance.** The bike's module does not
> expose its kilometre total over Bluetooth — the Veloretti app shows it from
> Comodule's cloud, not from the bike directly. This integration is fully local,
> so it can't provide it (verified by an exhaustive register sweep).

The **battery** sensor is the star of the show: because your bike usually sleeps
next to its charger at home, Home Assistant is perfectly placed to log its charge
curve and warn you when it runs low — even though the Veloretti app can only see
it when the app is open. The **Battery** and **Last seen** values stick around
while the bike sleeps (and across a Home Assistant restart), and **Connectivity**
tells you whether the reading is live or the last-known one.

**Speed** and the raw **Motion** sensor are disabled by default. They only read
non-zero while the bike is actually moving *and* still in Bluetooth range — which,
for a bike parked at home, is rarely. Speed is roughly calibrated to km/h; Motion
is a raw wheel-rotation value. Enable them if you want them (see
[Calibration](#calibrating-the-experimental-sensors)).

## How it works (and the sleeping-bike problem)

A Veloretti is **off** almost all the time. While off it does not advertise over
Bluetooth and cannot be connected to — this is normal and expected.

Crucially, **the bike only turns on when you press its power button.** Plugging in
the charger does not wake it, and it never wakes on its own. So Home Assistant can
only read the bike **while you have it switched on** — typically when you turn it
on to ride, or press the power button to check it.

This integration is built around that:

- It only connects and polls **while the bike is on** (advertising in range).
- When the bike is off, it simply **does nothing** — no polling, no errors,
  no log spam.
- **Battery**, **Last seen** and **Connectivity** keep showing the last-known
  reading while the bike is off (and across a Home Assistant restart), so you
  always see the most recent battery level and exactly when it was measured. The
  other sensors (assist, lights, speed/motion) go `unavailable` while off.
- The moment you switch the bike on, Home Assistant reconnects, reads it, and
  updates the values and the *Last seen* timestamp.

So the natural rhythm is: **you switch the bike on → Home Assistant grabs the
current battery level and state and timestamps it → you turn it off again and the
last-known values stay put.** In practice you get a fresh reading every time you
use the bike.

> ℹ️ Only one device can talk to the bike at a time. While Home Assistant is
> connected, the Veloretti app can't connect, and vice-versa. Home Assistant
> connects only briefly for each poll, so this is rarely noticeable, but if the
> app "can't find" the bike, give Home Assistant a moment to release it.

> **No charging sensor.** The bike's module does not expose a charge-current or
> charging-state register over Bluetooth (confirmed by an exhaustive register
> sweep), so this integration deliberately does **not** include a "charging"
> sensor rather than fake one from the battery-level trend. Watch the **Battery**
> sensor's history instead — a rising curve is a charge.

## Compatibility

- **Confirmed:** Veloretti bikes on the `comodule-2020` BLE profile (e.g. the
  **Ivy** and **Ace** generations with the Comodule display, firmware `240118`,
  hardware `3.2.0`).
- **Likely:** other Veloretti models using the same Comodule module.
- **Maybe:** non-Veloretti Comodule e-bikes. The register map differs per
  firmware generation, so battery/assist may land on different bytes. Open an
  issue with a debug dump (see [Troubleshooting](#troubleshooting)) if you'd like
  to help add support.

You need a Home Assistant instance with working **Bluetooth** — either a built-in/
USB adapter on the host, or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
within range of where the bike is parked.

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/tieskuh/veloretti-ble-ha` with category **Integration**.
3. Search for **Veloretti BLE** in HACS and install it.
4. **Restart Home Assistant.**

### Manual

Copy `custom_components/veloretti_ble` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Setup

1. **Switch the bike on** with its power button and keep it near Home Assistant.
   (It's only reachable while it's on.)
2. Home Assistant usually **auto-discovers** the bike — look for a *Veloretti BLE*
   discovery on the **Settings → Devices & services** page and click **Configure**.
   Otherwise, click **+ Add integration**, search for **Veloretti BLE**, and pick
   your bike from the list.
3. **First-time pairing:** the bike requires a Bluetooth bond. Home Assistant
   pairs automatically ("Just Works", no PIN). If the first setup fails, close the
   Veloretti app (so it isn't holding the connection), make sure the bike is on,
   and try again.

That's it — the device and its entities appear once the first poll succeeds.

## Calibrating the experimental sensors

`Speed` is decoded from the bike's motion register and is roughly calibrated to
km/h (a ~20 km/h ride matched the register nicely), but it hasn't been checked
against the bike's own display across the full range. `Motion (raw)` is the finer
wheel-rotation value with no unit yet. If you enable them and note the values
alongside the speed on the bike's display while riding past Home Assistant, you
can refine the scaling — findings in an issue are very welcome.

## Troubleshooting

- **"No Veloretti bikes found" during setup** — the bike is off or out of range.
  Switch it on with the power button, close the Veloretti app, and retry.
- **Entities are `unavailable`** — expected while the bike is off. They recover
  automatically the next time you switch it on. If they never recover, check that
  the bike is in Bluetooth range of your adapter/proxy.
- **Values look wrong on a non-Ivy/Ace model** — the register map may differ.
  Enable debug logging, capture a poll, and open an issue:

  ```yaml
  # configuration.yaml
  logger:
    logs:
      custom_components.veloretti_ble: debug
  ```

  The debug log includes the raw register packets, which is exactly what's needed
  to map a new model.

## Privacy & security

- **Fully local.** Nothing is sent to Veloretti or Comodule. No account or
  internet connection is used.
- **Read-only telemetry.** The integration authenticates to the bike using
  Comodule's shared default telemetry key and only **reads** values. It does
  **not** control the lock, motor, or any setting — those live on a separate,
  encrypted channel that this integration deliberately leaves alone.

## Credits

Built by reverse-engineering the Comodule BLE protocol. Standing on the shoulders
of prior work:

- [Walker73](https://github.com/AxelFougues/Walker73) — open-source Comodule/Super73 dashboard.
- [reverse.bike](https://www.reverse.bike) — Super73 / Comodule GATT documentation.

## Disclaimer

This is an unofficial, community project. It is not affiliated with, endorsed by,
or supported by Veloretti or Comodule. Use at your own risk.

## License

[MIT](LICENSE)
