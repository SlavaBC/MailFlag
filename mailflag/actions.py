"""Desktop-independent IMAP actions; a separate connection per action."""
import re


def mark_exact_read(mailbox_factory, host, folder, email, password, uid, uidvalidity):
    uid = str(uid)
    if not re.fullmatch(r'[1-9][0-9]*', uid) or int(uid) > 4294967295:
        return False
    try:
        expected = int(uidvalidity)
        if expected <= 0:
            return False
        with mailbox_factory(host).login(email, password, initial_folder=folder) as box:
            if int(box.folder.status(folder)['UIDVALIDITY']) != expected:
                return False
            found = list(box.fetch(uid_list=[uid], mark_seen=False, headers_only=True))
            if len(found) != 1 or str(found[0].uid) != uid:
                return False
            if int(box.folder.status(folder)['UIDVALIDITY']) != expected:
                return False
            box.flag([uid], r'\Seen', True)
            # UID STORE never substitutes sequence numbers. A concurrent expunge
            # can produce an OK no-op; verify the message and flag afterward.
            found = list(box.fetch(uid_list=[uid], mark_seen=False, headers_only=True))
            return (int(box.folder.status(folder)['UIDVALIDITY']) == expected
                    and len(found) == 1 and str(found[0].uid) == uid
                    and r'\Seen' in found[0].flags)
    except Exception as exc:
        print(f'Mark as read failed ({type(exc).__name__}); kept in pending.')
        return False
