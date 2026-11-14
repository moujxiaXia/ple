#!/usr/bin/env bash
# 判断评测是在正常推理还是卡住
set -uo pipefail
echo "=== docker stats ==="
docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}'
echo "=== 到模型端点的连接 ==="
ss -tnp 2>/dev/null | grep -E 'ESTAB.*:443' | head -5
echo "=== serve 容器最近输出 ==="
S=$(docker ps --format '{{.Names}}' | grep '^plebench-serve' | head -1)
[ -n "$S" ] && docker logs --tail 15 "$S" 2>&1 | tail -15
