# Poseidon Touch Injection Pump Suite

This folder contains a clean-room reimplementation of the Poseidon
injection pump control stack. The design targets four syringe pumps
driven by two Arduino Uno + CNC Shield v3 controller boards.

## Firmware

* `firmware/poseidon_dual_pump.ino` — flash this sketch onto each Uno.
  Compile once with `BOARD_ROLE_PRIMARY=1` (pumps 1–2) and once with
  `BOARD_ROLE_PRIMARY=0` (pumps 3–4). The code stores speed, acceleration
  and calibration data in EEPROM and accepts the same CSV command frames
  used by the legacy GUI.

## Touch GUI

* `gui/poseidon_touch_gui.py` — standalone PyQt5 application optimised
  for a 1024×600 touch display. It manages both controller boards, offers
  syringe presets, guided calibration, and per-pump jog/run controls.

## Running the GUI

```bash
python3 -m pip install pyqt5 pyserial
python3 NEW_SYSTEM/gui/poseidon_touch_gui.py
```

The application persists calibration data in
`~/.poseidon_pump_calibration.json` so syringe profiles and jog settings
remain available between sessions.
