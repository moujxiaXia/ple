#!/usr/bin/env bash
# 配额重置后自动开跑：先移除自身 cron 条目，再启动评测
set -uo pipefail
crontab -l 2>/dev/null | grep -v 'auto_start.sh' | crontab -
echo "$(date '+%F %T') auto start triggered" >> /root/ple/auto_start.log
bash /root/ple/start_eval.sh lv-cable-sizing --rebuild >> /root/ple/auto_start.log 2>&1
