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
c = OpenAI(base_url=base, api_key=key, timeout=300, max_retries=0)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                       "required": ["command"], "additionalProperties": False},
    },
}]

HEREDOC = ("cd /filesystem/electrical__lv_cable_sizing__blind && cat > work/model_data.py <<'PY'\n"
           "import math, csv, openpyxl\n"
           "def load(path):\n"
           "    with open(path) as fh:\n"
           "        return fh.read()\n"
           "if __name__ == '__main__':\n"
           "    print(load('project/schedules/P-4210_motor_schedule.xlsx')[:80])\n"
           "PY")

def probe(label, turns, pad, max_tokens=32000):
    msgs = [{"role": "user", "content": "Analyse the project files."}]
    for i in range(turns):
        msgs.append({"role": "assistant", "content": f"step {i} " + pad,
                     "tool_calls": [{"id": f"call_{i}", "type": "function",
                                     "function": {"name": "bash",
                                                  "arguments": json.dumps({"command": HEREDOC})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "done"})
    msgs.append({"role": "user", "content": "Continue."})
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs, tools=TOOLS,
                                      tool_choice="auto", max_completion_tokens=max_tokens)
        u = r.usage
        print(f"[{label}] msgs={len(msgs)} in={u.prompt_tokens} ok {time.time()-t:.1f}s")
    except Exception as e:
        body = getattr(e, "body", None) or str(e)
        print(f"[{label}] msgs={len(msgs)} -> {type(e).__name__} {time.time()-t:.1f}s "
              f"body={json.dumps(body, ensure_ascii=False)[:400] if isinstance(body, dict) else str(body)[:400]}")


probe("heredoc-46msg", 22, "x" * 200)
probe("heredoc-85k", 22, "x" * 2500)
probe("heredoc-85k-max32k", 22, "x" * 2500, max_tokens=32000)
