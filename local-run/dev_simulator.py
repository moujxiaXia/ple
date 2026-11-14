r"""本地 evaluator 模拟器 — 把 harness 的 WebSocket 请求映射到 Windows 本地。

用法：
  # 先启动 harness:
  #   $env:PORT=8765; python my-harness/serve.py
  # 再启动模拟器:
  python local-run/dev_simulator.py --smoke
  python local-run/dev_simulator.py --port 8765

exec 命令通过 Git Bash（C:\Program Files\Git\bin\bash.exe）执行。
read_file / write_file 直接映射到本地文件系统的 workdir 下。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from typing import Any

import websockets

GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"
ROOT = pathlib.Path(__file__).resolve().parents[1]  # ple-google
RUNS_DIR = ROOT / "local-run" / "runs"

# 真实评测中 MCP server 跑在任务容器内的 127.0.0.1:8000；本地仿真时可用
# MCP_BASE_URL 或 MCP_BASE_<NAME> 把它换到别的 origin（路径保持不变）。
MAX_HTTP_BYTES = 10 << 20
HOP_BY_HOP = {
    "host", "content-length", "transfer-encoding", "connection", "keep-alive",
    "upgrade", "te", "trailer", "proxy-connection", "proxy-authenticate",
    "proxy-authorization",
}

SMOKE_TASK = {
    "type": "task",
    "protocol": 1,
    "session": "smoke-" + uuid.uuid4().hex[:8],
    "instruction": (
        "Create a file named hello.txt in the working directory containing the "
        "single line 'Hello, world!'. Then answer with a short summary of what "
        "you did."
    ),
    "limits": {
        "agent_timeout_sec": 600,
        "exec_timeout_sec": 120,
        "max_output_bytes": 100_000,
        "max_write_bytes": 10_000_000,
    },
    "mcp_servers": [],
}


def resolve_workdir(session_id: str) -> pathlib.Path:
    workdir = RUNS_DIR / session_id / "app"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def abs_path(workdir: pathlib.Path, p: str) -> pathlib.Path:
    """Resolve a harness path (POSIX-style) to a local absolute path."""
    path = p.replace("/", os.sep).replace("\\", os.sep)
    pp = pathlib.Path(path)
    if not pp.is_absolute():
        pp = workdir / pp
    return pp.resolve()


def run_exec(command: str, timeout_sec: int) -> dict[str, Any]:
    """Run a bash command via Git Bash and return an exec result dict."""
    try:
        result = subprocess.run(
            [GIT_BASH, "-c", command],
            capture_output=True,
            text=True,
            timeout=min(timeout_sec, 600),
            cwd=str(abs_path(RUNS_DIR / "__dummy__", ".")),  # unused; bash -c cwd is set separately
        )
        # Actually cwd needs to be set — but the task workdir varies, we set it in the calling code.
        output = (result.stdout or "") + (result.stderr or "")
        return {
            "ok": True,
            "exit_code": result.returncode,
            "output": output,
            "truncated": False,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": True,
            "exit_code": 124,
            "output": ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else "",
            "truncated": False,
            "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"Git Bash not found at {GIT_BASH}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"exec failed: {type(exc).__name__}: {exc}"}


def mcp_allows(url: str, servers: list[dict[str, Any]]) -> bool:
    """与 taskbridge.mcp_allows 同规则：只允许声明的 MCP server 或其子路径。"""
    try:
        path = urllib.parse.urlsplit(url).path
    except ValueError:
        return False
    decoded = urllib.parse.unquote(path)
    if (
        "%2f" in path.lower()
        or "%5c" in path.lower()
        or "\\" in path
        or ";" in decoded
        or {".", ".."} & set(decoded.split("/"))
    ):
        return False
    for server in servers:
        base = str(server.get("url") or "")
        if base and (
            url == base
            or ("?" not in base and url.startswith(base + "?"))
            or url.startswith(base.rstrip("/") + "/")
        ):
            return True
    return False


def mcp_target(url: str, servers: list[dict[str, Any]]) -> str:
    """把容器内的 MCP 地址重写到本地 MCP server。

    只替换 scheme://host:port，路径与查询串原样保留（本地替身监听同路径）。
    本地 origin 优先级：MCP_BASE_<NAME> > MCP_BASE_URL > 原 origin。
    """
    parts = urllib.parse.urlsplit(url)
    for server in servers:
        base = str(server.get("url") or "")
        if not base:
            continue
        base_parts = urllib.parse.urlsplit(base)
        same_origin = (
            parts.scheme == base_parts.scheme
            and parts.netloc == base_parts.netloc
        )
        if not same_origin:
            continue
        name = str(server.get("name") or "").upper().replace("-", "_")
        local = (
            os.environ.get(f"MCP_BASE_{name}")
            or os.environ.get("MCP_BASE_URL")
            or f"{base_parts.scheme}://{base_parts.netloc}"
        ).rstrip("/")
        local_parts = urllib.parse.urlsplit(local)
        return urllib.parse.urlunsplit((
            local_parts.scheme,
            local_parts.netloc,
            parts.path or "/",
            parts.query,
            "",
        ))
    return url


def forward_http(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: int,
) -> dict[str, Any]:
    """执行一次真实 HTTP 请求；不跟随重定向，剥掉逐跳头，限制 10 MB。"""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return {"ok": False, "error": f"unsupported scheme in {url}"}
    conn_cls = (
        http.client.HTTPSConnection if parts.scheme == "https"
        else http.client.HTTPConnection
    )
    conn = conn_cls(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                    timeout=timeout)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    clean = {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}
    try:
        conn.request(method, target, body=body, headers=clean)
        resp = conn.getresponse()
        data = resp.read(MAX_HTTP_BYTES + 1)
        truncated = len(data) > MAX_HTTP_BYTES
        if truncated:
            data = data[:MAX_HTTP_BYTES]
        return {
            "ok": True,
            "status": resp.status,
            "headers": {k: v for k, v in resp.getheaders()
                        if k.lower() not in HOP_BY_HOP},
            "body_b64": base64.b64encode(data).decode(),
            "truncated": truncated,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"http {method} {url}: "
                                      f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()


async def handle_request(
    req: dict[str, Any],
    workdir: pathlib.Path,
    servers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch one harness request and return a result dict (without id/type)."""
    kind = req.get("type")

    if kind == "exec":
        command = req.get("command", "")
        timeout = int(req.get("timeout_sec", 120))
        print(f"  [exec] {command[:120]}")
        try:
            proc = await asyncio.create_subprocess_exec(
                GIT_BASH, "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workdir),
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=min(timeout, 600)
            )
            output = stdout.decode("utf-8", "replace")
            print(f"    exit={proc.returncode} ({len(output)} bytes)")
            return {
                "ok": True,
                "exit_code": proc.returncode,
                "output": output,
                "truncated": False,
                "timed_out": False,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
                stdout, _ = await proc.communicate()
                return {
                    "ok": True,
                    "exit_code": 124,
                    "output": stdout.decode("utf-8", "replace"),
                    "truncated": False,
                    "timed_out": True,
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"timeout cleanup failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"exec: {type(exc).__name__}: {exc}"}

    if kind == "read_file":
        path_str = req.get("path", "")
        pp = abs_path(workdir, path_str)
        print(f"  [read_file] {path_str} -> {pp}")
        try:
            if not pp.is_file():
                return {"ok": False, "error": f"no such file: {path_str}"}
            data = pp.read_bytes()
            if len(data) > 10_000_000:
                head = data[:5_000_000]
                tail = data[-5_000_000:]
                content = base64.b64encode(head + tail).decode()
                return {
                    "ok": True,
                    "content_b64": content,
                    "size": len(data),
                    "truncated": True,
                }
            return {
                "ok": True,
                "content_b64": base64.b64encode(data).decode(),
                "size": len(data),
                "truncated": False,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"read_file: {type(exc).__name__}: {exc}"}

    if kind == "write_file":
        path_str = req.get("path", "")
        append = bool(req.get("append", False))
        b64 = req.get("content_b64", "")
        pp = abs_path(workdir, path_str)
        print(f"  [write_file] {path_str} ({len(b64)} b64 chars, append={append})")
        try:
            data = base64.b64decode(b64)
            pp.parent.mkdir(parents=True, exist_ok=True)
            mode = "ab" if append else "wb"
            with open(pp, mode) as f:
                f.write(data)
            return {"ok": True, "size": pp.stat().st_size}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"write_file: {type(exc).__name__}: {exc}"}

    if kind == "http":
        url = req.get("url", "")
        method = str(req.get("method") or "GET").upper()
        if not mcp_allows(url, servers):
            print(f"  [http] {method} {url} -> refused (not a declared MCP server)")
            return {
                "ok": False,
                "error": f"http: {url} is not one of the task's MCP servers,"
                         " nor a path under one",
            }
        target = mcp_target(url, servers)
        headers = req.get("headers") or {}
        body = base64.b64decode(req.get("body_b64") or "")
        timeout = min(int(req.get("timeout_sec", 120)), 600)
        print(f"  [http] {method} {url} -> {target} ({len(body)} bytes)")
        result = await asyncio.to_thread(
            forward_http, method, target, headers, body, timeout
        )
        if result.get("ok"):
            print(f"    status={result['status']} "
                  f"body={len(result.get('body_b64') or '')} b64 chars")
        else:
            print(f"    failed: {result.get('error')}")
        return result

    return {"ok": False, "error": f"unknown request type: {kind}"}


async def run_session(harness_ws_url: str, task: dict[str, Any]) -> None:
    """Connect to harness, send task, loop until done/cancel."""
    session_id = task["session"]
    workdir = resolve_workdir(session_id)
    servers = [s for s in (task.get("mcp_servers") or []) if isinstance(s, dict)]
    print(f"\n{'='*60}")
    print(f"Session: {session_id}")
    print(f"Workdir: {workdir}")
    if servers:
        for s in servers:
            print(f"MCP: {s.get('name')} {s.get('url')} -> "
                  f"{mcp_target(str(s.get('url') or ''), [s])}")
    else:
        print("MCP: (none)")
    print(f"{'='*60}")
    print(f"Task instruction (first 200 chars):")
    print(f"  {task['instruction'][:200]}...")
    print()

    task_msg = {**task, "workdir": str(workdir)}

    async with websockets.connect(harness_ws_url, max_size=16 * 1024 * 1024) as ws:
        print(f"→ Connected to {harness_ws_url}")
        await ws.send(json.dumps(task_msg))
        print("→ Sent task message")

        start = time.monotonic()
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=600)
            except asyncio.TimeoutError:
                print("⚠️  No message from harness for 600s — giving up")
                break

            elapsed = time.monotonic() - start
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"⚠️  Bad JSON from harness: {exc}; ignoring")
                continue

            kind = msg.get("type")

            if kind == "cancel":
                print(f"←  Received cancel after {elapsed:.0f}s")
                break

            if kind == "log":
                text = msg.get("text", "")
                if text:
                    for line in text.strip().splitlines()[-3:]:
                        print(f"  [log] {line}")
                continue

            if kind == "usage":
                print(f"  [usage] {msg.get('model')}: "
                      f"in={msg.get('input_tokens')} "
                      f"out={msg.get('output_tokens')} "
                      f"cache={msg.get('cache_read_tokens')}")
                continue

            if kind == "done":
                final = msg.get("final_message", "")
                print(f"\n✓  Task done after {elapsed:.1f}s")
                print(f"  Final message ({len(final)} chars):")
                for line in final.strip().splitlines():
                    print(f"    {line[:200]}")
                break

            if kind == "error":
                print(f"✗  Harness error after {elapsed:.1f}s: {msg.get('message', '')}")
                break

            # Request types that need a result: exec / read_file / write_file / http
            if kind in ("exec", "read_file", "write_file", "http"):
                rid = msg.get("id", str(uuid.uuid4()))
                result = await handle_request(msg, workdir, servers)
                reply = {"type": "result", "id": rid, **result}
                await ws.send(json.dumps(reply))
                continue

            print(f"  [unknown] {json.dumps(msg)[:200]}")

    # 收集 deliverables
    print(f"\n📁 Deliverables in {workdir}:")
    for p in sorted(workdir.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(workdir)}  ({p.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local PLE evaluator simulator")
    parser.add_argument("--port", type=int, default=8765,
                        help="Port the harness listens on (default 8765)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--smoke", action="store_true",
                        help="Run the built-in smoke task")
    parser.add_argument("--task-file", type=str,
                        help="Path to a task JSON file (overrides --smoke)")
    args = parser.parse_args()

    url = f"ws://{args.host}:{args.port}"

    if args.task_file:
        with open(args.task_file, encoding="utf-8") as f:
            task = json.load(f)
    elif args.smoke:
        task = SMOKE_TASK
    else:
        parser.error("Must pass --smoke or --task-file")
        return

    try:
        asyncio.run(run_session(url, task))
    except ConnectionRefusedError:
        print(f"\n✗  Cannot connect to {url}. Is the harness running?")
        print(f"    Start it with:")
        print(f'      $env:PORT={args.port}; $env:MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"; $env:MODEL_NAME="YOUR_ENDPOINT_ID"; $env:MODEL_API_KEY="YOUR_KEY"; python my-harness/serve.py')
        sys.exit(1)


if __name__ == "__main__":
    main()
