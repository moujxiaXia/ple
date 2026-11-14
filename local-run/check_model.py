"""最小凭证验证：直接调用一次 chat.completions，确认 base_url / model / key 三者匹配。"""
from __future__ import annotations

import os
import pathlib
import sys

import openai

ENV_PATH = pathlib.Path(__file__).resolve().parent / ".env"


def load_env(path: pathlib.Path) -> None:
    if not path.is_file():
        sys.exit(f".env not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def mask(s: str) -> str:
    if not s:
        return "<empty>"
    return s[:6] + "..." + s[-4:] if len(s) > 12 else s[:2] + "..."


load_env(ENV_PATH)

base_url = os.environ.get("MODEL_BASE_URL", "")
api_key = os.environ.get("MODEL_API_KEY", "")
model = os.environ.get("MODEL_NAME", "")

print("配置：")
print(f"  base_url = {base_url}")
print(f"  model    = {model}")
print(f"  api_key  = {mask(api_key)}")
print()

if not base_url or not api_key or not model:
    sys.exit("缺少必填配置")

client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=120)

print("→ 发送 chat.completions ...")
try:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Reply with exactly: PLE_OK"},
        ],
        max_tokens=64,
        temperature=0,
    )
except openai.APIStatusError as exc:
    print(f"✗ HTTP {exc.status_code}")
    body = getattr(exc, "response", None)
    if body is not None:
        print(f"  body: {body.text[:1500]}")
    sys.exit(1)
except Exception as exc:  # noqa: BLE001
    print(f"✗ {type(exc).__name__}: {exc}")
    sys.exit(1)

text = (resp.choices[0].message.content or "").strip()
print("✓ 调用成功")
print(f"  reply     = {text!r}")
print(f"  finish    = {resp.choices[0].finish_reason}")
print(f"  usage     = prompt={resp.usage.prompt_tokens} "
      f"completion={resp.usage.completion_tokens}")
print(f"  resp.model= {resp.model}")
