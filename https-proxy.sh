#!/bin/bash
# HTTPS代理服务启停脚本

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD="python3"
SERVER_SCRIPT="$SCRIPT_DIR/server.py"
PID_FILE="/var/run/https-proxy.pid"
LOG_FILE="/var/log/https-proxy.log"

# 服务配置参数（可根据需要修改）
HOST="0.0.0.0"
PORT="8888"
MAX_CONNECTIONS="10000"
QUEUE_SIZE="50000"
WORKER_THREADS="100"
QUEUE_TIMEOUT="30.0"
REQUEST_TIMEOUT="30.0"
KEEPALIVE_TIMEOUT="60.0"
CLOSE_AFTER_RESPONSE="true"

# 检查Python是否安装
check_python() {
    if ! command -v $PYTHON_CMD &> /dev/null; then
        echo "错误: 未找到 $PYTHON_CMD，请先安装Python3"
        exit 1
    fi
}

# 检查服务脚本是否存在
check_script() {
    if [ ! -f "$SERVER_SCRIPT" ]; then
        echo "错误: 服务脚本不存在: $SERVER_SCRIPT"
        exit 1
    fi
}

# 启动服务
start() {
    check_python
    check_script
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "服务已在运行中 (PID: $PID)"
            exit 1
        else
            echo "清理旧的PID文件"
            rm -f "$PID_FILE"
        fi
    fi
    
    echo "正在启动HTTPS代理服务..."
    
    # 创建日志目录（如果不存在）
    mkdir -p "$(dirname "$LOG_FILE")"
    
    # 启动服务（后台运行）
    nohup $PYTHON_CMD "$SERVER_SCRIPT" \
        "$PORT" \
        "$HOST" \
        "$MAX_CONNECTIONS" \
        "$QUEUE_SIZE" \
        "$WORKER_THREADS" \
        "$QUEUE_TIMEOUT" \
        "$REQUEST_TIMEOUT" \
        "$KEEPALIVE_TIMEOUT" \
        "$CLOSE_AFTER_RESPONSE" \
        >> "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    
    # 等待一下，检查是否启动成功
    sleep 2
    if ps -p $PID > /dev/null 2>&1; then
        echo "服务启动成功 (PID: $PID)"
        echo "日志文件: $LOG_FILE"
    else
        echo "服务启动失败，请查看日志: $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# 停止服务
stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "服务未运行（PID文件不存在）"
        exit 1
    fi
    
    PID=$(cat "$PID_FILE")
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "服务未运行（进程不存在）"
        rm -f "$PID_FILE"
        exit 1
    fi
    
    echo "正在停止HTTPS代理服务 (PID: $PID)..."
    kill $PID
    
    # 等待进程结束
    for i in {1..10}; do
        if ! ps -p $PID > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    
    # 如果还在运行，强制杀死
    if ps -p $PID > /dev/null 2>&1; then
        echo "强制停止服务..."
        kill -9 $PID
        sleep 1
    fi
    
    rm -f "$PID_FILE"
    echo "服务已停止"
}

# 重启服务
restart() {
    stop
    sleep 1
    start
}

# 查看服务状态
status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "服务未运行"
        exit 1
    fi
    
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "服务正在运行 (PID: $PID)"
        echo "监听端口: $PORT"
        echo "日志文件: $LOG_FILE"
        
        # 显示进程信息
        ps -p $PID -o pid,ppid,cmd,%mem,%cpu,etime
    else
        echo "服务未运行（进程不存在）"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# 查看日志
logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "日志文件不存在: $LOG_FILE"
        exit 1
    fi
}

# 主函数
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "命令说明:"
        echo "  start   - 启动服务"
        echo "  stop    - 停止服务"
        echo "  restart - 重启服务"
        echo "  status  - 查看服务状态"
        echo "  logs    - 查看日志（实时）"
        exit 1
        ;;
esac

exit 0

