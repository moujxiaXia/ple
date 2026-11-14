import os, time, sys
from openai import OpenAI

base = os.environ.get("MODEL_BASE_URL")
key = os.environ.get("MODEL_API_KEY")
model = os.environ.get("MODEL_NAME")
print("base:", base, "model:", model, "proxy:", os.environ.get("HTTPS_PROXY"))

def call(label, **kw):
    c = OpenAI(base_url=base, api_key=key, timeout=kw.pop("timeout", 60), max_retries=0)
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, **kw)
        msg = r.choices[0].message
        print(f"[{label}] {time.time()-t:.1f}s ok content={ (msg.content or '')[:60]!r} tools={len(msg.tool_calls or [])}")
    except Exception as e:
        print(f"[{label}] {time.time()-t:.1f}s FAIL {type(e).__name__}: {str(e)[:200]}")

call("simple", messages=[{"role": "user", "content": "Reply with OK"}], timeout=45)

call("with-tools", messages=[{"role": "user", "content": "List the files in the current directory using the tool."}],
     tools=[{"type": "function", "function": {"name": "bash", "description": "run a shell command",
             "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}],
     tool_choice="auto", timeout=60)

call("with-effort", messages=[{"role": "user", "content": "Reply with OK"}],
     reasoning_effort="medium", max_completion_tokens=2048, timeout=60)
