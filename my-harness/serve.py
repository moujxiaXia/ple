# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Plan-work-verify harness running three specialized agent roles per task.

1. The planner inspects the task's files and writes a plan describing each
   deliverable, its path and format, and how to verify it.
2. The worker executes the task using the plan; its answer becomes the final
   message.
3. The verifier starts with a fresh conversation containing only the task, the
   plan, and the worker's summary. It inspects the deliverables and replies
   `PASS` or lists specific gaps, which are sent back to the worker for up to
   `MAX_FIX_ROUNDS` rounds while sufficient time remains.

The planner and verifier receive only `bash` and `read_file` and are instructed
not to modify any files.
"""

import asyncio
import json
import os
import re
import time

import openai
import taskbridge


def log(*parts):
  """Writes one flushed progress line to the container log."""
  print("[harness]", *parts, flush=True)


MODEL = os.environ["MODEL_NAME"]
# The model's highest reasoning level: max for Claude, GLM, GPT-6 and
# DeepSeek-V4, high for the others (Gemini refuses max). REASONING_EFFORT
# overrides it.
MAX_EFFORT_MODELS = ("claude", "glm", "gpt-6", "deepseek-v4")
# REASONING_EFFORT overrides it. Unknown models get no effort field: Ark's
# coding endpoint stalls indefinitely when it receives one.
EFFORT = os.environ.get("REASONING_EFFORT")
if EFFORT is None:
  EFFORT = "max" if any(m in MODEL.lower() for m in MAX_EFFORT_MODELS) else ""
# a fix round wraps up this long before the time limit, and a wrap-up call may
# take as long
WRAP_UP_SEC = 240
WRAP_UP = {
    "role": "user",
    "content": "Time is up for this step. Stop and reply with your answer.",
}
RESULT_CHARS = 20_000  # a longer tool result loses its middle
# Seconds between retries once the SDK's own quick retries are exhausted.
RETRY_WAITS = (5, 15, 30, 60, 120)
# How endpoints word a 400 saying the conversation no longer fits the context
# window: Claude, OpenAI and vLLM, Gemini, xAI.
CONTEXT_FULL = re.compile(
    r"context.?(length|window)|prompt is too long|maximum prompt length"
    r"|exceed[^.]{0,40}(token|context)",
    re.I,
)
CUT_KEEP = 1000  # characters a tool result keeps once the context is full
# times in a row an empty or cut-off reply gets a "continue" before the run
# stops
MAX_NUDGES = 3
# lower it for a small context window
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "32000"))
# Recent turns kept verbatim; older ones are dropped from the request.
CONTEXT_KEEP = int(os.environ.get("CONTEXT_KEEP", "16"))
# A single model call is capped so one stalled request cannot eat the budget.
MAX_CALL_SEC = float(os.environ.get("MAX_CALL_SECONDS", "900"))
# Claude caches a prompt prefix only when marked with cache_control. Each call
# marks the system prompt and the latest message (using 2 of Claude's 4 cache
# breakpoints) so each turn reads the prior conversation from cache. Other
# providers cache automatically without markers.
CACHE_MARK = "claude" in MODEL.lower()
# the planner wraps up once it has used this share of the task's time
PLAN_SHARE = 0.1
# the worker wraps up when this share is left, to keep time for checking and
# fixing
CHECK_SHARE = 0.25
# a check or a fix round starts only with this long to work before its own
# wrap-up
MIN_STEP_SEC = 120
MAX_FIX_ROUNDS = 2

# Connect to any OpenAI-compatible endpoint via standard env vars
# (OPENAI_BASE_URL, OPENAI_API_KEY) or our own aliases (MODEL_BASE_URL,
# MODEL_API_KEY) for local development. Egress timeout 1800 s matches the
# proxy's 30-minute idle limit.
_BASE_URL = os.environ.get("MODEL_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
_API_KEY = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none"
client = openai.AsyncOpenAI(
    base_url=_BASE_URL, api_key=_API_KEY,
    max_retries=5, timeout=1800,
)

PLANNER = """You plan an engineering task that another engineer will carry out in a Linux container with no internet \
access. Inspect the task's files with your tools (bash starts in {workdir}), but do not create or change any file. \
Then reply with the plan: each deliverable with its exact path and format, what it must contain, the data and method \
to use, and how to check it."""

