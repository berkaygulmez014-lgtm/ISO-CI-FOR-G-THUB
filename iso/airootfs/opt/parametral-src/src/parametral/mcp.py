"""MCP adapter for the Parametral tool API.

MCP is how a model *sees* tools; the gateway is what decides whether a call may happen. This
module is deliberately thin: it speaks MCP over stdio, maps each tool to one gateway method,
and hands every decision to the daemon (capability tokens, approvals, the tier-2 oracle,
sandbox, audit). Putting policy in here would create a second, weaker place to get it wrong.

Protocol: JSON-RPC 2.0 over stdio, one message per line, MCP revision 2024-11-05.

Run: parametral-mcp           (talks to the daemon socket, as the ai user)
"""
from __future__ import annotations

import json
import os
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "parametral"
SERVER_VERSION = "0.1.0"

# name -> (gateway method, description, input schema)
TOOLS: dict[str, dict] = {
    "sandbox_create": {
        "method": "v1.sandbox.create",
        "description": "Create an isolated sandbox. Everything the model runs lives inside one.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "short label, max 63 chars"},
                "limits": {
                    "type": "object",
                    "description": "cpu_cores, memory_mb, disk_mb, pids",
                    "properties": {
                        "cpu_cores": {"type": "number"},
                        "memory_mb": {"type": "integer"},
                        "disk_mb": {"type": "integer"},
                        "pids": {"type": "integer"},
                    },
                },
                "net": {"type": "boolean", "description": "network is off unless a grant exists"},
            },
            "required": ["name"],
        },
    },
    "sandbox_destroy": {
        "method": "v1.sandbox.destroy",
        "description": "Destroy a sandbox and everything in it.",
        "schema": {
            "type": "object",
            "properties": {"sandbox_id": {"type": "string"}, "purge": {"type": "boolean"}},
            "required": ["sandbox_id"],
        },
    },
    "exec_run": {
        "method": "v1.exec.run",
        "description": (
            "Run a command inside a sandbox. Pass a verdict to assert the outcome; without one "
            "'it ran' is all you know."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "cmd": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "env": {"type": "object"},
                "timeout_s": {"type": "integer"},
                "verdict": {
                    "type": "object",
                    "description": (
                        "postcondition: expect_exit, stdout_contains, stderr_contains, "
                        "stdout_regex, file_exists, file_sha256"
                    ),
                },
                "capability_token": {"type": "string"},
            },
            "required": ["sandbox_id", "cmd"],
        },
    },
    "fs_read": {
        "method": "v1.fs.read",
        "description": "Read a file inside a sandbox.",
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "path": {"type": "string"},
                "max_bytes": {"type": "integer"},
            },
            "required": ["sandbox_id", "path"],
        },
    },
    "fs_write": {
        "method": "v1.fs.write",
        "description": "Write a file inside a sandbox (creates parents by default).",
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "content_b64": {"type": "string"},
                "mode": {"type": "string"},
            },
            "required": ["sandbox_id", "path"],
        },
    },
    "fs_list": {
        "method": "v1.fs.list",
        "description": "List a directory inside a sandbox.",
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
            },
            "required": ["sandbox_id", "path"],
        },
    },
    "app_install": {
        "method": "v1.app.install",
        "description": (
            "Install an application from Nix into a sandbox profile. Returns a generation that "
            "can be rolled back."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "manifest": {
                    "type": "object",
                    "properties": {
                        "flake_ref": {"type": "string", "description": "e.g. nixpkgs#ripgrep"},
                        "flake_lock": {"type": "string", "description": "pinned hash; required"},
                        "name": {"type": "string"},
                    },
                    "required": ["flake_ref"],
                },
                "capability_token": {"type": "string"},
            },
            "required": ["sandbox_id", "manifest"],
        },
    },
    "app_verify": {
        "method": "v1.app.verify",
        "description": "Check that an installed application actually runs.",
        "schema": {
            "type": "object",
            "properties": {"sandbox_id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["sandbox_id", "name"],
        },
    },
    "snapshot_create": {
        "method": "v1.snapshot.create",
        "description": "Snapshot a sandbox before a risky change.",
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "label": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["sandbox_id"],
        },
    },
    "snapshot_restore": {
        "method": "v1.snapshot.restore",
        "description": "Roll a sandbox back to a snapshot. Needs confirm=true.",
        "schema": {
            "type": "object",
            "properties": {
                "sandbox_id": {"type": "string"},
                "snapshot_id": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["sandbox_id", "snapshot_id", "confirm"],
        },
    },
    "approval_get": {
        "method": "v1.approvals.get",
        "description": (
            "Check a pending approval. wait_s long-polls; state is pending/approved/rejected/"
            "deferred/expired."
        ),
        "schema": {
            "type": "object",
            "properties": {"approval_id": {"type": "string"}, "wait_s": {"type": "number"}},
            "required": ["approval_id"],
        },
    },
    "node_status": {
        "method": "v1.node.status",
        "description": "Node health: sandboxes, audit head, tier-2 oracle availability.",
        "schema": {"type": "object", "properties": {}},
    },
}


def tool_list() -> list[dict]:
    return [
        {"name": name, "description": spec["description"], "inputSchema": spec["schema"]}
        for name, spec in TOOLS.items()
    ]


class McpServer:
    """Transport-only MCP server: every decision is the backend's."""

    def __init__(self, backend):
        # backend(method: str, params: dict) -> dict, raising an exception with .code/.message
        self.backend = backend

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        # notifications carry no id and expect no response
        if msg_id is None and method and method.startswith("notifications/"):
            return None

        if method == "initialize":
            return _ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "ping":
            return _ok(msg_id, {})
        if method == "tools/list":
            return _ok(msg_id, {"tools": tool_list()})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            return self._call_tool(msg_id, name, arguments)

        return _err(msg_id, -32601, f"unknown method: {method}")

    def _call_tool(self, msg_id, name: str, arguments: dict) -> dict:
        spec = TOOLS.get(name)
        if spec is None:
            return _err(msg_id, -32602, f"unknown tool: {name}")

        missing = [key for key in spec["schema"].get("required", []) if key not in arguments]
        if missing:
            return _ok(msg_id, _tool_result(
                f"missing required argument(s): {', '.join(missing)}", is_error=True))

        try:
            result = self.backend(spec["method"], arguments)
        except Exception as exc:  # noqa: BLE001 - the model must see the failure
            code = getattr(exc, "code", None)
            detail = getattr(exc, "data", None)
            text = f"{code if code is not None else 'ERROR'}: {exc}"
            if detail:
                text += f"\n{json.dumps(detail, ensure_ascii=False)}"
            return _ok(msg_id, _tool_result(text, is_error=True))

        return _ok(msg_id, _tool_result(json.dumps(result, ensure_ascii=False, indent=2)))


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _ok(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(backend, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    server = McpServer(backend)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps(_err(None, -32700, f"parse error: {exc}")) + "\n")
            stdout.flush()
            continue
        response = server.handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    """Connect to the running daemon and serve MCP on stdio."""
    socket_path = os.environ.get("PARAMETRAL_SOCKET")
    try:
        from .client import Client
    except ImportError:                      # running from the bin/ entry point
        from parametral.client import Client

    def backend(method: str, params: dict) -> dict:
        client = Client(socket_path=socket_path)
        try:
            return client.call(method, **params)
        finally:
            client.close()

    return serve(backend)


if __name__ == "__main__":
    raise SystemExit(main())
