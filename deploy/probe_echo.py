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
c = OpenAI(base_url=base, api_key=key, timeout=180, max_retries=0)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False},
    },
}]

msgs = [{"role": "user", "content": "Read /tmp/a.txt, then read /tmp/b.txt, then read /tmp/c.txt. Use the tool each time."}]
for step in range(6):
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs, tools=TOOLS,
                                      tool_choice="auto", max_completion_tokens=32000)
    except Exception as e:
        body = getattr(e, "body", None) or str(e)
        print(f"[step {step}] {type(e).__name__} {time.time()-t:.1f}s "
              f"body={json.dumps(body, ensure_ascii=False)[:500] if isinstance(body, dict) else str(body)[:500]}")
        break
    m = r.choices[0].message
    turn = m.model_dump(exclude_none=True)
    print(f"[step {step}] {time.time()-t:.1f}s keys={sorted(turn)} tools={len(m.tool_calls or [])}")
    msgs.append(turn)
    if not m.tool_calls:
        msgs.append({"role": "user", "content": "Continue: read the next file."})
        continue
    for call in turn["tool_calls"]:
        msgs.append({"role": "tool", "tool_call_id": call["id"], "content": f"content of {step}"})
