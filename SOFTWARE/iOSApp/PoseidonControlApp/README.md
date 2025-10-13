# Poseidon Control iOS App Prototype

This SwiftUI app mirrors the REST workflows that the Poseidon web UI already exposes so you can drive the pumps from an iPhone or iPad.

## Project layout

```
PoseidonControlApp/
 ├── PoseidonControlApp/
 │   ├── PoseidonControlAppApp.swift   # App entry point
 │   ├── ContentView.swift             # Home dashboard (server status, pumps, logs)
 │   ├── Models/                       # Codable models shared with the REST API
 │   ├── Services/                     # PoseidonAPI wrapper (async/await over FastAPI)
 │   ├── Utilities/                    # Helpers (numeric parsing, etc.)
 │   └── Views/
 │        ├── PumpDetailView.swift     # Per pump control + calibration
 │        ├── SettingsView.swift       # Server URL and auto-refresh options
 │        └── BannerView.swift         # Reusable status banner
 └── README.md
```

## Getting started

1. On macOS, open Xcode 15+ and create a new **App** project named `PoseidonControlApp`.
2. Set Interface to `SwiftUI`, Language to `Swift`, and make sure “Include Tests” is off.
3. Replace the generated files with the sources in `PoseidonControlApp/` (drag them into the Xcode project, keeping the folder references).
4. Add a **Network** App Transport Security exception so the app can talk to your Pi over HTTP:
   - In Xcode, open the app target’s `Info` tab → `+` → `App Transport Security Settings`.
   - Inside, add `Allow Arbitrary Loads` = `YES` (or restrict to your Pi’s host if you terminate TLS elsewhere).
5. Build & run on a device that’s on the same network as the Raspberry Pi that hosts the Poseidon web service.

## Features

- View board connection state, remaining steps per pump, and recent log lines.
- Send speed/accel/run/jog/pause/stop/resume commands for any of the four pumps.
- Manage calibration values (steps per mm, invert flag, travel and volume compensation).
- Read and update the shared syringe model list.
- Optional auto polling so the UI remains in sync without manual refresh.

## Next steps / ideas

- Add authentication (token prompt) once the backend exposes it.
- Bundle the REST base URL in build configs for staging vs. production units.
- Store recent commands locally so the UI can pre-fill typical values per pump.
- Implement push notifications (via WebSocket) for real-time event streaming once the FastAPI service adds it.

