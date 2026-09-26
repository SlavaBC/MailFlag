# Manual OTP end-to-end checklist

The JSON/pytest corpus covers the classifier offline. Use these few real-mail
checks only for the full integration chain:

1. Send `Your verification code is 482913`; expect OTP popup `482913`.
2. Click the code; verify clipboard contains exactly `482913`, popup closes,
   and that exact UID moves to Trash.
3. Send `Security code 8841`; verify the four-digit path.
4. Send HTML mail containing `<b>654321</b>` next to `verification code`.
5. Send a normal GitHub/CI subject containing build and commit numbers; expect
   the ordinary-mail popup.
6. Let an OTP popup time out; verify it becomes pending and is not moved.
7. Open a pending OTP and click it; verify copy and exact-message Trash again.
8. Repeat one OTP on each configured account to check per-account UIDVALIDITY.

Full path under test:

`IMAP IDLE → MIME parsing → OTP classifier → popup → clipboard → Trash`
