#!/bin/bash
# PSK Reporter 停止脚本
# 停止 Web 应用

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  PSK Reporter 停止服务"
echo "  数据库: 远程 StarRocks (无需停止)"
echo "=========================================="

# 停止 Web 应用
if pgrep -f "web_app.py" > /dev/null; then
    echo ""
    echo ">>> 停止 Web 应用..."
    pkill -f "web_app.py" 2>/dev/null || true
    echo "Web 应用已停止"
else
    echo ""
    echo "Web 应用未运行"
fi

echo ""
echo "=========================================="
echo "  所有本地服务已停止"
echo "  (远程 StarRocks 数据库不受影响)"
echo "=========================================="