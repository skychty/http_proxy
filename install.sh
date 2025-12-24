#!/bin/bash
# HTTPS代理服务安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="https-proxy"
SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME.service"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_FILE="$SCRIPT_DIR/https-proxy.sh"

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo "错误: 请使用root权限运行此脚本"
    exit 1
fi

echo "=========================================="
echo "HTTPS代理服务安装脚本"
echo "=========================================="
echo ""

# 检查服务文件是否存在
if [ ! -f "$SERVICE_FILE" ]; then
    echo "错误: 服务文件不存在: $SERVICE_FILE"
    exit 1
fi

# 检查脚本文件是否存在
if [ ! -f "$SCRIPT_FILE" ]; then
    echo "错误: 启停脚本不存在: $SCRIPT_FILE"
    exit 1
fi

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3，请先安装Python3"
    exit 1
fi

# 检查服务脚本是否存在
if [ ! -f "$SCRIPT_DIR/server.py" ]; then
    echo "错误: 服务脚本不存在: $SCRIPT_DIR/server.py"
    exit 1
fi

echo "1. 复制服务文件到系统目录..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_NAME.service"

# 更新服务文件中的路径（使用实际路径）
echo "2. 更新服务文件路径..."
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|g" "$SYSTEMD_DIR/$SERVICE_NAME.service"
sed -i "s|ExecStart=.*|ExecStart=/usr/bin/python3 $SCRIPT_DIR/server.py 443 0.0.0.0 10000 50000 100 30.0 30.0 60.0 true|g" "$SYSTEMD_DIR/$SERVICE_NAME.service"

echo "3. 设置脚本执行权限..."
chmod +x "$SCRIPT_FILE"

echo "4. 重新加载systemd..."
systemctl daemon-reload

echo "5. 启用服务（开机自启动）..."
systemctl enable "$SERVICE_NAME.service"

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""
echo "服务管理命令:"
echo "  启动服务:   systemctl start $SERVICE_NAME"
echo "  停止服务:   systemctl stop $SERVICE_NAME"
echo "  重启服务:   systemctl restart $SERVICE_NAME"
echo "  查看状态:   systemctl status $SERVICE_NAME"
echo "  查看日志:   journalctl -u $SERVICE_NAME -f"
echo ""
echo "或者使用启停脚本:"
echo "  $SCRIPT_FILE {start|stop|restart|status|logs}"
echo ""
echo "服务将在系统启动时自动启动"
echo ""

