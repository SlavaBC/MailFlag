"""Desktop-independent IMAP actions; a separate connection per action."""
import re


def _valid_uid(uid):
    value = str(uid)
    return value if re.fullmatch(r'[1-9][0-9]*', value) and int(value) <= 4294967295 else None


def move_exact(mailbox_factory, host, folder, email, password, uid,
               uidvalidity, destination_resolver):
    """Move exactly one validated UID; provider supplies destination policy."""
    uid = _valid_uid(uid)
    if uid is None:
        return False
    try:
        expected = int(uidvalidity)
        with mailbox_factory(host).login(email, password, initial_folder=folder) as box:
            if int(box.folder.status(folder)['UIDVALIDITY']) != expected:
                return False
            found = list(box.fetch(uid_list=[uid], mark_seen=False, headers_only=True))
            if len(found) != 1 or str(found[0].uid) != uid:
                return False
            destination = destination_resolver(box)
            if not destination:
                return False
            if int(box.folder.status(folder)['UIDVALIDITY']) != expected:
                return False
            box.move([uid], destination)
            return True
    except Exception as exc:
        print(f'Move failed ({type(exc).__name__}); message was not moved.')
        return False


def named_folder(name):
    """Destination resolver verifying an exact provider folder via IMAP LIST."""
    def resolve(box):
        typ, data = box.client.list('""', name)
        return name if typ == 'OK' and data else None
    return resolve


def special_folder(flag, fallback_names):
    wanted = flag.casefold()
    fallbacks = {value.casefold() for value in fallback_names}
    def resolve(box):
        for info in box.folder.list():
            name = getattr(info, 'name', None)
            flags = getattr(info, 'flags', ())
            if name and any(str(item).casefold() == wanted for item in flags or ()):
                return name
        for info in box.folder.list():
            name = getattr(info, 'name', None)
            if name and name.casefold() in fallbacks:
                return name
        return None
    return resolve


def mark_exact_read(mailbox_factory, host, folder, email, password, uid, uidvalidity):
    uid = _valid_uid(uid)
    if uid is None:
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
