# HomeControl

A Windows background app with an iPhone dashboard on your home network. Python 3 with Tcl/Tk is required for the optional screen effects; no third-party Python packages are needed.

## Install or update on the controlled laptop

1. Stop the old version: run Disable-Startup.cmd as administrator and close any manual Start.cmd window.
2. Replace the application files in the same permanent folder, including all Python files and the vendor folder. Your usage data and keys remain in the existing data folder. Keep the folder in place while any device recovery is pending.
3. Run Install-Startup.cmd as administrator using your usual Windows administrator account. It starts the app now and at each Windows sign-in, in the background, including on battery.
4. Run Connection-Info.cmd. It verifies the key against the live server and prints the phone address and automatic sign-in link. Keep that link private.
5. Open the address in Safari while on the same home Wi-Fi. Set the laptop's Wi-Fi network profile to Private. The startup installer allows port 8765 only on Private networks from the local subnet. Do not forward this port on your router.

Start.cmd runs manually with a console; keep it open for that mode. Startup runs at Windows sign-in, not before login. The laptop must be awake and connected. Keep the app folder in place or reinstall startup after moving it. Logs are in the data folder's background.log. Disable-Startup.cmd stops the scheduled copy and removes its task/firewall rule; it does not restore power limits.

## Multiple laptops on home Wi-Fi

Install HomeControl on each Windows laptop and run **Install-Startup.cmd as administrator** using that laptop’s own Windows account. Keep existing keys and data folders when updating. Run Connection-Info.cmd on the second laptop and copy its home-network address and access key.

Open the first laptop’s dashboard on your iPhone, expand **Laptops → Add another laptop**, enter a name, the other laptop’s `http://192.168.x.x:8765/` address and its key, then tap **Add laptop**. Choose the laptop in **Control laptop**. CPU/GPU settings, app time, daily budgets, FPS, internet caps, devices, power actions and terminal commands now apply to the selected laptop. Switching clears unsaved device choices and terminal output so one laptop’s controls are not carried to another. The dashboard rejects stale responses after a switch.

The first laptop relays requests on the home network and stores the other laptop’s key only in its private runtime data folder. Target keys never appear in API responses or GitHub. Both laptops must be awake with HomeControl running on the same LAN; the first laptop must remain available while its dashboard controls the second. The iPhone needs only Safari and the first dashboard’s key. No ngrok, Tailscale, additional account or internet tunnel is required. If an address changes, remove the saved laptop and add its new address/key. Removing a saved laptop only removes its connection entry; it does not uninstall that laptop or erase its usage data.

Only literal private IPv4 addresses on port 8765 are accepted. Redirects and system web proxies are refused so saved keys are sent only to the configured laptop. All hub endpoints and relayed controls require the first laptop’s existing access key. The home-network firewall rule remains limited to the local subnet on the Private profile.

## Live readings and App FPS

CPU utilization, RAM, battery and each hardware GPU's busiest engine are sampled every two seconds using Windows APIs and performance counters. NVIDIA temperature and power draw are queried independently. Unsupported CPU/GPU temperatures and power readings say **Unavailable**; ACPI thermal zones are not presented as CPU temperatures. NVIDIA power/clock capability discovery runs separately, so it cannot block the telemetry sampler.

FPS monitoring starts enabled. The bundled official [PresentMon 2.6.0 x64 console](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0) needs no separate overlay, service installation or changes to games. The executable's SHA-256 is checked before launch against `b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`. The release manifest, MIT license and third-party notices are in vendor/presentmon.

**App FPS** measures presented frames over a rolling two-second window, using the most active swap chain of the foreground process. It is not monitor refresh rate or guaranteed displayed FPS. You can pin a running process instead. A changed/exited application clears the frame history; stale readings disappear after five seconds. No frames, insufficient permissions and helper failures have separate states. A game launcher may be a different process from its game: pin the actual game's executable if necessary.

HomeControl streams CSV into bounded memory, without saving frame captures. Its dedicated `HomeControlFPS-…` trace name allows other PresentMon sessions to coexist. It terminates its own session on normal exit and replaces only its own orphaned session after an abrupt termination. The FPS switch persists; pinned process IDs do not survive an app restart. Run the elevated startup task for full ETW access.

## Internet speed slider

The slider sets **0.1–1000 Mbps**. Its far-right position is **Unlimited**; tap Apply internet limit to use the selected value, or tap Unlimited to remove it immediately. The numeric box allows 0.1 Mbps steps. The same cap applies independently to aggregate internet downloads and uploads on this laptop, across its adapters; it does not change the router or other devices. Mbps means megabits per second, so 8 Mbps is about 1 MB/s before overhead.

