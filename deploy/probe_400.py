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
        "name": "bash",
        "description": "run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                       "required": ["command"], "additionalProperties": False},
    },
}]

CMD = ('grep -n "3-2.1\\|spare\\|Spare" /tmp/work/txt/criteria__UFC_3-520-01_Interior_Electrical_Systems_2025-01-16.txt'
       ' | head -20; echo ====; sed -n \'/3-2.1 /,/3-2.2/p\' /tmp/work/txt/criteria__UFC_3-520-01_Interior_Electrical_Systems_2025-01-16.txt | head -60')
OUT = ("exit code 0\n139:   3-2.1            Spare Capacity. ................................ 8\n"
       "148:   3-2.10           Signage................................ 13\n"
       "529:3-2.1         Spare Capacity.\n531:Provide a minimum of 15% empty space and 15% spare capacity (ampacity) for all\n"
       "535:\u00be-inch (20 mm), for every three spare circuit breakers and for every three empty pole\n"
       "positions. Round up the sum of spare breakers and empty pole positions to the nearest\n546:Not")
ENC = ("djH8L9Ivx/HLlMyty81sJ9Li335cjeglJzJY+qRAjeuM02+2lZDNWq5qKEeogmQ9wqbtJGIv7ae67a7US4vB"
       "FI3Gvbwom4A9ZoJXKi2bRJVtlCJeD/HnTeKNKStsLwX6eaIla88NNX4odDNwoWovH85drkvuyyJqzn6ajJDK6O"
       "1T8U/tTilQcclGUZL2KRkmmadFPOg=")


def turn(content="", reasoning=None, enc=None):
    msg = {"role": "assistant", "content": content, "tool_calls": [{
        "id": "call_aufy9bxgfl4wrarh1d17xo0g", "type": "function",
        "function": {"name": "bash", "arguments": json.dumps({"command": CMD})}}]}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    if enc is not None:
        msg["encrypted_content"] = enc
    return msg


def probe(label, msgs):
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs, tools=TOOLS,
                                      tool_choice="auto", max_completion_tokens=32000)
        print(f"[{label}] ok {time.time()-t:.1f}s out={r.usage.completion_tokens}")
    except Exception as e:
        body = getattr(e, "body", None) or str(e)
        print(f"[{label}] {type(e).__name__} {time.time()-t:.1f}s "
              f"body={json.dumps(body, ensure_ascii=False)[:300] if isinstance(body, dict) else str(body)[:300]}")


base_msgs = [{"role": "user", "content": "Check the criteria documents for spare capacity."}]

probe("plain-tool", base_msgs + [turn(), {"role": "tool", "tool_call_id": "call_aufy9bxgfl4wrarh1d17xo0g", "content": OUT}])

probe("with-encrypted", base_msgs + [turn("", "Good - superseded is clear.", ENC),
                                     {"role": "tool", "tool_call_id": "call_aufy9bxgfl4wrarh1d17xo0g", "content": OUT}])

probe("empty-content-only", base_msgs + [turn(""), {"role": "tool", "tool_call_id": "call_aufy9bxgfl4wrarh1d17xo0g", "content": OUT}])
