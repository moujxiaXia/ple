#!/usr/bin/env bash
# 在 harness 容器内做最小模型调用测试（复用同一代理与凭证）
set -uo pipefail
S=$(docker ps --format '{{.Names}}' | grep '^plebench-serve' | head -1)
if [ -z "$S" ]; then echo "serve container not running"; exit 1; fi
docker exec -i "$S" /opt/harness/venv/bin/python - < /root/ple/test_model.py
