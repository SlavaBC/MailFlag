# MailFlag architecture

- `mailflag/core`: provider- and desktop-independent account parsing, message
  identities, OTP classification, JSON state codec, UID/delivery policy,
  reconnect/status models, and exact IMAP actions.
- `mailflag/providers`: provider profiles. Yahoo owns its host, Inbox, webmail
  URL and Spam folder here.
- `mailflag/platform`: OS service contracts and the current Linux backend.
- `mailflag/app.py`: Linux GTK presentation and composition root. It converts
  Core events into popup, pending-indicator and tray behavior.
- One monitor worker and one IMAP connection are created per account. INBOX
  remains selected for IDLE; configured extra folders are checked sequentially
  every 30 seconds and INBOX is reselected before the next IDLE cycle.
- `state.json` version 3 stores checkpoints below account and folder. Message-ID
  deduplication is account-wide, while every destructive identity remains
  source-folder + UIDVALIDITY + UID.
- `mailflag/folders.py` discovers selectable existing mailboxes and updates the
  per-account configuration. It never creates or renames server folders.
- `mailflag/opening.py`, `sound.py`, `setup_account.py`: user preferences and
  setup using the selected platform backend rather than Linux commands.

Core modules import neither GTK nor Linux platform modules. `test_core.py` can
run without a desktop session and is the portable regression suite.