WORKER = """You are an expert engineer working on a task in a Linux container with no internet access. Your tools \
act inside it, and bash starts in {workdir}. A plan for the task follows it; use it, and correct it where the files \
show it is wrong. Compute with code, not by hand. Write each deliverable exactly where and in the format the task \
asks, then open it again to check it. If the clock is short, put a complete first version of every deliverable in place \
before refining any of it. When you are done, reply without calling a tool: a short summary of each \
deliverable, where it is, and the key results."""

VERIFIER = """You check an engineer's work on a task in a Linux container. You get the task, the plan, and the \
engineer's summary of what was delivered. Open every deliverable with your tools (bash starts in {workdir}) and check \
it against the task: the path, the format, every part the task asks for, and the key numbers, recomputed. Do not \
create or change any file. If everything holds, reply with the single word PASS and nothing else. Otherwise reply \
with a numbered list of the gaps, each specific enough to fix."""


def tool(name, description, **params):
  """Builds an OpenAI function-tool definition dictionary.

  Args:
    name: Tool function name.
    description: Human-readable tool description.
    **params: Parameter names mapped to their JSON Schema type strings.

  Returns:
    An OpenAI function-tool specification dictionary.
  """
  return {
      "type": "function",
      "function": {
          "name": name,
          "description": description,
          "parameters": {
              "type": "object",
              "properties": {k: {"type": v} for k, v in params.items()},
              "required": list(params),
          },
      },
  }


TOOLS = [
    tool(
        "bash",
        "Run a bash command (120 s limit) and return its exit code and output.",
        command="string",
    ),
    tool("read_file", "Read a text file.", path="string"),
    tool(
        "write_file",
        "Create or overwrite a file; parent folders are created.",
        path="string",
        content="string",
    ),
]
READ_ONLY = TOOLS[:2]


class Mcp:
    """任务容器内一个 Streamable HTTP MCP server 的最小客户端。

    连接时做 initialize → notifications/initialized → tools/list，把工具转换成
    OpenAI function 定义；调用时走 tools/call，通过 `Session.http` 传输。
    """

    def __init__(self, session, name: str, url: str):
        self.session = session
        self.name = name
        self.url = url
        self.session_id = ""
        self.protocol = ""
        self.tools = []
        self._names = {}  # 暴露给模型的工具名 -> MCP 原始工具名
        self._seq = 0

    async def _post(self, payload, notify=False):
        """POST 一条 JSON-RPC 消息，返回解析后的响应（通知返回 None）。"""
        self._seq += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        reply = await self.session.http(
            self.url,
            method="POST",
            headers=headers,
            body=json.dumps(payload).encode(),
            timeout_sec=120,
        )
        for k, v in reply.get("headers", {}).items():
            if k.lower() == "mcp-session-id":
                self.session_id = v
        raw = reply.get("body") or b""
        if notify or not raw:
            return None
        text = raw.decode("utf-8", "replace")
        if "event-stream" in json.dumps(reply.get("headers", {})).lower():
            # SSE：取最后一个带 JSON 的 data 行
            data = [ln[5:].strip() for ln in text.splitlines()
                    if ln.startswith("data:")]
            if not data:
                return None
            text = data[-1]
        try:
            parsed = json.loads(text)
        except ValueError:
            raise taskbridge.TaskError(
                f"mcp {self.name}: HTTP {reply.get('status')} non-JSON reply:"
                f" {text[:200]}"
            ) from None
        if not isinstance(parsed, dict):
            raise taskbridge.TaskError(
                f"mcp {self.name}: unexpected JSON-RPC reply"
            )
        return parsed

    async def _rpc(self, method, params=None, notify=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if not notify:
            payload["id"] = self._seq
        if params is not None:
            payload["params"] = params
        reply = await self._post(payload, notify=notify)
        if not reply:
            return None
        if "error" in reply:
            err = reply["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise taskbridge.TaskError(f"mcp {self.name}: {message}")
        return reply.get("result")

    async def connect(self):
        """完成握手并返回暴露给模型的工具定义列表。"""
        init = await self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "my-harness", "version": "1"},
        })
        self.protocol = (init or {}).get("protocolVersion", "")
        await self._rpc("notifications/initialized", notify=True)
        listed = await self._rpc("tools/list") or {}
        self.tools = []
        for spec in listed.get("tools") or []:
            original = spec.get("name") or ""
            if not original:
                continue
            exposed = f"{self.name}__{original}"
            if len(exposed) > 60:  # OpenAI 工具名上限 64
                exposed = exposed[:50] + "_" + format(
                    abs(hash(exposed)) % 10**8, "08d")
            self._names[exposed] = original
            self.tools.append({
                "type": "function",
                "function": {
                    "name": exposed,
                    "description": (spec.get("description") or "")[:1000],
                    "parameters": spec.get("inputSchema")
                    or {"type": "object", "properties": {}},
                },
            })
        return self.tools

    async def call(self, exposed: str, args) -> str:
        """调用一个 MCP 工具并把内容块拼成文本。"""
        result = await self._rpc("tools/call", {
            "name": self._names[exposed],
            "arguments": args,
        }) or {}
        parts = []
        for block in result.get("content") or []:
            if block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif block.get("type") == "image":
                parts.append(f"[image {block.get('mimeType')}]")
            else:
                parts.append(f"[{block.get('type')} content]")
        body = "\n".join(p for p in parts if p) or "(no content)"
        if result.get("isError"):
            return f"error: {body}"
        return body


