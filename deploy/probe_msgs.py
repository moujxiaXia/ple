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
        "name": name,
        "description": f"the {name} tool",
        "parameters": {
            "type": "object",
            "properties": {arg: {"type": "string"} for arg in args},
            "required": list(args),
            "additionalProperties": False,
        },
    },
} for name, args in (("bash", ["cmd"]), ("read_file", ["path"]), ("write_file", ["path", "content"]))]


def build(turns, filler):
    msgs = [{"role": "system", "content": "You are an engineer. Use tools." * 20}]
    for i in range(turns):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{
            "id": f"call_{i}", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": f"/filesystem/f{i}.txt"})},
        }]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": filler})
        msgs.append({"role": "assistant", "content": f"read file {i}"})
    msgs.append({"role": "user", "content": "Continue with the analysis."})
    return msgs


def probe(label, turns, filler, max_tokens=32000):
    msgs = build(turns, filler)
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs, tools=TOOLS,
                                      tool_choice="auto", max_completion_tokens=max_tokens)
        u = r.usage
        print(f"[{label}] turns={turns} in={u.prompt_tokens} ok {time.time()-t:.1f}s")
    except Exception as e:
        body = getattr(e, "body", None) or getattr(e, "message", "")
        print(f"[{label}] turns={turns} -> {type(e).__name__} {time.time()-t:.1f}s "
              f"body={json.dumps(body, ensure_ascii=False)[:600] if isinstance(body, dict) else str(body)[:600]}")


probe("tool-history", 8, "ok")
probe("tool-history-long", 8, "line of text\n" * 400)
probe("tool-history-50k", 8, "line of text\n" * 1600)
probe("tool-history-42msg", 14, "line of text\n" * 900)
