# HomeControl — Windows laptop + iPhone

Windows background app with an iPhone browser dashboard on your home network. Includes separate CPU and supported NVIDIA GPU power controls, foreground app/game time totals, automatic sign-in links, and automatic launch at Windows sign-in. Requires Python 3 on the target Windows laptop; no third-party Python packages are required.

## Making updates from your PC

Clone this repository using GitHub Desktop, or use `git clone` with its GitHub URL. Edit `server.py` for tracking and hardware controls, `dashboard.html` for the phone dashboard, and `Startup.ps1` for startup installation. Commit and push your changes from your PC.

On the controlled laptop, stop HomeControl with Disable-Startup.cmd before pulling updates into the same folder. Then rerun Install-Startup.cmd as administrator. This keeps your local app time and saved restoration settings. Do not commit access keys, usage databases, logs, or data-location.txt; the included .gitignore excludes them. GitHub stores the source code; the dashboard still runs on the laptop over home Wi-Fi.

Access key update: close any manually running Start.cmd window, replace application files with this release, then rerun Install-Startup.cmd as administrator. Run Connection-Info.cmd again. It verifies the key against the live server and prints an automatic sign-in link; keep that link private. Startup now records its data location so the connection helper reads the same key across accounts. Do not copy the generated data-location.txt to another laptop. Existing app time and saved power settings are preserved.

1. Install Python 3 for Windows if needed: https://www.python.org/downloads/windows/ . Enable its launcher or add Python to PATH.
2. For automatic startup, use the startup instructions below. For a manual run, double-click Start.cmd and keep its window open.
3. On your home Wi-Fi, open the displayed http://LAPTOP-IP:8765 address in iPhone Safari. Enter the access key printed in the laptop window. You can use Share → Add to Home Screen.
4. If Windows asks about firewall access, allow **Private networks** only. Your Windows Wi-Fi network profile must be Private. Do not forward this port on your router. Guest Wi-Fi/client isolation can prevent a connection.
5. Move the slider and tap Apply limit. Both charger and battery maximum processor state are changed for your current power plan. If Windows denies changes, close the program and run Start.cmd as administrator.
6. Tap Restore original settings to recover the values saved before your first change. You can also run Restore.cmd locally, including after restarting Windows. This may need administrator privileges. Power changes persist after closing the app; recovery data is preserved until a successful restore. Restore selects the saved original power plan.

The CPU cap adjusts Windows maximum processor state, not an exact speed or FPS percentage. Hardware and Windows power policies may limit its effect. It does not cap network speed or individual apps. Check a running workload on your own laptop to confirm its effect.

## Separate GPU slider

The NVIDIA GPU slider queries the target laptop's driver for adjustable power limits. If the driver exposes a valid range, the slider requests a wattage cap as a percentage of its default power limit, bounded by the GPU's minimum. For example, a 60 W default with a 30 W minimum permits 50–100%. This is a power cap, not a utilization ceiling or exact FPS/speed percentage. The driver can still reject writes even when readable limits are exposed; the dashboard displays the error. RTX 3050 Laptop support depends on the actual laptop firmware and driver and has not been verified on your other laptop.

Intel UHD graphics is not controlled by this slider. If NVIDIA limits are unavailable, the GPU slider is disabled with an explanation. No unsupported GPU cap is simulated. CPU control and app tracking still work. GPU restoration is separate on the dashboard; Restore.cmd restores both saved CPU and GPU settings. NVIDIA power changes may require running Start.cmd as administrator. Original GPU watts are stored in %LOCALAPPDATA%\HomeControl\original-gpu.json.

Copy the entire HomeControl folder to the OTHER laptop and run Start.cmd there. Python and NVIDIA drivers must be installed on that laptop. Nothing needs to run on the computer used to download or copy this folder. On the iPhone, use the address printed by the other laptop.

App/game totals use executable names and foreground focus, excluding idle periods after 60 seconds without keyboard/mouse input. Controller-only games may be counted as idle; browser sites are grouped under the browser. Background activity is not counted. Samples are taken every two seconds; focus changes and sleep gaps are excluded. Tracking is not retroactive and runs only while Start.cmd stays open. Last 7 days includes today, using the laptop's local date.

All usage and the access key stay in %LOCALAPPDATA%\HomeControl. No cloud account or internet hosting is used. This server listens on the laptop's network interfaces; use it only on your trusted home network. HTTP does not encrypt the key or traffic. Treat the printed key as a password. To rotate it, stop the program, delete key.txt in that data folder, and restart.

If the laptop sleeps, loses Wi-Fi, or the program closes, phone control disconnects. Windows may require permission to read some foreground processes; these intervals are excluded.

## Automatic startup

1. Extract this folder to a permanent location on the other laptop. Install Python 3 there.
2. Close any manually started HomeControl window. Right-click **Install-Startup.cmd → Run as administrator** using your usual Windows administrator account.
3. This creates an elevated interactive scheduled task, starts it now, and runs it quietly at each sign-in. It stays running on battery. The elevated task allows supported power-setting changes without a prompt each time.
4. Run **Connection-Info.cmd** to see the iPhone address and access key. Set your home Wi-Fi network profile to Private; the installer allows port 8765 only on Private networks from the local subnet.
5. Keep the folder in place; rerun the installer after moving it. Logs are in %LOCALAPPDATA%\HomeControl\background.log. Task Scheduler lists the task as HomeControl.
6. To stop it and disable automatic startup, right-click **Disable-Startup.cmd → Run as administrator**. Usage and restoration files remain. This does not restore power settings; use the dashboard restore buttons or Restore.cmd first.

Startup runs at Windows sign-in, not before login, because foreground app tracking needs your desktop session. No automatic Windows login is configured. Elevating with another account's credentials installs for that account instead, so install under your own administrator account. Installation must be tested on the target laptop. With startup enabled, app tracking continues in the background without keeping Start.cmd open.