async def connect_mcp(session):
    """连接任务声明的所有 MCP server；失败的 server 记日志后跳过。"""
    servers = []
    for spec in session.mcp_servers:
        name = str(spec.get("name") or "")
        url = str(spec.get("url") or "")
        if not name or not url:
            continue
        server = Mcp(session, name, url)
        try:
            tools = await server.connect()
        except Exception as exc:  # noqa: BLE001
            await session.log(f"mcp {name}: connect failed ({str(exc)[:200]})")
            continue
        await session.log(f"mcp {name}: {len(tools)} tools")
        servers.append(server)
    return servers


def clip(text):
  """Truncates `text` in the middle if it exceeds `RESULT_CHARS` characters.

  Args:
    text: Tool output string to clip.

  Returns:
    The original string if within `RESULT_CHARS`, or a middle-truncated string.
  """
  if len(text) <= RESULT_CHARS:
    return text
  half = RESULT_CHARS // 2
  return (
      f"{text[:half]}\n[... {len(text) - RESULT_CHARS} characters cut"
      f" ...]\n{text[-half:]}"
  )


def marked(messages):
  """Returns the messages a model call sends.

  For Claude, this is a copy whose system prompt and newest message carry
  `cache_control`. The stored conversation stays as it is, so each turn marks
  its own newest message.

  Args:
    messages: The conversation so far, in OpenAI chat format.

  Returns:
    `messages` itself for other models, or the marked copy for Claude.
  """
  if not CACHE_MARK:
    return messages
  out = list(messages)
  for i in {0, len(out) - 1}:
    m, content = out[i], out[i].get("content")
    if isinstance(content, str) and content:
      out[i] = {
          **m,
          "content": [{
              "type": "text",
              "text": content,
              "cache_control": {"type": "ephemeral"},
          }],
      }
    else:
      out[i] = {**m, "cache_control": {"type": "ephemeral"}}
  return out


def trimmed(messages):
  """Returns the slice of history a model call sends.

  Long tasks grow past what the model accepts and drive up cost, so only the
  task statement, the newest turns, and a note about the omitted work are sent.
  Files the omitted steps wrote stay on disk, so the note is enough to recover
  the state. Tool results are never separated from their tool call.

  Args:
    messages: The conversation so far, in OpenAI chat format.

  Returns:
    The messages to send, always starting with the system prompt.
  """
  keep = CONTEXT_KEEP
  if len(messages) <= keep + 2:
    return messages
  head, tail = messages[:2], messages[-keep:]
  while tail and tail[0].get("role") == "tool":
    tail.pop(0)
  omitted = len(messages) - len(head) - len(tail)
  note = {
      "role": "user",
      "content": (
          f"[{omitted} earlier tool calls and results are omitted to save "
          "context. The files they wrote are still on disk; read them again "
          "when you need their contents.]"
      ),
  }
  return head + [note] + tail


