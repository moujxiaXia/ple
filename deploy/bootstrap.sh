#!/usr/bin/env bash
# 新加坡 ECS 初始化：安装 Docker 与 uv，并做最小验证。
# 用法（在服务器上）：bash bootstrap.sh
set -euo pipefail

echo "=== 基础信息 ==="
uname -m
cat /etc/os-release | head -3
nproc
free -g | head -2
df -h / | tail -1

if [ "$(uname -m)" != "x86_64" ]; then
  echo "!! 需要 x86_64，当前为 $(uname -m)，终止" >&2
  exit 1
fi

AVAIL_GB=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
MIN_GB="${MIN_FREE_GB:-30}"
echo "=== 根分区可用: ${AVAIL_GB}G（门槛 ${MIN_GB}G）==="
if [ "${AVAIL_GB}" -lt "${MIN_GB}" ]; then
  echo "!! 可用磁盘不足 ${MIN_GB}G，无法拉取任务镜像，终止" >&2
  exit 1
fi

echo "=== 安装 Docker ==="
if ! command -v docker >/dev/null 2>&1; then
  dnf install -y dnf-plugins-core
  dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker --version
docker info --format 'server={{.ServerVersion}} driver={{.Driver}} cgroup={{.CgroupVersion}}'

echo "=== 安装 uv ==="
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo "=== 验证 ==="
docker run --rm hello-world
echo "=== bootstrap done ==="
