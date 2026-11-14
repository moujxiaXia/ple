#!/usr/bin/env bash
# 打印 harness 容器日志与评测进度
set -uo pipefail
S=$(docker ps --format '{{.Names}}' | grep '^plebench-serve' | head -1)
if [ -z "$S" ]; then echo "no serve container running"; else
  echo "=== harness log ($S) ==="
  docker logs --tail "${1:-25}" "$S" 2>&1 | tail -"${1:-25}"
fi
echo "=== run log ==="
tail -c 600 /root/ple/run-lvcable.log
