#!/usr/bin/env bash
# 临时把缓存任务的资源声明下调到 2 核 / 6 GB，仅用于在 2C8G 机器上验证评测管道。
# 注意：分数不代表官方结果，扩容后需还原 task.toml 重跑。
set -uo pipefail
T=$(ls -d /root/.cache/plebench/tasks/*/tasks/lv-cable-sizing 2>/dev/null | head -1)
if [ -z "${T}" ]; then
  echo "task not found in cache" >&2
  exit 1
fi
echo "task: $T"
echo "--- before ---"
grep -nE '^[[:space:]]*(cpus|memory_mb)[[:space:]]*=' "$T/task.toml"
sed -i -E 's/^([[:space:]]*cpus[[:space:]]*=[[:space:]]*).*/\1 2/' "$T/task.toml"
sed -i -E 's/^([[:space:]]*memory_mb[[:space:]]*=[[:space:]]*).*/\1 6144/' "$T/task.toml"
echo "--- after ---"
grep -nE '^[[:space:]]*(cpus|memory_mb)[[:space:]]*=' "$T/task.toml"
