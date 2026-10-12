# MailFlag 0.14.3-beta1 GUI verification report

This is a local beta build. No public release or Git tag was created.

## Status

| Area | Status | Evidence / remaining manual check |
|---|---|---|
| Baseline and checkpoint | DONE | Pre-GUI stable checkpoint is `a9e5e7337b8045241279f5f7b8af070045a3399f`; 515 tests passed. |
| Version consistency | DONE | Application `0.14.3-beta1`; Debian `0.14.3~beta1`; source, About and package metadata agree. |
| Icons | DONE | Existing selected MailFlag artwork is packaged at 48, 64, 128 and 256 px; dimensions verified. |
| Application menu | DONE | Menu runs `--settings`; absolute executable, selected icon and `Terminal=false`. |
| Settings / first run | DONE | GTK Accounts, Folders, Notifications, Startup and About plus Welcome/account/folder/finish flow. |
| First run and autostart | DONE | Freedesktop autostart runs `--startup`: a clean profile opens Settings; configured profiles start only the background monitor. |
| Window icon | DONE | Settings and all transient dialogs inherit the icon; GTK program name, window `WM_CLASS` and desktop `StartupWMClass` consistently use `mailflag`. |
| Folder chooser | DONE | Long folder lists scroll inside a bounded dialog; action buttons remain outside the scrolling area. |
| Process lifecycle | DONE | Separate background/settings locks and a `0600` Unix control socket prevent duplicate monitoring; the tray Settings item opens one protected Settings window without stopping monitoring. |
| Account management | DONE | Yahoo add/test/edit/remove; confirmed removal stops only the selected worker, clears only that account's credential/config/state/pending data and does not touch server mail. |
| Custom IMAP | PARTIAL | Visible as a future provider adapter but intentionally disabled because the current verified core is Yahoo-only. |
| Notification settings | DONE | Popup/sound switches and fixed 10/20/30/45/60 durations; OTP capped at 30 seconds. |
| CLI discoverability | DONE | `--help`, confirmed `--remove-account`, and packaged `man mailflag`. |
| Debian package | DONE | Valid amd64 package built and inspected; extracted runtime reports the expected version. |
| Dependencies | DONE | Apt dependencies are declared; `imap-tools 1.15.0` is bundled under `/opt/mailflag/vendor`. |
| Package safety | DONE | Maintainer scripts only refresh desktop/icon caches and never connect to IMAP or touch user state/keyring. |
| Upgrade/uninstall preservation | DONE | Package owns no files under `$HOME`; migration test preserves config/state; removal scripts leave home and keyring untouched. |
| Per-account folder configuration | DONE | IMAP LIST based `mailflag --configure-folders`; only existing selectable folders; INBOX mandatory; action folders excluded. |
| Multi-folder monitoring | DONE | One connection per account; INBOX IDLE/safety refresh; extra folders polled sequentially every 30 seconds. |
| Per-folder state/actions | DONE | State v3 stores folder UIDVALIDITY, last UID, pending and references; exact source folder is used for mail actions. |
| Reconnect/startup/suspend | DONE | Startup, long outage and resume recover all configured folders into pending; short reconnect stays live. |
| Duplicate suppression | DONE | Account-wide bounded Message-ID history suppresses cross-folder repeat notification; UID identity remains authoritative for actions. |
| Automated regressions | DONE | 530 tests pass (one Unix-socket runtime test skipped only because the build sandbox blocks AF_UNIX); OTP 200/200 remains green. |
| Clean real-machine install and Yahoo E2E | PARTIAL | Package-root extraction and offline runtime are verified. Installing into the active desktop, login/reboot, keyring and real Yahoo folders require the user's machine/session and credentials. |
| Linux Mint visual checks at all desktop scales | PARTIAL | Exact icon files and metadata are verified; final Cinnamon rendering must be observed after installation. |
| Public publication | BLOCKED BY SCOPE | Explicitly excluded: no GitHub Release, upload or public tag. |

## Architecture and data

- One MailFlag process serves all accounts; one IMAP connection is created per account.
- INBOX remains near-real-time via IMAP IDLE plus the existing ten-second read-only refresh.
- Additional folders use the same connection and a 30-second polling interval, then INBOX is selected again before IDLE.
- Folder discovery preserves server names, nested paths and decoded names supplied by `imap-tools`.
- Trash/Junk/Bulk/Sent/Drafts and nonselectable folders are kept separate from monitored folders.
- `~/.config/mailflag/config.ini` stores each account's `monitored_folders`; credentials remain in Secret Service.
- `~/.config/mailflag/state.json` version 3 stores `account -> folders -> folder state`. Version 2 and legacy state migrate automatically without replaying mail.
- Message-ID is used only as an account-wide notification dedup hint. Delete, Spam, Mark as Read and OTP Trash validate source folder, UIDVALIDITY and UID.
- A missing or renamed extra folder reports an error and does not stop the account's other folders.

## Package dependencies

Required apt packages: `python3 (>= 3.10)`, `python3-gi`, `python3-cairo`,
`gir1.2-gtk-3.0`, `gir1.2-gdkpixbuf-2.0`,
`gir1.2-ayatanaappindicator3-0.1`, `libsecret-tools`, `xdg-utils`.

Recommended: `libnotify-bin`, `pulseaudio-utils`.

Python dependency `imap-tools 1.15.0` is pinned and bundled; no network or pip
operation is needed during package installation.

## User workflow

1. Install: `sudo apt install ./mailflag_0.14.3~beta1_amd64.deb`.
2. If upgrading from the old local installer, run once: `mailflag-migrate-local`.
3. Add an account: `mailflag --add-account`.
4. Select folders: `mailflag --configure-folders` (or append the exact account argument), then restart MailFlag.
5. Verify autostart by logging out and back in. Only one indicator should appear; a second manual start should say the app is already running.
6. Update with `sudo apt install ./new-mailflag.deb`; config, state, pending and keyring credentials remain outside the package.
7. Remove with `sudo apt remove mailflag`; user data and keyring credentials are retained.

## Manual beta acceptance

After installing on the desktop, verify menu icon/launch, login and reboot
autostart, two-account monitoring, delivery into one real extra Yahoo folder,
ordinary and OTP actions from that folder, short reconnect, long outage and
suspend recovery. These checks deliberately require the actual session and mail
account and were not simulated as proof of real Yahoo behavior.
