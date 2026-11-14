"""启动 harness：加载 local-run/.env 后执行 my-harness/serve.py。

用法：
  python local-run/run_harness.py
  python local-run/run_harness.py --port 8765
"""

from __future__ import annotations

import os
import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ENV_PATH = HERE / ".env"


def load_env(path: pathlib.Path) -> None:
    if not path.is_file():
        sys.exit(f".env not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            os.environ[k] = v  # .env 优先，便于本地覆盖


load_env(ENV_PATH)
os.environ.setdefault("PORT", "8765")

required = ["MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME"]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    sys.exit(f"缺少环境变量: {', '.join(missing)}")

print(f"[run_harness] model={os.environ['MODEL_NAME']} "
      f"base_url={os.environ['MODEL_BASE_URL']} port={os.environ['PORT']}",
      flush=True)

harness_dir = ROOT / "my-harness"
sys.path.insert(0, str(harness_dir))
sys.argv = ["serve.py"]
runpy.run_path(str(harness_dir / "serve.py"), run_name="__main__")
