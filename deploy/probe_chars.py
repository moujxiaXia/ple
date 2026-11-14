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


def probe(label, content):
    t = time.time()
    try:
        r = c.chat.completions.create(model=model,
                                      messages=[{"role": "user", "content": content}],
                                      max_completion_tokens=256)
        print(f"[{label}] ok {time.time()-t:.1f}s {r.choices[0].message.content[:30]!r}")
    except Exception as e:
        body = getattr(e, "body", None) or str(e)
        print(f"[{label}] {type(e).__name__} body={json.dumps(body, ensure_ascii=False)[:500] if isinstance(body, dict) else str(body)[:500]}")


probe("nul-byte", "hello\x00world, reply OK")
probe("control-chars", "hello\x01\x02\x1b[31mworld, reply OK")
probe("surrogate", "hello\ud83dworld, reply OK")
probe("long-nul", ("x\x00" * 5000) + " reply OK")
