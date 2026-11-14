#!/usr/bin/env bash
# 列出已缓存任务的 CPU / 内存声明，并与宿主机对比
set -uo pipefail
ROOT=$(ls -d /root/.cache/plebench/tasks/*/tasks 2>/dev/null | head -1)
echo "tasks dir: ${ROOT:-not found}"
echo "host cpus: $(nproc), mem: $(free -m | awk '/^Mem:/{print $2}') MB"
echo
printf '%-40s %-6s %s\n' TASK CPUS MEM_MB
for d in "$ROOT"/*/; do
  [ -f "$d/task.toml" ] || continue
  name=$(basename "$d")
  cpus=$(grep -E '^[[:space:]]*cpus[[:space:]]*=' "$d/task.toml" | head -1 | grep -oE '[0-9.]+')
  mem=$(grep -E '^[[:space:]]*memory_mb[[:space:]]*=' "$d/task.toml" | head -1 | grep -oE '[0-9]+')
  printf '%-40s %-6s %s\n' "$name" "${cpus:-2}" "${mem:-4096}"
done
