import os, re, json, time
from openai import OpenAI

env = {}
for line in open("/root/ple/local.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
base, key = env["MODEL_BASE_URL"], env["MODEL_API_KEY"]
model = re.search(r"openai-compatible/(\S+)",
                  open("/root/ple/my-harness/submission.yaml", encoding="utf-8").read()).group(1)
c = OpenAI(base_url=base, api_key=key, timeout=120, max_retries=0)


def probe(label, msgs):
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs, max_completion_tokens=512)
        d = r.choices[0].message.model_dump(exclude_none=True)
        print(f"[{label}] ok {time.time()-t:.1f}s reply_keys={sorted(d)}")
    except Exception as e:
        body = getattr(e, "body", None) or str(e)
        print(f"[{label}] {type(e).__name__} {time.time()-t:.1f}s "
              f"body={json.dumps(body, ensure_ascii=False)[:400] if isinstance(body, dict) else str(body)[:400]}")


probe("plain", [{"role": "user", "content": "Reply OK"}])

probe("echo-reasoning", [
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4", "reasoning_content": "The user asks a simple sum."},
    {"role": "user", "content": "Reply OK"},
])

probe("echo-empty-content-toolcall", [
    {"role": "user", "content": "Read /tmp/a.txt"},
    {"role": "assistant", "content": "", "tool_calls": [{
        "id": "call_1", "type": "function",
        "function": {"name": "read_file", "arguments": "{\"path\": \"/tmp/a.txt\"}"}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    {"role": "user", "content": "Reply OK"},
])
