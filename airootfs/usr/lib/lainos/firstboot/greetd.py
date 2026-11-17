"""Conversa com o greetd para já entrar na sessão depois de criar a conta.

O assistente roda no lugar da tela de login, então fala o mesmo protocolo
que ela: mensagens JSON precedidas do tamanho (4 bytes, ordem nativa) pelo
soquete indicado em $GREETD_SOCK.
"""
from __future__ import annotations

import json
import os
import socket
import struct


class GreetdError(RuntimeError):
    pass


def _send(sock: socket.socket, message: dict) -> None:
    payload = json.dumps(message).encode("utf-8")
    sock.sendall(struct.pack("=I", len(payload)) + payload)


def _read_exact(sock: socket.socket, count: int) -> bytes:
    chunks = b""
    while len(chunks) < count:
        piece = sock.recv(count - len(chunks))
        if not piece:
            raise GreetdError("o greetd fechou a conexão")
        chunks += piece
    return chunks


def _receive(sock: socket.socket) -> dict:
    (length,) = struct.unpack("=I", _read_exact(sock, 4))
    if length > 1024 * 1024:
        raise GreetdError("resposta grande demais do greetd")
    return json.loads(_read_exact(sock, length).decode("utf-8"))


def available() -> bool:
    return bool(os.environ.get("GREETD_SOCK"))


def login(username: str, password: str, command: list[str],
          env: list[str] | None = None, timeout: float = 20.0) -> None:
    """Autentica e pede ao greetd para iniciar a sessão. Levanta GreetdError se falhar.

    Depois que esta função retorna, o processo precisa terminar: o greetd só
    inicia a sessão do usuário quando a tela de login sai.
    """
    path = os.environ.get("GREETD_SOCK")
    if not path:
        raise GreetdError("fora do greetd")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        _send(sock, {"type": "create_session", "username": username})
        for _ in range(12):
            reply = _receive(sock)
            kind = reply.get("type")
            if kind == "success":
                break
            if kind == "auth_message":
                if reply.get("auth_message_type") in ("secret", "visible"):
                    _send(sock, {"type": "post_auth_message_response", "response": password})
                else:
                    _send(sock, {"type": "post_auth_message_response"})
                continue
            description = reply.get("description") or "erro de autenticação"
            try:
                _send(sock, {"type": "cancel_session"})
                _receive(sock)
            except (OSError, GreetdError, ValueError):
                pass
            raise GreetdError(description)
        else:
            raise GreetdError("o greetd não concluiu a autenticação")

        _send(sock, {"type": "start_session", "cmd": command, "env": list(env or [])})
        reply = _receive(sock)
        if reply.get("type") != "success":
            raise GreetdError(reply.get("description") or "não consegui iniciar a sessão")
