# Release history

## 3.7 - 2026-10-07

- Added the dashboard remote keyboard: text and special-key buttons on the selected unlocked PC.
- Added a local ZIP updater with package checksums, private backups, preservation of keys/settings/history, startup repair/enabling, immediate restart and authenticated version checks.
- Added rollback for replaced files and the previous scheduled task when copying or startup fails. Blocks updates during outstanding CPU restoration and locks device journals during atomic file replacement, preserving disconnected device recovery records.
- Preserved custom runtime locations when installing/enabling startup.
- Added a second Tweakout confirmation and saved-work acknowledgment. Removed HomeControl text from the effects window.
- Added a bounded retry for transient Windows file locks when replacing JSON control files.
- Added complete installation, update, multi-computer, troubleshooting and recovery instructions.
- OTA updates are deferred. No critical Windows-service termination or automatic Windows Update installation is included.

## 3.6

- Reversible gradual CPU slowdown, configurable floor and hold time, with independent recovery.
- Reworked simulated fault dialogs, crash-screen effects and local error audio with explicit waveform-output fallback.
- App/game launcher, multi-computer controls, Home Screen support and home-network access.
