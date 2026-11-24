"""Thin JSON-RPC client for the v1 API.

Berkay's AI can copy this file (stdlib only) or reimplement it from
docs/API-v1.md — the wire format is the contract, this is just convenience.
"""
from __future__ import annotations

import json
import socket

from . import util

PROTOCOL_VERSION = "v1"


class ClientError(RuntimeError):
    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data or {}

    @property
    def parametral_code(self) -> str:
        return self.data.get("parametral_code", "UNKNOWN")


class Client:
    def __init__(self, socket_path: str | None = None, node_id: str = "local",
                 timeout: float = 120.0):
        self.socket_path = socket_path or util.socket_path()
        self.node_id = node_id
        self.timeout = timeout
        self._socket = None
        self._id = 0

    # ------------------------------------------------------------------ io

    def connect(self) -> "Client":
        if self._socket is not None:
            return self
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self._socket = sock
        return self

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def __enter__(self) -> "Client":
        return self.connect()

    def __exit__(self, *_exc) -> None:
        self.close()

    def call(self, method: str, **params):
        self.connect()
        self._id += 1
        params.setdefault("node_id", self.node_id)
        payload = {"jsonrpc": "2.0", "id": f"req-{self._id}", "method": method,
                   "params": params}
        self._socket.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ClientError(-32603, "daemon closed the connection", {})
            buffer += chunk
        response = json.loads(buffer)
        if "error" in response:
            error = response["error"]
            raise ClientError(error.get("code"), error.get("message"), error.get("data"))
        return response.get("result")

    # ------------------------------------------------------------ shortcuts

    def hello(self, client_version: str = "parametral-client/0.1.0") -> dict:
        return self.call("v1.node.hello", client_version=client_version,
                         protocol_versions=[PROTOCOL_VERSION])

    def status(self) -> dict:
        return self.call("v1.node.status")

    def request_permission(self, operation: str, scope: dict, justification: str,
                           ttl_s: int | None = None, approval_id: str | None = None,
                           max_uses: int | None = None) -> dict:
        params = {"operation": operation, "scope": scope, "justification": justification}
        if ttl_s is not None:
            params["ttl_s"] = ttl_s
        if approval_id is not None:
            params["approval_id"] = approval_id
        if max_uses is not None:
            params["max_uses"] = max_uses
        return self.call("v1.permission.request", **params)

    def sandbox_create(self, name: str, **options) -> dict:
        return self.call("v1.sandbox.create", name=name, **options)

    def exec(self, sandbox_id: str, cmd: list[str], token: str, **options) -> dict:
        return self.call("v1.exec.run", sandbox_id=sandbox_id, cmd=cmd,
                         capability_token=token, **options)

    def fs_write(self, sandbox_id: str, path: str, token: str, **options) -> dict:
        return self.call("v1.fs.write", sandbox_id=sandbox_id, path=path,
                         capability_token=token, **options)

    def fs_read(self, sandbox_id: str, path: str, token: str, **options) -> dict:
        return self.call("v1.fs.read", sandbox_id=sandbox_id, path=path,
                         capability_token=token, **options)
