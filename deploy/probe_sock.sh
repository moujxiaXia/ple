#!/usr/bin/env bash
# 看 harness 是否收到评测端的 TCP 连接
set -uo pipefail
S=$(docker ps --format '{{.Names}}' | grep '^plebench-serve' | head -1)
echo "serve: $S"
echo "=== /proc/net/tcp（本地地址 十六进制端口）==="
docker exec "$S" sh -c 'cat /proc/net/tcp; echo ---; cat /proc/net/tcp6 | head -5'
echo "=== 8765 = 0x223D ==="
echo "=== 进程状态 ==="
docker exec "$S" sh -c 'ps -o pid,stat,etime,time,cmd 2>/dev/null | head -10'
