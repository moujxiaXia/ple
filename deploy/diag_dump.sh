#!/usr/bin/env bash
# 查找 400 取证文件与相关日志
set -uo pipefail
T=$(find /root/ple/results/attempt1/jobs/dev -maxdepth 1 -type d -name 'lv-cable-sizing__*' | head -1)
echo "trial: $T"
echo "=== 取证相关日志 ==="
grep -E 'written to|dump failed|api error|last ' "$T/agent/serve.log" 2>/dev/null | tail -8
echo "=== artifacts 文件 ==="
find "$T/artifacts" -type f 2>/dev/null | head -15
echo "=== manifest ==="
head -c 600 "$T/artifacts/manifest.json" 2>/dev/null
echo
echo "=== 任务工作区里的 debug 文件 ==="
find "$T" -name 'ple-debug*' 2>/dev/null
