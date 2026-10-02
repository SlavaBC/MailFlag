# MailFlag 0.13.0-beta1 verification report

This is a local beta build. No public release or Git tag was created.

## Status

| Area | Status | Evidence / remaining manual check |
|---|---|---|
| Baseline and checkpoint | DONE | Stable 0.12.6 passed 484 tests; checkpoint commit `9b2a705`. |
| Version consistency | DONE | Application `0.13.0-beta1`; Debian `0.13.0~beta1`; source, menu and package metadata agree. |
| Icons | DONE | Existing selected MailFlag artwork is packaged at 48, 64, 128 and 256 px; dimensions verified. |
| Application menu | DONE | Freedesktop launcher has an absolute executable, `Icon=mailflag` and `Terminal=false`; `desktop-file-validate` passes. |
| Autostart | DONE | System freedesktop entry is installed at `/etc/xdg/autostart/mailflag.desktop`. |
| Single instance | DONE | Per-user nonblocking lock at `~/.config/mailflag/instance.lock`; regression test verifies a second process is rejected. |
| Debian package | DONE | Valid amd64 package built and inspected; extracted runtime reports the expected version. |
| Dependencies | DONE | Apt dependencies are declared; `imap-tools 1.15.0` is bundled under `/opt/mailflag/vendor`. |
| Package safety | DONE | Maintainer scripts only refresh desktop/icon caches and never connect to IMAP or touch user state/keyring. |
| Upgrade/uninstall preservation | DONE | Package owns no files under `$HOME`; migration test preserves config/state; removal scripts leave home and keyring untouched. |
| Per-account folder configuration | DONE | IMAP LIST based `mailflag --configure-folders`; only existing selectable folders; INBOX mandatory; action folders excluded. |
| Multi-folder monitoring | DONE | One connection per account; INBOX IDLE/safety refresh; extra folders polled sequentially every 30 seconds. |
| Per-folder state/actions | DONE | State v3 stores folder UIDVALIDITY, last UID, pending and references; exact source folder is used for mail actions. |
| Reconnect/startup/suspend | DONE | Startup, long outage and resume recover all configured folders into pending; short reconnect stays live. |
| Duplicate suppression | DONE | Account-wide bounded Message-ID history suppresses cross-folder repeat notification; UID identity remains authoritative for actions. |
| Automated regressions | DONE | 503 tests pass; OTP 200/200 (TP 100, TN 100, FP 0, FN 0). |
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

1. Install: `sudo apt install ./mailflag_0.13.0~beta1_amd64.deb`.
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