async def run_tool(session, fn, mcp=None):
  """Executes a single tool call in the task container and returns its output.

  Rewrites `fn["arguments"]` as canonical JSON (or `"{}"` if invalid) so the
  conversation history remains valid for strict endpoints. Any tool failure is
  returned as an error string for the model. Calls naming a task MCP tool are
  dispatched to that server.

  Args:
    session: Active `taskbridge.Session` connected to the task container.
    fn: Function-call dictionary containing `name` and `arguments`.
    mcp: Connected `Mcp` servers for this task (may be empty).

  Returns:
    The clipped tool output or error string to send back to the model.
  """
  name = fn["name"]
  try:
    args = json.loads(fn["arguments"] or "{}")
    if not isinstance(args, dict):
      raise TypeError("not a JSON object")
    fn["arguments"] = json.dumps(args, allow_nan=False)
  except (TypeError, ValueError) as exc:
    fn["arguments"] = "{}"
    return (
        f"error: the arguments are not a JSON object ({exc}); send the call"
        " again"
    )
  try:
    if name == "bash":
      result = await session.exec(args["command"])
      return clip(f"exit code {result['exit_code']}\n{result['output']}")
    if name == "read_file":
      return clip(
          (await session.read_file(args["path"])).decode("utf-8", "replace")
      )
    if name == "write_file":
      return (
          f"wrote {await session.write_file(args['path'], args['content'])}"
          f" bytes to {args['path']}"
      )
    for server in mcp or ():
      if name in server._names:
        return clip(await server.call(name, args))
    return f"error: there is no tool named {name}"
  # ValueError: content with an unpaired surrogate
  except (taskbridge.TaskError, KeyError, ValueError) as exc:
    return f"error: {type(exc).__name__}: {exc}"


async def recover(session, messages, exc, waits, until):
  """Handles a failed model call and returns whether to retry.

  On a 400 context-overflow error, shortens the oldest tool results. On a rate
  limit, server error, or connection drop, sleeps for the next interval in
  `RETRY_WAITS` (capped at the step's wrap-up deadline). Errors are logged
  rather than added to the conversation.

  Args:
    session: Active `taskbridge.Session` for the task.
    messages: The conversation, shortened in place when the context is full.
    exc: The `openai.APIError` the call raised.
    waits: Iterator over the remaining intervals in `RETRY_WAITS`.
    until: Seconds before the time limit at which the step wraps up.

  Returns:
    `True` to retry the call, `False` to re-raise.
  """
  status = getattr(exc, "status_code", None)  # None: no HTTP answer
  if status == 400 and CONTEXT_FULL.search(str(exc)):
    return await shorten(session, messages)
  wait = next(waits, None)
  if wait is None or not (
      status is None or status in (408, 409, 429) or status >= 500
  ):
    return False
  left = session.time_left()
  if left is not None and left > until:
    wait = min(wait, left - until)
  await session.log(
      f"model call failed ({str(exc)[:200]}); again in {wait:.0f} s"
  )
  await asyncio.sleep(wait)
  return True


