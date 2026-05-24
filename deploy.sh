#!/bin/bash
# 部署 nature-album 到 NAS (UGREEN DX4600)
# 用法: bash deploy.sh

set -e

NAS_IP="192.168.31.233"
NAS_USER="pcwork"
NAS_PASS="Shanghai2025/"
APP_DIR="/home/pcwork/nature-album"
LOCAL_DIR="C:/Users/jason/Projects/relic-album"

echo "=== 1. 打包项目 ==="
cd "$LOCAL_DIR"
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='uploads' \
    --exclude='album/*/*' --exclude='thumbs/*/*' \
    -czf /tmp/nature-album.tar.gz .

echo "=== 2. 上传到 NAS ==="
sshpass -p "$NAS_PASS" scp /tmp/nature-album.tar.gz ${NAS_USER}@${NAS_IP}:/tmp/

echo "=== 3. 解压并构建 ==="
sshpass -p "$NAS_PASS" ssh ${NAS_USER}@${NAS_IP} << 'ENDSSH'
    set -e
    APP_DIR="/home/pcwork/nature-album"
    mkdir -p $APP_DIR
    cd $APP_DIR
    tar -xzf /tmp/nature-album.tar.gz
    mkdir -p album/relic album/animal album/plant thumbs/relic thumbs/animal thumbs/plant uploads

    echo "=== 4. Docker 构建 ==="
    docker compose build --no-cache

    echo "=== 5. 启动容器 ==="
    docker compose down 2>/dev/null || true
    docker compose up -d

    echo "=== 6. 检查状态 ==="
    sleep 3
    docker compose ps
    echo ""
    echo "部署完成: http://${NAS_IP}:8000"
ENDSSH

echo "=== 完成 ==="
