#!/usr/bin/env bash
# 检查 session.log 的内容是否被持久化（用于决定 400 取证方式）
set -uo pipefail
T=$(find /root/ple/results/attempt1/jobs/dev -maxdepth 1 -type d -name 'lv-cable-sizing__*' | head -1)
echo "trial: $T"
for f in "$T/trial.log" "$T/agent/serve.log" /root/ple/results/attempt1/harbor.log; do
  echo "--- $f ($(wc -c < "$f" 2>/dev/null) bytes)"
  grep -c 'plan:' "$f" 2>/dev/null || true
done
echo "=== trial.log 前 40 行 ==="
head -40 "$T/trial.log" 2>/dev/null
