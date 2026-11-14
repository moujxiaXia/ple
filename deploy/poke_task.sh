#!/usr/bin/env bash
# 查看正在运行的任务容器内部状态
set -uo pipefail
C=$(docker ps --format '{{.Names}}' | grep 'env-main' | head -1)
if [ -z "$C" ]; then echo "no running task container"; exit 0; fi
echo "container: $C"
echo "--- /filesystem ---"
docker exec "$C" sh -c 'ls -la /filesystem | head -20'
echo "--- deliverable candidates ---"
docker exec "$C" sh -c 'find /filesystem -maxdepth 5 \( -name "*.zip" -o -name "*.md" -o -name "*.xlsx" -o -name "*.py" \) 2>/dev/null | head -15'
echo "--- touched in last 10 min ---"
docker exec "$C" sh -c 'find /filesystem -type f -newermt "-10 minutes" 2>/dev/null | head -10'
