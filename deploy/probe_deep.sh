#!/usr/bin/env bash
# 深入排查：harness 是否收到评测连接
set -uo pipefail
S=$(docker ps --format '{{.Names}}' | grep '^plebench-serve' | head -1)
echo "serve: $S"
echo "=== serve 容器内连接（8765 与出站）==="
docker exec "$S" sh -c 'ss -tn 2>/dev/null || netstat -tn 2>/dev/null' | head -12
echo "=== serve 环境变量（脱敏）==="
docker exec "$S" sh -c 'env | grep -E "^(MODEL_|HTTPS_PROXY|HTTP_PROXY|PORT|TASK)" | sed -E "s/(KEY=).*/\1***/"'
echo "=== trial 目录 ==="
T=$(find /root/ple/results/attempt1/jobs/dev -maxdepth 1 -type d -name 'lv-cable-sizing__*' | head -1)
echo "trial dir: $T"
ls -la "$T" 2>/dev/null
echo "=== trial result.json ==="
head -c 800 "$T/result.json" 2>/dev/null
echo
echo "=== trial.log 大小 ==="
wc -c "$T/trial.log" 2>/dev/null
