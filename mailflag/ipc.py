"""Small local Unix-socket control channel for the background process."""

import socket
import threading
import os


def send_command(path, command, timeout=1.0, expect_response=False):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(path))
            client.sendall((command.strip() + "\n").encode("utf-8"))
            if expect_response:
                client.shutdown(socket.SHUT_WR)
                response = client.recv(4096).decode("utf-8", "replace").strip()
                return response or None
        return True
    except OSError:
        return False


class ControlServer:
    def __init__(self, path, callback):
        self.path = path
        self.callback = callback
        self.socket = None
        self.thread = None

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self.socket.listen(4)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while self.socket is not None:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                break
            try:
                with connection:
                    command = connection.recv(256).decode("utf-8", "replace").strip()
                    if command:
                        try:
                            response = self.callback(command)
                        except Exception as exc:
                            response = f"ERROR: {type(exc).__name__}: {exc}"
                        if response is not None:
                            try:
                                connection.sendall(
                                    (str(response) + "\n").encode("utf-8")
                                )
                            except OSError:
                                pass
            except OSError:
                continue

    def close(self):
        current, self.socket = self.socket, None
        if current is not None:
            try:
                current.close()
            except OSError:
                pass
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
