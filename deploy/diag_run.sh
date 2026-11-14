#!/usr/bin/env bash
# 分析一次评测的产出与失败原因
set -uo pipefail
A=${1:-/root/ple/results/attempt1}
echo "=== 结果目录 ==="
find "$A" -maxdepth 3 -type f | head -30
echo "=== 任务目录 ==="
T=$(find "$A/jobs/dev" -maxdepth 1 -type d -name 'lv-cable-sizing__*' | head -1)
echo "trial: $T"
ls -la "$T" 2>/dev/null | head -20
echo "=== trial.log ==="
tail -c 800 "$T/trial.log" 2>/dev/null
echo
echo "=== result.json ==="
head -c 600 "$T/result.json" 2>/dev/null
echo
echo "=== agent 产物 ==="
find "$T" -path '*artifacts*' -o -name '*.log' | head -20
echo "=== 交付目录 ==="
find "$T" -type d \( -name files -o -name deliverables \) -exec sh -c 'echo {}; ls -la {}' \; 2>/dev/null | head -20