async def shorten(session, messages):
  """Truncates the older half of long tool results to `CUT_KEEP` characters.

  Repeated calls truncate progressively newer results. Claude's thinking blocks
  are kept intact because each block's signature is self-contained and Claude
  rejects tool loops if the latest assistant turn loses its thinking block.

  Args:
    session: Active `taskbridge.Session` for the task.
    messages: The conversation, modified in place.

  Returns:
    Whether any tool result was truncated.
  """
  long = [
      n
      for n, m in enumerate(messages)
      if m["role"] == "tool" and len(m["content"]) > 2 * CUT_KEEP
  ]
  if not long:
    return False
  cut = long[: max(1, len(long) // 2)]
  for n in cut:
    messages[n]["content"] = (
        messages[n]["content"][:CUT_KEEP]
        + "\n[... cut to save context; run the tool again if needed]"
    )
  await session.log(f"context full: cut {len(cut)} old tool results")
  return True


def conversation(system, session, prompt):
  """Creates the initial `[system, user]` message list for a role.

  Args:
    system: System prompt template containing `{workdir}`.
    session: Active `taskbridge.Session` providing `workdir`.
    prompt: Initial user message content.

  Returns:
    A two-element list of OpenAI chat message dictionaries.
  """
  return [
      {"role": "system", "content": system.format(workdir=session.workdir)},
      {"role": "user", "content": prompt},
  ]


async def agent(session, messages, tools, until, final=False, mcp=None):
  """Runs the tool-calling loop on `messages` until the model answers.

  Prompts the model to wrap up immediately once fewer than `until` seconds
  remain on the task clock. When `final` is `True`, updates
  `session.final_message` with each non-empty response.

  Args:
    session: Active `taskbridge.Session` for the task.
    messages: Mutable conversation history list.
    tools: List of OpenAI tool definitions available to this role.
    until: Remaining task time threshold (in seconds) at which this step wraps
      up.
    final: Whether to record responses in `session.final_message`.
    mcp: Connected task MCP servers whose tools `tools` includes.

  Returns:
    The final text response produced by this agent step.
  """
  # head: the start of an answer cut off at the output limit
  nudges, head, waits = 0, "", iter(RETRY_WAITS)
  cleaned = False
  while True:
    left = session.time_left()  # None when the task has no time limit
    wrap_up = left is not None and left < until
    if wrap_up and messages[-1:] != [WRAP_UP]:  # asked once, also on a retry
      messages.append(dict(WRAP_UP))
    # A call still running when the wrap-up starts is stopped. The wrap-up call
    # itself gets at most WRAP_UP_SEC and stops at the time limit; if it takes
    # longer, the step returns head, its answer so far.
    if left is None:
      timeout = MAX_CALL_SEC
    elif wrap_up:
      timeout = min(WRAP_UP_SEC, left)
    else:
      timeout = min(left - until, MAX_CALL_SEC)
    try:
      extra = {"reasoning_effort": EFFORT} if EFFORT else {}
      started = time.time()
      wire = trimmed(messages)
      log(f"model call: {len(messages)} msgs ({len(wire)} sent), {len(tools)} tools, timeout={timeout}")
      reply = await asyncio.wait_for(
          client.chat.completions.create(
              model=MODEL,
              messages=marked(wire),
              tools=tools,
              tool_choice="none" if wrap_up else "auto",
              max_completion_tokens=MAX_OUTPUT_TOKENS,
              **extra,
          ),
          timeout,
      )
      usage = reply.usage
      log(
          f"model reply in {time.time() - started:.1f}s, "
          f"in={getattr(usage, 'prompt_tokens', 0)} "
          f"out={getattr(usage, 'completion_tokens', 0)}"
      )
    except asyncio.TimeoutError:
      log(f"model call timed out after {timeout:.0f}s, retrying")
      if wrap_up:
        return head
      continue
    except openai.APIError as exc:
      log(
          f"api error: {type(exc).__name__} "
          f"status={getattr(exc, 'status_code', None)} "
          f"body={str(getattr(exc, 'body', None))[:500]}"
      )
      if getattr(exc, "status_code", None) == 400:
        # The container dies with the trial, so keep the request in the task
        # workspace where harbor collects it as an artifact.
        try:
          await session.write_file(
              "/filesystem/ple-debug-400.json",
              json.dumps({"model": MODEL, "tools": tools, "messages": marked(messages)},
                         ensure_ascii=False),
          )
          log("request written to /filesystem/ple-debug-400.json")
        except Exception as err:
          log(f"dump failed: {type(err).__name__}: {err}")
        for msg in messages[-2:]:
          log(f"last {msg.get('role')}: {json.dumps(msg, ensure_ascii=False)[:4000]}")
        if not cleaned:
          # Ark rejects some histories that echo back its thinking tokens; the
          # text of each turn is enough to carry on without them.
          cleaned = True
          for msg in messages:
            msg.pop("reasoning_content", None)
            msg.pop("encrypted_content", None)
          log("retrying without reasoning fields")
          continue
      if await recover(session, messages, exc, waits, until):
        continue
      raise
    waits = iter(RETRY_WAITS)
    if reply.usage:
      details = getattr(reply.usage, "prompt_tokens_details", None)
      await session.usage(
          MODEL,
          reply.usage.prompt_tokens,
          reply.usage.completion_tokens,
          getattr(details, "cached_tokens", 0) or 0,
      )
    message, cut = (
        reply.choices[0].message,
        reply.choices[0].finish_reason == "length",
    )
    text = head + (message.content or "")
    if final and text:
      session.final_message = text
    # sent back as returned: Gemini refuses a tool call without its thought
    # signature
    turn = message.model_dump(exclude_none=True)
    if wrap_up or not message.tool_calls:
      turn.pop("tool_calls", None)  # calls made at the wrap-up are not run
      if message.content:
        # a fix round, or the request to go on after a cut-off reply, continues
        # from this answer
        messages.append(turn)
      if wrap_up or (message.content and not cut) or nudges == MAX_NUDGES:
        return text
      nudges, head = nudges + 1, text
      messages.append({
          "role": "user",
          "content": (
              "Your reply was cut off; continue where it stopped."
              if cut
              else "Continue, and finish with your answer."
          ),
      })
      continue
    nudges, head = 0, ""
    messages.append(turn)
    for call in turn["tool_calls"]:
      log(f"tool {call['function']['name']} {call['function']['arguments'][:120]}")
      await session.log(
          f"{call['function']['name']} {call['function']['arguments'][:200]}"
      )
      content = await run_tool(session, call["function"], mcp)
      messages.append(
          {"role": "tool", "tool_call_id": call["id"], "content": content}
      )
    if left is not None:
      messages[-1]["content"] += (
          f"\n[{int((session.time_left() - until) // 60)} minutes left for this"
          " step]"
      )


async def solve(session):
  """Executes the planner, worker, and verifier loop for `session`.

  Args:
    session: Active `taskbridge.Session` for the task.

  Returns:
    The final summary message from the worker.
  """
  total = session.time_left()

  def until(share):
    """Computes the remaining seconds when `share` of total task time is left.

    Args:
      share: Fraction of total task time remaining (`0.0` to `1.0`).

    Returns:
      Remaining seconds threshold, or `0` if the task has no time limit.
    """
    return 0 if total is None else total * share

  def time_for(wrap_up):
    """Checks whether at least `MIN_STEP_SEC` remains before `wrap_up`.

    Args:
      wrap_up: Remaining seconds threshold at which the next step wraps up.

    Returns:
      `True` if there is no deadline or at least `MIN_STEP_SEC` before
      `wrap_up`.
    """
    left = session.time_left()
    return left is None or left - wrap_up >= MIN_STEP_SEC

  task = session.instruction
  log(f"task received: {len(task)} chars, time_left={total}s")
  mcp = await connect_mcp(session)
  extra = [t for server in mcp for t in server.tools]
  log(f"mcp tools: {len(extra)}")
  plan = await agent(
      session,
      conversation(PLANNER, session, task),
      READ_ONLY + extra,
      until(1 - PLAN_SHARE),
      mcp=mcp,
  )
  log(f"plan done: {len(plan)} chars")
  await session.log(f"plan: {plan[:1000]}")
  work = conversation(WORKER, session, f"{task}\n\n## Plan\n{plan}")
  summary = await agent(session, work, TOOLS + extra, until(CHECK_SHARE),
                        final=True, mcp=mcp)
  log(f"worker done: {len(summary or '')} chars")
  for _ in range(MAX_FIX_ROUNDS):
    if not time_for(until(CHECK_SHARE / 2)):
      break
    review = (
        f"## Task\n{task}\n\n## Plan\n{plan}\n\n## The engineer's"
        f" summary\n{summary}"
    )
    verdict = await agent(
        session,
        conversation(VERIFIER, session, review),
        READ_ONLY + extra,
        until(CHECK_SHARE / 2),
        mcp=mcp,
    )
    await session.log(f"verifier: {verdict[:1000]}")
    # PASS alone in any letter case (Markdown emphasis and a full stop aside),
    # or an empty reply, names no gaps
    if verdict.strip("*_. \r\n\t").upper() in ("", "PASS") or not time_for(
        WRAP_UP_SEC
    ):
      break
    work.append({
        "role": "user",
        "content": (
            "A reviewer checked your files and found these"
            f" gaps:\n{verdict}\n\nFix them, then reply with your updated"
            " summary."
        ),
    })
    summary = (
        await agent(session, work, TOOLS + extra, WRAP_UP_SEC, final=True, mcp=mcp)
        or summary
    )
  return summary or session.final_message


if __name__ == "__main__":
  taskbridge.run(solve)
