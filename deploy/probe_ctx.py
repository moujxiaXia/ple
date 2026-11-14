import os, time
from openai import OpenAI

env = {}
for line in open("/root/ple/local.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

base, key = env["MODEL_BASE_URL"], env["MODEL_API_KEY"]
model = env.get("MODEL_NAME")
if not model:
    import re
    text = open("/root/ple/my-harness/submission.yaml", encoding="utf-8").read()
    model = re.search(r"openai-compatible/(\S+)", text).group(1)
print("base:", base, "model:", model)
c = OpenAI(base_url=base, api_key=key, timeout=120, max_retries=0)


def probe(label, words, max_tokens):
    msgs = [{"role": "user", "content": ("word " * words) + "\nReply with OK"}]
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=msgs,
                                      max_completion_tokens=max_tokens)
        u = r.usage
        print(f"[{label}] words={words} max={max_tokens} -> ok {time.time()-t:.1f}s "
              f"in={u.prompt_tokens} out={u.completion_tokens}")
    except Exception as e:
        body = getattr(e, "body", None) or getattr(e, "message", "")
        print(f"[{label}] words={words} max={max_tokens} -> {type(e).__name__} "
              f"{time.time()-t:.1f}s body={str(body)[:300]}")


probe("small-bigmax", 10, 32000)
probe("mid-bigmax", 20000, 32000)
probe("large-bigmax", 52000, 32000)
probe("large-smallmax", 52000, 4000)
