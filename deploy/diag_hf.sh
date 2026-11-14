#!/usr/bin/env bash
# HF 诊断：区分 token 无效 / 权限不足 / 数据集未授权
set -uo pipefail
set -a
. /root/ple/local.env
set +a
H="Authorization: Bearer ${HF_TOKEN}"
DS="google/physical-engineerings-last-exam"

echo "=== 1. token 对普通公开仓库的读权限 ==="
curl -sSL -m 30 -H "$H" -o /dev/null -w 'bert-base config.json -> %{http_code}\n' \
  https://huggingface.co/bert-base-uncased/resolve/main/config.json

echo "=== 2. 数据集元信息（gating 类型）==="
curl -sS -m 30 -H "$H" "https://huggingface.co/api/datasets/${DS}" \
  | tr ',' '\n' | grep -E '"(gated|private|id|error)"' | head -6

echo "=== 3. 数据集文件列表（带 token）==="
curl -sS -m 30 -H "$H" -o /dev/null -w 'tree -> %{http_code}\n' \
  "https://huggingface.co/api/datasets/${DS}/tree/main"

echo "=== 4. 单个小文件下载（带 token）==="
curl -sSL -m 30 -H "$H" -o /dev/null -w 'resolve -> %{http_code}\n' \
  "https://huggingface.co/datasets/${DS}/resolve/main/tasks/lv-cable-sizing/task.toml"
