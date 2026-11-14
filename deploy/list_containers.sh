#!/usr/bin/env bash
# 列出所有评测相关容器及其最后若干行日志
set -uo pipefail
docker ps --format '{{.Names}}	{{.Status}}'
for c in $(docker ps --format '{{.Names}}' | grep serve); do
  echo "-- $c"
  docker logs --tail "${1:-3}" "$c" 2>&1
done
