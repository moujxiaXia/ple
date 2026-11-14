#!/usr/bin/env bash
# 停止当前评测并清理容器
set -uo pipefail
pkill -f 'eval/run.py' 2>/dev/null || true
sleep 2
NAMES=$(docker ps --format '{{.Names}}' | grep -E 'lv-cable-sizing|plebench-serve|plebench-egress' || true)
if [ -n "$NAMES" ]; then echo "$NAMES" | xargs -r docker rm -f; fi
echo "stopped"
docker ps --format '{{.Names}}' | head -5
