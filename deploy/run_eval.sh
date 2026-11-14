#!/usr/bin/env bash
# 服务器端单/多任务评测包装脚本：bash run_eval.sh <task-id> [额外参数...]
set -euo pipefail
export PATH=/root/.local/bin:${PATH}
cd /root/ple/repo
exec /root/.local/bin/uv run python eval/run.py /root/ple/my-harness \
  --env-file /root/ple/local.env \
  --tasks "${1:-lv-cable-sizing}" \
  --trials 1 \
  --out /root/ple/results \
  "${@:2}"
