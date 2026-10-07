# HomeControl 3.7: installation and updates

HomeControl runs on each Windows PC you want to control. Your iPhone or another computer opens its dashboard in a browser. This release works on trusted home Wi-Fi only; no cloud account, tunnel or phone app is needed.

## What you need

- A Windows 10/11 PC with an Intel or AMD x64 processor, a signed-in administrator account, and the PC awake. ARM Windows is not tested or packaged.
- **64-bit Python 3.10 or newer with Tcl/Tk**, the Python launcher and `pythonw.exe`. Get the regular **Windows installer (64-bit)** from [Python's official Windows downloads](https://www.python.org/downloads/windows/). Use the regular installer rather than the embeddable package. Keep Tcl/Tk and the launcher selected, and select **Add Python to PATH** when offered. No pip packages are required. [Python's Windows installation documentation](https://docs.python.org/3/using/windows.html).
- The release ZIP from this repository's [Releases page](https://github.com/DaBeaklyBird/HomeControl/releases), or **Code → Download ZIP** for the current source. A private repository requires GitHub access to download; running HomeControl requires no GitHub sign-in.
- The controlled PC and browser device on the same home network. Guest Wi-Fi that isolates devices will not work.

## First installation

1. Download the ZIP on the **Windows computer being controlled**. Right-click it and choose **Extract All**.
2. Put the extracted **HomeControl** folder in a permanent local location, such as `C:\HomeControl`. The correct folder contains `server.py`, `Install-Startup.cmd` and `vendor`. A GitHub source ZIP may call its folder `HomeControl-main`; that works too. Do not run files from inside the ZIP. Avoid cloud-only folders, junctions and symlinks.
3. Make the home network **Private** in Windows Settings → Network & internet → your connection's properties → Network profile. Use this only for your trusted home network.
4. In the permanent app folder, right-click **Install-Startup.cmd → Run as administrator**. Use the Windows account that will normally sign in to this PC. Accept Windows' elevation prompt. The script installs the **HomeControl** scheduled task, starts it immediately, and permits port 8765 only on Private networks from the local subnet.
5. Run **Connection-Info.cmd** in that same folder. It checks the key against the running app and prints the PC's address, access key, and automatic sign-in link. Do not post those details publicly.
6. On your iPhone, join the same home Wi-Fi, open Safari, and enter the printed address, such as `http://192.168.1.50:8765/`. Enter the **case-sensitive key from that PC**, or open its automatic sign-in link. The example IP is not your PC's address.
7. To make it an iPhone Home Screen app, open the dashboard in Safari → Share → **Add to Home Screen** → Add. Optional **Remember key on this device** keeps the key in this browser. Close and reopen the Home Screen app after updates if it shows the old interface.

Automatic startup is **at Windows sign-in**, including on battery. It does not wake a sleeping PC and does not run before someone signs in. Keep the installed folder in place. Do not run `Start.cmd` alongside the startup copy; `Start.cmd` is the manual console alternative.

## Update an existing installation automatically

1. Download the new ZIP on the PC being updated and **Extract All into a separate temporary folder outside the old app folder**. Do not overwrite the old folder by hand first.
2. Open the new extracted folder containing **Update.cmd**. Right-click **Update.cmd → Run as administrator**, using the same Windows account that installed HomeControl.
3. The updater finds the old folder from its startup task. If the task is missing, paste the full path of the **old folder containing server.py** when asked. It uses the existing Python installation, or Python on PATH if there was no task.
4. Wait for **“updated and running”** and **“Automatic startup at Windows sign-in is ON.”** The updater verifies package checksums; cancels pending shutdown/Tweakout/lag; sets internet limiting to Unlimited; checks CPU recovery; stops the old copy; saves the app files it will replace, runtime data and startup configuration; copies the new files into the old folder; installs/enables startup; starts HomeControl; and checks that the correct version accepts the existing key.
5. Refresh the phone dashboard. Your address and access key normally remain the same. Run **Connection-Info.cmd in the old permanent folder** to check them. Update each controlled PC separately, then remove the temporary extracted update folder when finished.

There is no need to run Disable-Startup.cmd or reinstall startup manually for a successful automated update. Keys, usage history, saved computers, app budgets, terminal preference and device selections are preserved. Lag/Tweakout do not start automatically. Device and CPU recovery records are never erased by the updater. Pending CPU restoration blocks replacement until it finishes. Device journals are locked during replacement, disconnected records stay intact, and independent recovery tasks continue afterward from the same permanent app folder. Permanent CPU/GPU caps are left in place; daily app budgets can resume enforcement after restart.

The backup path is printed under `%LOCALAPPDATA%\HomeControlBackups`, for example `HomeControl-20261007-120000-ab12cd`. It contains `app` (replaced original files), `runtime` (data snapshot), and `startup-task.xml` when a task existed. The folder is restricted to your account and SYSTEM because it contains credentials. Keep it private. A failed file replacement or startup check automatically restores original app files and the previous startup task. Runtime data stays in its existing location and is not overwritten during rollback.

Checksums detect incomplete or altered files; they are not a digital signature. Download from this repository or the provided release ZIP. The updater does not download code, check for future releases or implement OTA updates.

Advanced commands from the new extracted folder:

```powershell
# Validate files without changing the installation (no administrator required):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Update.ps1 -ValidateOnly

# Update a specified old folder from an administrator PowerShell:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Update.ps1 -InstallFolder "C:\HomeControl"
```

## Add another desktop or laptop

Install/update HomeControl separately on each Windows PC. Run Connection-Info.cmd on the second PC. In the first dashboard, open **Computers → Add another computer**, enter a name, the second PC's private IPv4 address on port 8765, and **its own access key**. Select it in **Control computer**. Both PCs must be awake, signed in and on the same home network. The PC hosting the dashboard relays controls to the selected one. No account or tunnel is needed on either device.

When a PC's IP changes, remove its saved entry and add its new address/key. You can reserve its IP in your router. Do not copy `data-location.txt`, keys or usage databases from one PC to another.

## Using the controls

- **CPU:** sets Windows maximum processor state for charger/battery from 1–100%. This is a performance request, not an exact percentage of CPU utilization. Restore uses saved original settings.
- **GPU:** uses supported NVIDIA power/clock controls. Some laptop GPUs reject these controls; Intel graphics cannot be capped this way. Unsupported controls report unavailable. The competing GPU-workload mode was removed.
- **Usage/budgets:** records the foreground app's time and lets you set daily budgets with app-only or whole-PC slowdown. An app budget runs in a Windows job when Windows permits it.
- **Live stats/FPS:** starts automatic App FPS tracking with the bundled verified PresentMon. Pin a running app if needed; missing readings say unavailable. FPS is presented frames, not guaranteed displayed frames or monitor refresh rate.
- **Launch apps:** chooses installed Start-menu apps and available desktop/game shortcuts on the selected PC. Launching may focus an existing window.
- **Remote keyboard:** unlock the PC and click the application to focus it first. Type in the dashboard and tap Send text, or use its special-key buttons. It sends into the focused Windows application; this is not screen sharing or a mouse. Secure prompts and the lock screen are not controlled.
- **Internet limit:** Mbps per direction, or move all the way to Unlimited. Uses the bundled WinDivert driver; security software can block it and HomeControl reports the error. No router changes are made.
- **Devices:** select USB/keyboard peripherals, then Enable/Disable/Restart. Protected network/storage/controller dependencies remain locked. Disable has independent recovery; a hub action can disconnect attached peripherals. Start by testing a spare peripheral.
- **Power:** Lock, or cancellable Restart/Shut down without forcing unsaved apps closed.
- **Remote PowerShell:** disabled initially. Run Enable-Terminal.cmd locally to allow commands, or Disable-Terminal.cmd to turn it off. Commands run with HomeControl's privileges, normally administrator, with a 30-second deadline.
- **Tweakout/lag:** reversible CPU effects and simulated visuals/audio. Full Tweakout has two phone confirmations and a saved-work checkbox before normal shutdown. Cancel is on the dashboard. Preview changes no CPU settings and does not shut down. No critical Windows-service kill or automatic Windows Update installation is included.

Anyone with the access key can operate these controls. HomeControl uses unencrypted HTTP on your trusted LAN; do not expose port 8765 publicly or forward it on the router. See [README.md](README.md) for API details and hardware limitations.

## Troubleshooting and recovery

| Problem | What to do |
| --- | --- |
| Python missing / Tcl/Tk missing | Repair the regular 64-bit Python installation, including Tcl/Tk and launcher. Reopen the installer/updater. |
| Updater says checksum failed | Extract a fresh ZIP. For your own source edits, run `python package.py` to regenerate the manifest, then update from that built ZIP. |
| CPU recovery pending / device recovery busy | Cancel Tweakout/lag on the dashboard and wait for CPU recovery. Keep the PC awake and old folder in place. For busy device recovery, retry shortly. Disconnected device records are preserved during updates. Do not delete recovery records. |
| Port 8765 occupied | Close any old manually opened Start.cmd console. The updater stops only this installation's identified Python server; it refuses to kill unrelated apps. |
| App offline / invalid key | Run Connection-Info.cmd in the permanent installed folder. If needed, rerun Install-Startup.cmd as administrator in that folder. Use the newly verified address/key. |
| Phone cannot connect | Check the PC is awake, signed in and on Private home Wi-Fi; phone on the same LAN, no isolated guest Wi-Fi; address matches Connection-Info.cmd. |
| Old interface on iPhone | Refresh Safari. Close/reopen the Home Screen app. Disconnect/reconnect if necessary. |
| Startup says access denied | Use Run as administrator with the same account that owns the old startup task. Do not use a different administrator account. |
| Startup check fails | Read `%LOCALAPPDATA%\HomeControl\background.log`, or the folder listed in installed `data-location.txt`. The updater prints its rollback result and backup path. |

For manual rollback after an automatic rollback failure: close HomeControl and stop its task; copy `backup\app` files back over the **same permanent folder**; import `startup-task.xml` through Task Scheduler, or run the restored Install-Startup.cmd as administrator. Do not replace runtime data unless you specifically need its older snapshot. Keep outstanding device recovery tasks and records. Check Connection-Info.cmd afterward.

To stop/uninstall startup, run **Disable-Startup.cmd as administrator**. It preserves usage and pending recovery. Restore CPU/GPU caps on the dashboard before stopping if desired. Wait for outstanding recovery before moving/deleting the app folder.
