#!/usr/bin/env bash
# 干净重启评测：停止旧进程 -> 清空结果目录 -> 后台启动
set -uo pipefail
bash /root/ple/stop_eval.sh >/dev/null 2>&1
sleep 3
rm -rf /root/ple/results
if [ -d /root/ple/results ]; then echo "results dir still exists" >&2; exit 1; fi
nohup bash /root/ple/run_eval.sh "$@" > /root/ple/run-lvcable.log 2>&1 < /dev/null &
echo "started: $*"
