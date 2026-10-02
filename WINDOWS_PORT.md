# Future Windows port

MailFlag 0.12.4 remains an architectural preparation release, not a Windows build.
The portable domain code lives in `mailflag/core`, provider data in
`mailflag/providers`, and operating-system operations behind
`mailflag/platform/base.py`.

## What a Windows implementation must provide

1. Implement `WindowsPlatform` in `mailflag/platform/windows.py`:
   - Windows Credential Manager storage compatible with `CredentialStore`;
   - per-user autostart enable/disable/status;
   - reliable suspend/resume timing or Windows power events;
   - Clipboard API;
   - notification sound playback;
   - default browser and mail-client opening;
   - native notifications;
   - `%APPDATA%`/`%LOCALAPPDATA%` config, state and cache paths.
2. Choose a Windows UI. The current UI remains GTK 3 and Linux-only. It may be
   ported with GTK or replaced by a Windows/Qt UI that calls the same Core.
3. Package Python, `imap-tools`, assets and the chosen UI toolkit; add a
   single-instance mechanism equivalent to the current `fcntl` lock.
4. Exercise Core tests on Windows before adding UI tests:

   ```text
   python -m unittest discover -s tests -p test_core.py -v
   ```

5. Add provider/account setup UI without storing App Passwords in config files.

## Linux-only pieces intentionally remaining

- GTK 3 and Ayatana AppIndicator UI in `mailflag/app.py`;
- the Linux implementation in `mailflag/platform/linux.py` (`secret-tool`,
  XDG/`gtk-launch`, `notify-send`, PulseAudio/PipeWire/ALSA players, `.desktop`);
- the shell installer and `.desktop` packaging;
- the `fcntl` single-instance lock in `mailflag/__main__.py`.

These pieces no longer define the Core contracts. A Windows port should replace
the platform implementation, UI/packaging and single-instance launcher while
reusing account parsing, models, state codec, OTP classification, UID rules,
delivery classification, connection status, reconnect policy and exact IMAP
actions.

## Compatibility contract

Linux continues to read `~/.config/mailflag/config.ini` and `state.json` in the
existing format, and existing Secret Service entries remain under
`service=mailflag, account=<email>`. No credential migration is needed.
