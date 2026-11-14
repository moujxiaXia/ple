#!/usr/bin/env bash
# 查看 egress 代理日志，判断 harness 是否真的发出模型请求
set -uo pipefail
E=$(docker ps --format '{{.Names}}' | grep 'egress-control-sidecar' | head -1)
echo "egress sidecar: $E"
docker logs --tail 40 "$E" 2>&1 | tail -40
echo "=== 代理进程连接数 ==="
docker exec "$E" sh -c 'cat /proc/net/tcp 2>/dev/null | wc -l'
