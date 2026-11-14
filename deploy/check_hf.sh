#!/usr/bin/env bash
# 验证 HuggingFace token 能否下载任务文件：bash check_hf.sh <dataset-file-url>
set -euo pipefail
set -a
. /root/ple/local.env
set +a
if [ -z "${HF_TOKEN:-}" ]; then
  echo "HF_TOKEN is empty in /root/ple/local.env" >&2
  exit 1
fi

echo "=== token ==="
echo "length: $(printf '%s' "${HF_TOKEN}" | wc -c)（HF read token 通常为 37）"
echo "prefix: $(printf '%s' "${HF_TOKEN}" | cut -c1-8)..."

echo "=== whoami ==="
curl -sS -m 30 -H "Authorization: Bearer ${HF_TOKEN}" \
  https://huggingface.co/api/whoami-v2 | head -c 300
echo

code=$(curl -sSL -m 60 -H "Authorization: Bearer ${HF_TOKEN}" -o /tmp/probe.out \
  -w '%{http_code}' "$1")
echo "http_code=$code"
head -c 400 /tmp/probe.out
echo
