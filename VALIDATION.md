# HomeControl validation — 2026-10-06

Windows 11 laptop with Intel Iris Xe. No RTX 3050 is attached.

- 45 automated Python tests pass: original CPU/GPU controls, usage budgets and terminal; FPS calculations, active swap chains, target switches/exits, stale/no-frame states, helper checksum/permissions/errors; power cancellation and non-forcing arguments; protected devices, deduplicated selections, partial failures and disconnected recovery; public web app assets and private-route authentication.
- Node web app sign-in checks pass: opt-in persistence, relaunch, disconnect, invalid keys, standalone help visibility, automatic sign-in fragments, blocked storage and late requests after logout.
- Web app assets provide an opaque 180 px Apple touch icon, 192/512 px manifest icons, standalone display and safe-area spacing. Physical iPhone Home Screen installation still requires the user to add the icon from Safari.
- The installed dashboard and public manifest/icons load successfully after a startup-task restart. A 390 x 844 browser viewport shows the install help and live dashboard without horizontal overflow; terminal is enabled, GPU workload is removed and saved device selections are preserved.
- Native hardware enumeration and GPU utilization counters work. Live CPU, RAM and battery readings work; unsupported temperatures/power say Unavailable.
- Official PresentMon 2.6.0 binary SHA-256 verified. An additional three-second PresentMon session ran alongside HomeControl with 126 frame rows and exit code 0. Existing PresentMon services remained running.
- Direct3D 11 reference application presented at 60.0 FPS on Iris Xe. HomeControl measured 60.4, 59.8 and 60.3 FPS across successive rolling windows.
- GPU workload UI, endpoints and worker files have been removed at the user's request; native GPU enumeration and the power/clock caps remain.
- An independent recovery task was registered under the existing elevated account, ran successfully with an empty journal, and was removed after the check. No actual PnP devices were disabled or restarted.
- Existing access key, usage database, original CPU settings and enabled terminal preference are preserved. Saved device selections are preserved and automatic FPS is enabled.

Remaining hardware acceptance: compare against an actual game's built-in FPS counter on Iris Xe and RTX 3050, and test device actions/recovery on selected spare peripherals. The currently running background game produced no frames during the pin check, so its FPS was correctly blank. Power actions and device mutations were tested with mocks; the laptop was not locked, restarted or shut down.

Internet limiter update:

- Official WinDivert 2.2.2 x64 DLL and driver downloaded from the vendor release, SHA-256 checked; Windows Authenticode reports the driver signature Valid. License notices and corresponding source archive are included.
- Native disposable localhost transfers measured 3.92 Mbps down and 3.92 Mbps up with a 4 Mbps cap. Closing the filters restored 541.20 Mbps in the same local test. These are test transfers, not an internet speed test.
- The installed elevated server successfully applied 20 Mbps, changed to 5 Mbps and returned to Unlimited. The authenticated dashboard remained reachable. Startup defaults to Unlimited.
- Native filter compile/evaluation covers IPv4/IPv6, incoming/outgoing traffic and private-address/dashboard exemptions. Tests cover decimal Mbps validation, pacing, partial-start cleanup, worker crash/stall cleanup and no automatic resumption.
- Device UI checks cover saving selections before actions and aborting when saving fails. Enable/Disable verify Windows device state; unconfirmed disable keeps recovery armed. Protected devices use locks and specific reasons. No real USB/keyboard devices were disabled or restarted.

Multiple laptops and USB hub/Bluetooth update:

- Home Wi-Fi only, as requested. No internet tunnel is configured. The temporary Tailscale/ngrok setup has been removed from the app.
- Native inventory confirms both USB Root Hub (USB 3.0) entries and Intel Wireless Bluetooth are selectable while Bluetooth PAN is disconnected and no protected storage/network descendant is attached. No real devices were disabled or restarted.
- The installed dashboard has no GPU workload card. Checking the three newly selectable rows and pressing Restart displays the affected-device confirmation. Cancel sent no action; reloading restored the existing saved 3 USB/4 keyboard selections, with no recovery records.
- Tests cover hub/radio confirmation, connected/unknown Bluetooth PAN, newly attached storage, child-before-parent disable, parent-before-child recovery, restart recovery, UTF-16 PnP output and removed routes.
- Multiple-laptop tests cover private-address validation, rejected keys, persistent connections with redacted API output, authenticated relaying, correct target selection, redirect refusal, removal and stale-response rejection. An actual second Windows laptop is not attached to this development environment, so its end-to-end hardware acceptance remains to be done after installing the update there.

- The updated installed dashboard displays the Laptops selector and add form, live hardware readings and preserved settings. The browser form rejects public addresses without saving them. The local startup task is Running and the existing access key is accepted.
