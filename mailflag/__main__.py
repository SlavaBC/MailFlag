"""Application entry point and single-instance guard."""
import sys
from .platform import get_platform
from .single_instance import acquire_instance_lock
from .version import __version__


def main():
    if '--version' in sys.argv:
        print(f'MailFlag {__version__}')
        return
    if '--configure-folders' in sys.argv:
        from .folders import configure_folders
        index = sys.argv.index('--configure-folders')
        account = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        configure_folders(account)
        return
    if '--add-account' in sys.argv:
        from . import setup_account
        return
    if '--demo' in sys.argv:
        from . import app
        app.install_ui_styles()
        # Offline UI preview: all mail/network actions are replaced.
        app.open_default_mail_app = lambda: True
        app.move_regular_to_trash = lambda *a: True
        app.move_regular_to_spam = lambda *a: True
        app.mark_exact_read = lambda *a: True
        app.add_pending_uid = lambda *a: None
        app.regular_popup.show('Long sender ' + 'a' * 180 + '@example.test',
                               'Long subject ' * 35, 'Preview text ' * 35,
                               1, 1, 'demo@example.test', '')
        app.regular_popup.window.connect("destroy", lambda *_: app.Gtk.main_quit())
        app.Gtk.main()
        return
    directory = get_platform().paths.config_dir
    lock = acquire_instance_lock(directory / 'instance.lock')
    if lock is None:
        print('MailFlag is already running.')
        return
    with lock:
        from .app import main as run
        run()


if __name__ == '__main__':
    main()
