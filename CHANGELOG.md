# Changelog

## 0.15.0-beta1

- Add a generic Custom IMAP account type alongside the existing Yahoo preset.
- Add host, port, SSL/TLS, display name and independent login-name settings.
- Keep Custom IMAP passwords only in the system Secret Service keyring.
- Reuse the existing folder selection, OTP, popup, pending, reconnect,
  suspend/resume and UIDVALIDITY safety pipeline for Custom IMAP accounts.
- Make account removal clear the selected Custom IMAP configuration,
  credential and local state without changing server mail.

## 0.14.8-beta1

- Connect the About tab to the published MailFlag website, GitHub repository,
  Privacy Policy and GPLv3 License.

## 0.14.7-beta1

- Add **About MailFlag** to the tray menu between Settings and Quit.
- Open Settings directly on the About tab, including when Settings is already
  open.
- Add placeholder Website, GitHub, Privacy Policy and GPLv3 License links to
  the About tab; publication URLs will be connected later.

## 0.14.6-beta1

- Correctly detect a fresh installation after `apt remove`, even when dpkg
  retains the previous package version in `config-files` state.
- Add an X11 display fallback for opening Settings from graphical installers.
- Give the Cinnamon application launcher an explicit installed icon path so it
  no longer falls back to a generic settings icon.

## 0.14.5-beta1

- After a fresh Debian installation, schedule Settings to open in each active
  graphical user session so installation has an immediate visible result.
- Do not open Settings automatically during package upgrades.
- If no supported desktop session is active, installation still succeeds and
  the normal application launcher and next-login autostart remain available.

## 0.14.4-beta1

- Stop background monitoring and Settings cleanly during Debian package removal.
- Add the headless `mailflag --shutdown` lifecycle command for all active users.
- Add a narrowly scoped `prerm` fallback using TERM, then KILL only for stuck
  `python -m mailflag` processes; user configuration and credentials remain.

All notable changes to MailFlag will be documented in this file.

## 0.14.3-beta1

- Added a Settings item to the tray menu immediately before Quit MailFlag.
- Made account removal stop only the selected account worker while other
  accounts continue monitoring.
- Made Remove clear the selected account's keyring credential, configuration,
  monitored folders, checkpoints and pending state with error reporting and
  rollback protection.
- Added a safe no-accounts state and regression coverage for removal failures.

## 0.14.2-beta1

- Added Yahoo Mail monitoring over IMAP with multi-account support.
- Added per-account monitored folders for messages delivered by server-side filters.
- Added OTP and verification-code detection with one-click clipboard copy.
- Added ordinary-mail popups with Open, Delete, Spam, Ignore, and Mark as Read actions.
- Added a persistent pending indicator and per-account pending handling.
- Added recovery after reconnect, network interruption, sleep/resume, and application restart.
- Added graphical settings for accounts, monitored folders, notifications, sound, and startup.
- Added local keyring credential storage and safe account removal.
- Improved human-readable HTML email previews and reduced OTP false positives from technical markup and non-OTP numbers.
- Added Debian packaging, application-menu integration, autostart, and Cinnamon window-icon matching.
