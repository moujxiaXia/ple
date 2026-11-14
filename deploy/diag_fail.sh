#!/usr/bin/env bash
# 查看失败细节
set -uo pipefail
T=$(find /root/ple/results/attempt1/jobs/dev -maxdepth 1 -type d -name 'lv-cable-sizing__*' | head -1)
echo "=== exception.txt ==="
cat "$T/exception.txt"
echo "=== deliverables/capture.json ==="
cat "$T/deliverables/capture.json"
echo
echo "=== 产出目录 ==="
find "$T/artifacts" -type f | head -20
echo "=== serve.log 末尾 ==="
tail -c 1200 "$T/agent/serve.log"
echo
echo "=== grade.log ==="
tail -c 600 "$T/verifier/grade.log" 2>/dev/null
