# HomeControl validation — 2026-10-06

Windows 11 laptop with Intel Iris Xe. No RTX 3050 is attached.

- 31 automated Python tests pass: original CPU/GPU controls, usage budgets and terminal; FPS calculations, active swap chains, target switches/exits, stale/no-frame states, helper checksum/permissions/errors; GPU cleanup and expiry/thermal/loss paths; power cancellation and non-forcing arguments; protected devices, deduplicated selections, partial failures and disconnected recovery; public web app assets and private-route authentication.
- Node web app sign-in checks pass: opt-in persistence, relaunch, disconnect, invalid keys, standalone help visibility, automatic sign-in fragments, blocked storage and late requests after logout.
- Web app assets provide an opaque 180 px Apple touch icon, 192/512 px manifest icons, standalone display and safe-area spacing. Physical iPhone Home Screen installation still requires the user to add the icon from Safari.
- The installed dashboard and public manifest/icons load successfully after a startup-task restart. A 390 x 844 browser viewport shows the install help and live dashboard without horizontal overflow; terminal is enabled, GPU load is off and device selections are empty.
- Native hardware enumeration and GPU utilization counters work. Live CPU, RAM and battery readings work; unsupported temperatures/power say Unavailable.
- Official PresentMon 2.6.0 binary SHA-256 verified. An additional three-second PresentMon session ran alongside HomeControl with 126 frame rows and exit code 0. Existing PresentMon services remained running.
- Direct3D 11 reference application presented at 60.0 FPS on Iris Xe. HomeControl measured 60.4, 59.8 and 60.3 FPS across successive rolling windows.
- A real Iris Xe workload accepted relative GPU priority +1, changed duty to 0 and back to 1, stopped at its one-minute expiry and stopped on explicit request. Workload is off after testing.
- An independent recovery task was registered under the existing elevated account, ran successfully with an empty journal, and was removed after the check. No actual PnP devices were disabled or restarted.
- Existing access key, usage database, original CPU settings and enabled terminal preference are preserved. Device selections are empty and automatic FPS is enabled.

Remaining hardware acceptance: compare against an actual game's built-in FPS counter on Iris Xe and RTX 3050, and test device actions/recovery on selected spare peripherals. The currently running background game produced no frames during the pin check, so its FPS was correctly blank. Power actions and device mutations were tested with mocks; the laptop was not locked, restarted or shut down.
