MAILFLAG PRIVACY POLICY

Last updated: October 6, 2026

MailFlag is a lightweight desktop email notifier designed to process email locally on your computer. This Privacy Policy explains what information MailFlag handles, how it is used, and what is not collected.

1. LOCAL PROCESSING

MailFlag connects directly to your configured email provider over IMAP and processes new messages locally on your device.

MailFlag may inspect message metadata and content, including sender, subject, message body, folder, and message identifiers, in order to:
- detect verification and one-time-password (OTP) codes;
- build notification previews;
- show sender and subject information;
- perform actions you request, such as marking a message as read, moving it to Trash or Spam, or opening it in your mail application or webmail;
- maintain local notification and recovery state.

MailFlag does not send your email content, verification codes, or credentials to MailFlag-operated servers.

2. EMAIL ACCOUNT CREDENTIALS

MailFlag does not store email passwords or app passwords in plain-text configuration files.

Credentials are stored in the operating system's secure credential storage, such as Linux Secret Service / keyring, and are used only to authenticate directly with your email provider.

MailFlag does not operate an authentication relay or credential server.

3. LOCAL DATA

MailFlag stores limited operational data on your computer, which may include:
- configured email account addresses;
- IMAP server and account settings;
- monitored folders;
- UIDVALIDITY and message checkpoints;
- pending-notification state;
- application preferences and settings.

This information is used only to operate MailFlag and restore its state after restart, reconnect, or sleep/resume.

4. NETWORK COMMUNICATIONS

MailFlag communicates directly with the email servers you configure.

Depending on your settings, MailFlag may also open your default mail application or a provider's webmail page when you choose an Open action.

MailFlag does not use its own server to proxy, copy, or store your mailbox data.

5. CLIPBOARD

When you click an OTP or verification code, MailFlag may copy that code to the system clipboard so you can paste it into another application.

Clipboard contents may be accessible to other applications according to the security model of your operating system and desktop environment.

6. ANALYTICS, ADVERTISING, AND TRACKING

MailFlag does not include advertising, analytics, behavioral tracking, or telemetry.

MailFlag does not sell personal information.

MailFlag does not use your email content or account data for AI training.

7. THIRD-PARTY EMAIL PROVIDERS

Your email provider processes your account data under its own terms and privacy policy.

MailFlag only accesses the mailbox functionality required for the features you enable. Actions such as Delete, Spam, and Mark as Read are performed directly against your email provider through IMAP.

8. DATA SHARING

MailFlag does not intentionally share your email content, verification codes, credentials, or locally stored MailFlag data with third parties.

Any data transmitted to your email provider is part of the normal operation of your existing email account.

9. DATA RETENTION AND REMOVAL

MailFlag keeps local configuration and operational state until you remove or change it.

Removing the MailFlag application from your computer does not necessarily remove user-level configuration files or credentials stored in the system keyring.

Account-specific credentials and local account data can be removed separately. MailFlag will not delete messages or folders from your mailbox merely because the application itself is uninstalled.

10. SECURITY

MailFlag is designed to minimize unnecessary data exposure by keeping processing local and using the operating system's credential storage.

No software can guarantee absolute security. Users remain responsible for securing their computer, operating system account, email account, and email-provider credentials.

11. CHANGES TO THIS POLICY

This Privacy Policy may be updated as MailFlag gains new features, providers, platforms, or network capabilities.

Material changes that affect how personal data is processed should be reflected in an updated version of this policy.

12. CONTACT

For privacy questions, use the contact method published in the official MailFlag GitHub repository or project website.

