# HomeControl validation — 2026-10-06

Windows 11 laptop with Intel Iris Xe. No RTX 3050 is attached.

- 83 automated Python tests pass: original CPU/GPU controls, usage budgets and terminal; FPS calculations, active swap chains, target switches/exits, stale/no-frame states, helper checksum/permissions/errors; power cancellation and non-forcing arguments; protected devices, deduplicated selections, partial failures and disconnected recovery; public web app assets and private-route authentication; Tweakout, gradual CPU lag and audio playback/recovery cases below.
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

Tweakout update (v3.4):

- Added authenticated selected-laptop mode/status/cancel routes, a 12-second effects-only preview and a separately confirmed 20-second CPU-1% sequence followed by normal shutdown. Cancel exists only on the dashboard. There is no local effects-window Cancel control or Escape handler, no real graphics-driver restart and no rapid full-screen flashing.
- New tests cover confirmation, strict inputs, preview without power changes, exact prior CPU restoration on Cancel/expiry, ordering before shutdown, duplicate starts, pending power conflicts, worker exit/stall/resume, helper-start failure, recovery registration failure, partial CPU writes, durable recovery after termination, failed recovery retention, shutdown rejection, corrupted records, authenticated routes and selected-laptop relay. Every laptop CPU write and shutdown in these tests is mocked. The existing disposable-child CPU job test is unchanged.
- Node checks pass for selected-laptop confirmation, changing targets before confirmation, effects-only preview, dashboard cancellation and recovery-pending controls, alongside existing sign-in, devices and internet checks. The complete dashboard script parses successfully.
- The installed elevated startup app ran the real effects-only preview. Native screenshot inspection confirms the fullscreen simulated display, fake diagnostic text, countdown and dashboard-cancel instruction. Windows accepted the looping audio request without error; subjective sound quality has not been measured. Slow dark palette changes occur every 2.5 seconds. The existing external hardware overlay can remain visible above the effect.
- A real preview expired cleanly. Another preview was cancelled through the dashboard; the worker stopped and all generated control/result/audio files were removed. CPU settings were not changed by previews. Full-mode shutdown and the laptop-wide 1% cap were deliberately tested with mocks; this laptop was not shut down.
- The independent Tweakout recovery task registered as Highest / Interactive under the existing account, ran against an empty disposable journal and removed itself. Repeated cleanup is idempotent. The completed check preserved the existing 99% AC/DC settings and requested no CPU writes.
- The installed dashboard presents the selected laptop and shutdown deadline before confirmation. Opening the confirmation and going back does not start a sequence. Existing key and usage data remain; current user device selections/recovery records are retained. The startup task continues to run at sign-in, and internet limiting starts Unlimited.

Computer/app launcher update (v3.5):

- Computer picker, install guidance, controls and status messages now cover Windows desktops and laptops. Existing saved connections and the legacy data/API names remain compatible. Desktops show unavailable battery/temperature fields without blocking other controls.
- Installed-app discovery found 162 Start-menu apps and available desktop shortcuts on this machine. Unavailable cloud-only desktop links are skipped rather than failing the entire inventory. Discovery and cached authenticated inventory are independent of live telemetry.
- Seven new Python tests cover stable opaque IDs with redacted paths, selected-app dispatch, unknown/malformed IDs, uninstalled apps, native failure reporting, inventory errors, concurrent refresh/launch, cached metrics access, route authentication and selected-computer relaying. All 68 Python tests pass. Node checks also cover app search, launch IDs, empty refresh, invalid choices and clearing the old app/terminal selection when changing computers.
- The installed app launched Calculator through the authenticated dashboard. Windows accepted the request and the Calculator window was present. Launch uses the existing Explorer desktop automation object; it supplies no arbitrary executable arguments. Physical second-computer launch acceptance still needs that computer running the update.

Lag and effects update (v3.6):

- Added a selected-computer CPU ramp of one percentage point per second, a configurable 1–99% floor and 0–60-second hold. Nine tests cover independent AC/DC caps, low original values, input validation, other-mode conflicts, task-arm failure, partial writes, expiry/cancel/close, delayed resume, recovery failure/retry, independently expired records, authentication and relaying. All machine-wide CPU writes in unit tests are mocked.
- A short native check armed the elevated independent recovery task, lowered both actual caps from 99% to 98%, cancelled and verified exact restoration to 99%/99%. It did not approach the 1% floor or request shutdown. Existing keys/preferences were preserved.
- Replaced the diagnostic-style effect with Windows-style error dialogs, limited display corruption and a simulated crash screen. Native screenshot verification confirms the effect and small HomeControl identification, with no computer-screen countdown or Cancel control. Dashboard cancellation stopped the real preview and its audio. The existing confirmed full-mode 20-second CPU cap/shutdown lifecycle remains; actual shutdown is tested with mocks.
- Loaded Windows Error, Critical Stop, Exclamation and Hardware Fail WAV cues locally and mixed them with a stronger buzz in a bounded 10-second PCM loop. Windows' default waveform mapper returned error 2 on this machine while explicit output 0 accepted playback. The new fallback produced a measured native output peak of 0.7883 at unchanged 50% speaker volume, with no audio error. This proves an output signal, not a subjective assessment of sound quality.
- Six effects tests cover PCM bounds/amplitude, resampling and rejected formats, countdown-free display stages, mapper fallback, loop lifetime, partial native failures, idempotent close and buffer retention on failed reset. Speaker diagnostics read volume/mute/peak only and capture no audio. The 83-test Python suite and Node dashboard checks pass, including lag dispatch/cancel, mutual exclusion and resetting stale controls when switching computers.

Confirmation update:
- Removed HomeControl text from the effect window.
- Dashboard tests verify that the first confirmation makes no start request and that final confirmation requires the saved-work acknowledgment.
- Atomic JSON replacement retries transient Windows PermissionError briefly and still raises persistent failures.
- No Service Host termination or automatic Windows Update installation was added.

Release 3.7 (2026-10-07):

- All 86 Windows Python tests pass, including keyboard input validation, Unicode event pairs, blocked input and authenticated dispatch. Node dashboard checks pass for text/key dispatch, error display, computer switching and two-step Tweakout confirmation. A native keyboard fixture refused to send when its window was not foreground; real remote typing into a foreground app still needs user acceptance.
- The PowerShell updater suite passes 35 assertions with real temporary file copies and mocked system operations. Covers success, missing task installation, startup/health/copy failure rollback, key/history/settings preservation, backup content, text line endings, checksum corruption, path traversal, real junction rejection, pending CPU recovery and retention of disconnected device records.
- The packaged updater ran through the existing elevated account on this laptop. Authenticated status reports 3.7; its scheduled task is Running, enabled, Highest/Interactive, with an enabled sign-in trigger. Six existing credential/preference files were byte-identical, usage entries remained, and all eight disconnected-device recovery records were retained. The temporary release-testing task was removed afterward.
- Updater backups are account/SYSTEM restricted. App files replace atomically, device journals use the existing named recovery mutex during copying, and independent recovery tasks remain registered. Custom data-location paths are retained. No reboot, full Tweakout shutdown, service-host termination or physical device mutation was performed for this release.
- Source-only ZIPs include official helper licenses/checksums/source and a generated normalized-text/binary update manifest. Keys, databases, logs, generated locations, recovery records and work artifacts are excluded. OTA updates remain deferred. Existing RTX 3050/game-counter/spare-peripheral acceptance limitations still apply.
