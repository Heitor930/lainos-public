"""O assistente fala com o greetd para entrar na sessão logo depois de criar a conta."""
import json
import os
import socket
import struct
import tempfile
import threading
import unittest

import _paths  # noqa: F401
from firstboot import greetd


class FakeGreetd:
    """Servidor mínimo que segue o protocolo do greetd e anota o que recebeu."""

    def __init__(self, path, password="segredo!", ask_info=False):
        self.path, self.password, self.ask_info = path, password, ask_info
        self.log = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            def receive():
                header = conn.recv(4)
                if len(header) < 4:
                    return None
                (size,) = struct.unpack("=I", header)
                return json.loads(conn.recv(size).decode())

            def send(message):
                data = json.dumps(message).encode()
                conn.sendall(struct.pack("=I", len(data)) + data)

            informed = False
            while True:
                message = receive()
                if message is None:
                    break
                self.log.append(message)
                kind = message["type"]
                if kind == "create_session":
                    if self.ask_info:
                        send({"type": "auth_message", "auth_message_type": "info", "auth_message": "Olá"})
                    else:
                        send({"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password: "})
                elif kind == "post_auth_message_response":
                    if self.ask_info and not informed:
                        informed = True
                        send({"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password: "})
                    elif message.get("response") == self.password:
                        send({"type": "success"})
                    else:
                        send({"type": "error", "error_type": "auth_error", "description": "senha errada"})
                else:
                    send({"type": "success"})

    def close(self):
        self.thread.join(2)
        self.server.close()


class Login(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, "greetd.sock")
        self.old = os.environ.get("GREETD_SOCK")
        os.environ["GREETD_SOCK"] = self.sock

    def tearDown(self):
        if self.old is None:
            os.environ.pop("GREETD_SOCK", None)
        else:
            os.environ["GREETD_SOCK"] = self.old
        self.tmp.cleanup()

    def test_successful_login_starts_the_session(self):
        server = FakeGreetd(self.sock)
        greetd.login("ana", "segredo!", ["lain-start-hyprland"], env=["XDG_SESSION_TYPE=wayland"])
        server.close()
        self.assertEqual([m["type"] for m in server.log],
                         ["create_session", "post_auth_message_response", "start_session"])
        self.assertEqual(server.log[0]["username"], "ana")
        self.assertEqual(server.log[2]["cmd"], ["lain-start-hyprland"])
        self.assertEqual(server.log[2]["env"], ["XDG_SESSION_TYPE=wayland"])

    def test_info_messages_are_acknowledged(self):
        server = FakeGreetd(self.sock, ask_info=True)
        greetd.login("ana", "segredo!", ["x"])
        server.close()
        self.assertEqual([m["type"] for m in server.log],
                         ["create_session", "post_auth_message_response", "post_auth_message_response",
                          "start_session"])
        self.assertNotIn("response", server.log[1])
        self.assertEqual(server.log[2]["response"], "segredo!")

    def test_wrong_password_cancels_and_reports(self):
        server = FakeGreetd(self.sock)
        with self.assertRaises(greetd.GreetdError) as caught:
            greetd.login("ana", "errada", ["x"])
        server.close()
        self.assertIn("senha errada", str(caught.exception))
        self.assertEqual([m["type"] for m in server.log],
                         ["create_session", "post_auth_message_response", "cancel_session"])

    def test_outside_greetd(self):
        del os.environ["GREETD_SOCK"]
        self.assertFalse(greetd.available())
        with self.assertRaises(greetd.GreetdError):
            greetd.login("ana", "x", ["x"])
        os.environ["GREETD_SOCK"] = self.sock


if __name__ == "__main__":
    unittest.main()