This uses the official signed [WinDivert 2.2.2](https://github.com/basil00/WinDivert/releases/tag/v2.2.2) x64 DLL and driver, with verified runtime checksums. The driver is loaded on demand when a limit is applied through the elevated startup task. No additional Python package or manual driver installation is needed. If Windows or security software blocks it, the app reports the error and restores unrestricted routing; it never changes security settings. Copy the entire vendor folder when updating. The LGPLv3/GPL licenses and corresponding unmodified source archive are supplied in vendor/windivert; custom builds can replace the binaries and update CHECKSUMS in network_native.py.

Only this laptop's internet TCP/UDP packets are shaped. HomeControl's port, localhost, IPv4 private/shared-address/link-local/multicast traffic and IPv6 local/multicast traffic bypass the limiter. The displayed download/upload rates count bytes delivered by the active shaper, including packet headers. They are not the Wi-Fi link rate or an ISP speed test. The limiter permits a small 10 ms burst; buffering and scheduling can lower actual speed. Inbound shaping limits delivery to applications after packets reach the laptop: TCP senders normally slow down, while excess UDP can be dropped and may still consume upstream Wi-Fi/ISP bandwidth. VPN paths and large-packet offloading can affect observed throughput.

Unlimited stops the worker and closes its filters. The worker's Windows job and parent watchdog also release them on app exit or failure. Bounded kernel queues are drained on normal Stop; abrupt termination can drop queued packets, which TCP may retransmit. A selected limit does not resume after restart or sign-in; startup always begins Unlimited. No packet captures or payloads are saved.

Authenticated GET /api/network returns state; POST /api/network accepts `{ "mbps": 4 }` or `{ "mbps": null }` for Unlimited. Live metrics include networkLimit. Runtime network-limit files are ignored by Git and excluded from packages.

`python tests/network_fixture.py` is an optional administrator acceptance check. It temporarily shapes disposable localhost transfers on its own port at 4 Mbps, then verifies unrestricted transfers after closing its handles. It does not shape the real internet or the HomeControl port.

## Laptop power

Lock acts immediately. Restart and shutdown begin a ten-second countdown with a Cancel button. At the deadline HomeControl asks Windows to close applications normally using shutdown.exe with `/t 0` and without `/f`. The countdown is kept inside HomeControl because a nonzero Windows shutdown timeout implies forced closure. Unsaved applications can prevent or delay completion. Closing HomeControl cancels a pending countdown. Sleep and wake are not offered.

## Tweakout mode

The dashboard can start a simulated glitch on the selected laptop: a fullscreen corrupted-display effect with slow dark colour changes, fake diagnostic text and a bounded synthetic buzz. It does not restart the graphics driver. Audio uses the existing Windows volume. There is no Cancel button or Escape shortcut in the laptop effect; **Cancel Tweakout & restore CPU is only on the dashboard**.

**Preview effects only** runs for 12 seconds without changing CPU settings or requesting shutdown. Full mode requires a separate confirmation naming the selected laptop. It sets the Windows maximum processor state to 1% for charger and battery, runs a 20-second countdown, then restores the previous CPU settings before requesting normal Windows shutdown with `/t 0` and no `/f`. This CPU setting is a performance request, not a guaranteed utilization/clock percentage. Unsaved applications can delay or prevent shutdown. Cancel remains available until the countdown dispatches shutdown; keep the dashboard connected to that laptop. The effect is clearly labelled as a simulation on screen.

HomeControl journals the exact pre-sequence CPU values and verifies an independent elevated **HomeControl-TweakoutRecovery-…** task before applying the cap. Cancel, helper failure, a stalled helper, a delayed resume, normal app exit or a rejected shutdown restores those values. If the app crashes, the recovery task restores them after 60 seconds and retries every minute or at sign-in. Startup also reconciles outstanding records. Failed recovery retains its record and blocks another sequence; Cancel retries restoration. The signed-in account and laptop must be awake for the recovery task to run. Keep the application folder in place until recovery finishes. The mode never resumes automatically at startup.

CPU/GPU changes, app-budget changes and other power actions are blocked during the sequence. Budget enforcement resumes afterward. Existing keys, usage history and device selections are preserved. Generated effects, audio and recovery records are excluded from source packages and GitHub. Authenticated endpoints: GET `/api/tweakout`, POST `/api/tweakout/start` with `{ "preview": true }` or `{ "confirmed": true }`, and POST `/api/tweakout/cancel` with `{}`. They support the existing selected-laptop relay.

## Selected USB and keyboard devices

Selections start empty. Choose connected peripherals, then Enable, Disable or Restart the selected group or both groups. Actions save the currently checked selections first; Save selections also keeps them for later without changing device state. Protected devices are shown with a lock and a specific reason. Combined selections are deduplicated by instance ID. Restart restarts the device; it does not uninstall/reinstall its driver. Each result is shown beside the buttons. Enable, Disable and Restart only report success after confirming the native device state; an unconfirmed disable retains its recovery record. Instance IDs must match fresh native PnP inventory. USB hubs and Bluetooth radios are selectable unless they contain storage or networking dependencies. Disable/Restart for these devices requires confirmation of the affected hub/radio in the dashboard; API clients must send `confirmed: true`. A hub action affects its attached peripherals. Bluetooth mice, controllers and audio disconnect with the radio. Host controllers, network devices and their ancestors, storage devices and their ancestors, and non-Bluetooth system devices remain protected. A Bluetooth radio and its hub are available only when Windows confirms their Bluetooth PAN networking component is disconnected; a missing/unknown network reading keeps them protected. Fresh checks before each action catch new attachments and network connections. All disk/storage devices are conservatively protected, including boot and mounted storage.

Before disabling a previously enabled device, or restarting a USB hub/Bluetooth radio, HomeControl durably journals its original enabled state and arms an independent **HomeControl-DeviceRecovery-…** scheduled task under the same elevated interactive account. If that task cannot be registered and verified, disabling is refused. Windows PnP commands do not use force or request a reboot. Only previously enabled devices with a journaled action are automatically re-enabled if disabled after 60 seconds. Parents recover before their selected children. A previously disabled device is left disabled. Failed/partial actions retain their recovery records; successful recovery requires confirming the enabled state.

The recovery task retries every minute and at sign-in, independent of the main app. HomeControl also reconciles records at startup and every five seconds, including immediately after it resumes from sleep. Disconnected peripherals remain in the journal until they reconnect and recovery succeeds. The account must be signed in and the laptop awake for recovery to run. Startup removal preserves the recovery task and journal; leave the app folder in place until recovery has finished. Test actions only with selected spare peripherals.

## iPhone Home Screen web app

In Safari, open the laptop address printed by Connection-Info.cmd. Tap **Share → Add to Home Screen**, enable **Open as Web App** if shown, then tap **Add**. Launch HomeControl from its Home Screen icon. The dashboard includes a custom Apple touch icon, a standalone web app manifest, safe-area spacing and touch controls. Install help hides when launched as a standalone app. See [Apple's instructions](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios).

Enter the access key inside the Home Screen app. Safari and the installed app can have separate browser storage. **Remember access key on this device** is optional and off by default; when selected, the validated key is kept in local storage for future launches. Disconnect removes both remembered and session keys. Only use the remember option on your own phone. The manifest and icons never contain the key. If browser storage is blocked, manual sign-in still works.

The app refreshes live data when you return to it. It needs the laptop awake and reachable through home Wi-Fi. It does not install an App Store app or add cloud hosting. No offline service worker is registered for the home-network HTTP address; live laptop control still requires a connection. Keep the laptop's IP stable in your router, or replace the Home Screen shortcut if its address changes.

## CPU slider: 1–100%

Sets the Windows maximum processor performance state for charger and battery. Values below 10% are accepted. This is not an exact speed, FPS, or utilization ceiling; Windows and hardware decide the minimum effective CPU clock. Restore CPU settings returns to the values saved before your first manual change.

## GPU power and clock modes

Power mode caps NVIDIA wattage as a percentage of the GPU's default power limit. Clock mode requests an upper graphics-clock limit as a percentage of its reported maximum clock. The driver sets the lowest allowed value; neither mode can promise a 1% GPU cap. Intel UHD is not capped.

The app searches both System32 and NVIDIA's NVSMI folder for nvidia-smi. GPU diagnostics reports driver power/clock information and whether HomeControl is elevated. Use it if writes fail, and send the exact output/error for troubleshooting. A reported range does not guarantee writable controls: RTX 3050 Laptop firmware or drivers can reject either method. The app reports failures rather than pretending a cap worked.

Restore GPU settings recovers the saved watts in power mode. In clock mode it resets the GPU to automatic clock management, which also clears any previous externally configured graphics clock lock. Restore before switching modes. Existing old-version power backups remain compatible. Manual GPU caps are not automatically reapplied after reboot; use the dashboard to apply again if the driver resets them.

## Daily app budgets

Use an app that already appears in recorded app time. Choose daily active minutes, CPU percentage after the budget, and either **only this app** or **whole laptop**. Saved budgets survive restarts. Usage is foreground time, excluding idle time after 60 seconds without keyboard/mouse input; controller-only games can appear idle. Budgets reset at midnight using the laptop's local date. Enforcement checks every five seconds while HomeControl runs.

App mode caps the shared CPU budget of matching executable-name processes with Windows job objects. Matching apps restarted that day are capped again. Some games, protected processes, or existing job restrictions can reject assignment; the dashboard shows errors and the number of processes actually capped. Windows system executables and HomeControl itself are excluded. Processes newly spawned after assignment can inherit the job until reset. App caps clear when you remove/raise the budget or the day changes; they do not cap GPU utilization.

Laptop mode temporarily lowers charger/battery CPU settings after the selected app's daily budget is reached, until midnight or until you remove/raise that expired budget. Multiple expired laptop rules use the lowest cap and never increase the pre-timer CPU settings. The prior settings are saved separately and restored when no laptop timer cap applies. The manual CPU slider is blocked while a laptop timer cap is active. Remove expired laptop budgets before restoring/changing manual CPU settings, otherwise enforcement will reapply the timer. Restore.cmd restores saved timer, manual CPU, and GPU settings locally.

## Remote PowerShell

Run Enable-Terminal.cmd locally on the laptop. The dashboard's Remote PowerShell panel becomes available on the next refresh; no restart is required. Disable-Terminal.cmd turns it off again. These scripts use the startup task's recorded data location.

Enter a command and optional laptop working-directory path. Each request runs a fresh, noninteractive Windows PowerShell process: directory changes, variables and sessions do not carry to the next command. Output is limited to 64 KB and execution to 30 seconds. Terminal processes are placed in a kill-on-close Windows job; children are stopped when the command completes or times out, so it is unsuitable for launching persistent background services. Only one terminal command runs at a time.

Remote commands run with HomeControl's privileges, normally administrator when installed at startup. Anyone with the access key can run commands when terminal mode is enabled. The local dashboard uses HTTP, so traffic and the key are unencrypted; enable terminal only on your trusted home network. No terminal command history is saved by HomeControl.

## Data and development

Default data: %LOCALAPPDATA%\HomeControl. Startup records the actual location in data-location.txt so the server and connection helper use the same key across accounts. Do not copy that file to another laptop. HOMECONTROL_DATA can override the location for isolated tests. App budgets live in app-limits.json; usage in usage.sqlite. No telemetry is uploaded.

Clone this repository with GitHub Desktop to edit on your PC. Edit server.py for routes/hardware, app_limits.py for budgets, remote_terminal.py for commands, and dashboard.html for the phone interface. Commit and push source changes, then update the laptop using the steps above. Keys, usage, logs, generated locations, and runtime settings are excluded by .gitignore.

Run `python -m unittest discover -s tests -v` on Windows. Tests use temporary data and mock powercfg/nvidia-smi writes, power actions and device mutations. They cover FPS windows/swap chains/target changes/staleness/permissions/helper failure, cancellation, protected devices, deduplication, task-arm failure and disconnected recovery after app termination. The native CPU test caps only a disposable child process, and the terminal test executes a read-only output command.

Run `node tests/test_webapp.js` for browser sign-in checks: optional remembered keys, relaunch, disconnect, invalid keys, automatic sign-in links, blocked storage and late requests after logout. The same Node checks cover saving device selections before an action, aborting on save failure, slider Mbps mapping and Unlimited. Public web app assets are also covered by the Python server tests.

Hardware acceptance: compare App FPS to an actual game's built-in counter on Iris Xe and RTX 3050, test coexistence with another PresentMon session, and use only selected spare peripherals for real disable/restart tests. The Windows test laptop has Iris Xe; RTX 3050 and spare-peripheral acceptance need those devices. Simulated tests do not substitute for that hardware acceptance.

`python tests/render_fixture.py` opens a small Direct3D 11 test window for eight seconds and compares its 60 FPS reference against the dashboard. It temporarily pins itself, then restores automatic tracking. This optional fixture expects the local installed server and data-location.txt. See VALIDATION.md for completed checks and remaining hardware acceptance.

New authenticated endpoints: GET /api/metrics, /api/laptops, /api/fps, /api/devices and /api/power/action; POST /api/laptops, /api/laptops/remove, /api/fps/settings, /api/devices/refresh, /api/devices/selections, /api/devices/action, /api/power/action and /api/power/cancel. All require the existing X-Access-Key header. Runtime settings, saved laptop keys and recovery records are gitignored and omitted from the update ZIP.

References: [Windows CPU-rate job controls](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information), [NVIDIA nvidia-smi controls](https://docs.nvidia.com/deploy/nvidia-smi/index.html).
