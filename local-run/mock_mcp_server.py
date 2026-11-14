"""本地 MCP server（Streamable HTTP），用于在没有任务容器时验证 harness 的 MCP 链路。

真实评测中任务容器在 http://127.0.0.1:8000/mcp/ 暴露项目应用（文档、表格、邮件、
CAD）。本文件提供一个最小可用的替身：一个受 --root 限制的 world 文件系统应用。

协议实现要点（与 docs/protocol.md 一致）：
  - POST 同一路径承接 JSON-RPC：initialize / notifications/initialized /
    tools/list / tools/call / ping
  - initialize 返回 Mcp-Session-Id 头，后续请求带上即可
  - 回复使用 application/json（协议允许 JSON 与 SSE 两种，这里只发 JSON）

用法：
  python local-run/mock_mcp_server.py                 # 监听 127.0.0.1:8000
  python local-run/mock_mcp_server.py --port 8001
"""

from __future__ import annotations

import argparse
import json
import pathlib
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MCP_PATH = "/mcp/"
PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 10 << 20

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files under a world directory, newest name order.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "relative to world root"},
            },
            "required": ["dir"],
        },
    },
    {
        "name": "read_text",
        "description": "Read a UTF-8 text file from the world.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_text",
        "description": "Write a UTF-8 text file into the world.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
]

_lock = threading.Lock()


def _text(message: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": message}]


class World:
    """world 根目录下的受限文件访问。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str) -> pathlib.Path:
        target = (self.root / path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"{path} escapes the world root")
        return target

    def list_files(self, dir: str) -> list[dict[str, Any]]:
        target = self.resolve(dir)
        if not target.is_dir():
            raise ValueError(f"{dir} is not a directory")
        names = sorted(p.name for p in target.iterdir())
        return _text("\n".join(names) if names else "(empty)")

    def read_text(self, path: str) -> list[dict[str, Any]]:
        target = self.resolve(path)
        if not target.is_file():
            raise ValueError(f"no such file: {path}")
        return _text(target.read_text(encoding="utf-8", errors="replace"))

    def write_text(self, path: str, content: str) -> list[dict[str, Any]]:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            target.write_text(content, encoding="utf-8")
        return _text(f"wrote {len(content.encode())} bytes to {path}")


def rpc(world: World, req: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 请求；通知类返回 None（不回包）。"""
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "world-apps", "version": "0.1"},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handlers = {
            "list_files": world.list_files,
            "read_text": world.read_text,
            "write_text": world.write_text,
        }
        try:
            if name not in handlers:
                raise ValueError(f"unknown tool {name}")
            content = handlers[name](**args)
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": content, "isError": False},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": _text(f"error: {type(exc).__name__}: {exc}"),
                    "isError": True,
                },
            }
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"unknown method {method}"},
    }


class Handler(BaseHTTPRequestHandler):
    world: World
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        print(f"[mcp] {fmt % args}", flush=True)

    def _send(self, status: int, payload: bytes, headers: dict[str, str] | None
              ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        # 单独一条 GET 是 SSE 流；一次 http 请求承载不了，明确拒绝
        self._send(405, b'{"error": "use POST"}', {"Allow": "POST"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith(MCP_PATH):
            self._send(404, b'{"error": "not found"}', None)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, b'{"error": "body too large"}', None)
            return
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            self._send(400, b'{"error": "invalid JSON"}', None)
            return

        headers: dict[str, str] = {}
        if not self.headers.get("Mcp-Session-Id"):
            headers["Mcp-Session-Id"] = uuid.uuid4().hex
        headers["MCP-Protocol-Version"] = (
            self.headers.get("MCP-Protocol-Version") or PROTOCOL_VERSION
        )

        if isinstance(req, list):
            replies = [r for r in (rpc(self.world, m) for m in req) if r]
            if not replies:
                self._send(202, b"", headers)
                return
            self._send(200, json.dumps(replies).encode(), headers)
            return

        reply = rpc(self.world, req)
        if reply is None:
            self._send(202, b"", headers)
            return
        self._send(200, json.dumps(reply).encode(), headers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local mock MCP world app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--root",
        default=str(pathlib.Path(__file__).resolve().parent / "world"),
        help="world 根目录（工具只能访问其内部）",
    )
    args = parser.parse_args()

    Handler.world = World(pathlib.Path(args.root))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock MCP listening on http://{args.host}:{args.port}{MCP_PATH} "
          f"root={Handler.world.root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
