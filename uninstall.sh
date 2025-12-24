#!/bin/bash
# HTTPS代理服务卸载脚本

set -e

SERVICE_NAME="https-proxy"
SYSTEMD_DIR="/etc/systemd/system"

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo "错误: 请使用root权限运行此脚本"
    exit 1
fi

echo "=========================================="
echo "HTTPS代理服务卸载脚本"
echo "=========================================="
echo ""

# 检查服务是否存在
if [ ! -f "$SYSTEMD_DIR/$SERVICE_NAME.service" ]; then
    echo "服务未安装"
    exit 0
fi

# 停止服务（如果正在运行）
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "1. 停止服务..."
    systemctl stop "$SERVICE_NAME"
fi

# 禁用服务
if systemctl is-enabled --quiet "$SERVICE_NAME"; then
    echo "2. 禁用服务..."
    systemctl disable "$SERVICE_NAME"
fi

# 删除服务文件
echo "3. 删除服务文件..."
rm -f "$SYSTEMD_DIR/$SERVICE_NAME.service"

# 重新加载systemd
echo "4. 重新加载systemd..."
systemctl daemon-reload
systemctl reset-failed

echo ""
echo "=========================================="
echo "卸载完成！"
echo "=========================================="
echo ""
echo "注意: 服务文件和数据文件未删除，如需完全删除请手动清理"
echo ""

