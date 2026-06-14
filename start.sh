#!/bin/bash
# PSK Reporter 启动脚本
# 连接远程 StarRocks 数据库，获取数据、导入通联日志、启动 Web 应用

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ACTION=${1:-"all"}
DB_HOST="ham.vlsc.net"
DB_PORT="9030"
DB_USER="root"
DB_NAME="pskreporter"

show_usage() {
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  all       启动 Web + 后台拉数据 (默认，Web 立即可用)"
    echo "  fetch     仅获取 PSK Reporter 数据"
    echo "  sync      仅同步 WSJT-X/JTDX 通联日志"
    echo "  web       仅启动 Web 应用（秒启）"
    echo "  stop      停止 Web 应用 + 后台数据任务"
    echo "  db-check  检查远程数据库状态"
    echo "  db-start  远程启动 StarRocks 数据库"
    echo ""
    echo "数据库: 远程 StarRocks (ham.vlsc.net:9030)"
    echo ""
}

# 检查远程数据库是否可连接
check_remote_db() {
    echo ">>> 检查远程数据库 (${DB_HOST}:${DB_PORT})..."
    
    # 先检查网络连通性
    if ! ping -c 1 -W 3 ${DB_HOST} > /dev/null 2>&1; then
        echo "❌ 错误: 无法连接到 ${DB_HOST} (网络不可达)"
        return 1
    fi
    
    # 检查端口
    if ! nc -z ${DB_HOST} ${DB_PORT} 2>/dev/null; then
        echo "⚠️ 警告: 数据库端口 ${DB_PORT} 未开放"
        echo "   StarRocks 可能未启动，尝试远程启动..."
        return 2
    fi
    
    # 使用 Python 测试连接
    source venv/bin/activate
    python3 -c "
import mysql.connector
try:
    conn = mysql.connector.connect(
        host='${DB_HOST}', port=${DB_PORT}, user='${DB_USER}',
        password='', database='${DB_NAME}', connection_timeout=5
    )
    cursor = conn.cursor()
    cursor.execute('SELECT 1')
    conn.close()
    exit(0)
except Exception as e:
    print(f'连接错误: {e}')
    exit(1)
" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo "✅ 数据库连接正常"
        return 0
    else
        echo "❌ 数据库连接失败"
        return 1
    fi
}

# 远程启动 StarRocks
start_remote_db() {
    echo ">>> 远程启动 StarRocks 数据库..."
    
    # 检查 SSH 连接
    if ! ssh -o ConnectTimeout=5 ${DB_HOST} "echo OK" > /dev/null 2>&1; then
        echo "❌ 错误: 无法 SSH 连接到 ${DB_HOST}"
        echo "   请检查 SSH 配置和密钥"
        return 1
    fi
    
    echo "   SSH 连接正常，检查服务状态..."
    
    # 检查进程状态
    FE_RUNNING=$(ssh ${DB_HOST} "pgrep -f 'StarRocksFE' | head -1" || echo "")
    BE_RUNNING=$(ssh ${DB_HOST} "pgrep -f 'starrocks_be' | head -1" || echo "")
    
    if [ -n "$FE_RUNNING" ] && [ -n "$BE_RUNNING" ]; then
        echo "   FE 和 BE 进程已在运行"
    else
        # 启动 FE
        if [ -z "$FE_RUNNING" ]; then
            echo "   启动 StarRocks FE..."
            ssh ${DB_HOST} "cd ~/starrocks/fe && ./bin/start_fe.sh --daemon" 2>/dev/null
            sleep 5
        fi
        
        # 启动 BE
        if [ -z "$BE_RUNNING" ]; then
            echo "   启动 StarRocks BE..."
            ssh ${DB_HOST} "cd ~/starrocks/be && ./bin/start_be.sh --daemon" 2>/dev/null
            sleep 5
        fi
    fi
    
    # 等待数据库就绪
    echo "   等待数据库就绪..."
    for i in {1..30}; do
        if nc -z ${DB_HOST} ${DB_PORT} 2>/dev/null; then
            sleep 2
            echo "✅ 数据库已启动"
            return 0
        fi
        sleep 1
    done
    
    echo "❌ 数据库启动超时"
    return 1
}

stop_services() {
    echo ""
    echo ">>> 停止服务..."
    
    # 停止后台数据同步（如果有）
    if pgrep -f "pskreporter_adif.py" > /dev/null 2>&1; then
        echo "停止后台数据获取..."
        pkill -f "pskreporter_adif.py" 2>/dev/null || true
    fi
    if pgrep -f "wsjtx_log_import.py" > /dev/null 2>&1; then
        echo "停止后台日志同步..."
        pkill -f "wsjtx_log_import.py" 2>/dev/null || true
    fi
    
    # 停止 Web 应用
    if pgrep -f "web_app.py" > /dev/null; then
        echo "停止 Web 应用..."
        pkill -f "web_app.py" 2>/dev/null || true
        echo "Web 应用已停止"
    else
        echo "Web 应用未运行"
    fi
    
    echo "所有服务已停止"
}

check_venv() {
    if [ ! -d "venv" ]; then
        echo ""
        echo ">>> 创建虚拟环境..."
        python3 -m venv venv
        source venv/bin/activate
        pip install mysql-connector-python flask flask-cors requests
    else
        source venv/bin/activate
    fi
}

fetch_data() {
    echo ""
    echo ">>> 获取 PSK Reporter 数据..."
    python pskreporter_adif.py
}

sync_qso_log() {
    echo ""
    echo ">>> 同步 WSJT-X/JTDX 通联日志..."
    python wsjtx_log_import.py
}

start_web() {
    echo ""
    echo ">>> 启动 Web 应用..."
    
    # 检查是否已运行
    if pgrep -f "web_app.py" > /dev/null; then
        echo "Web 应用已在运行中"
        echo "访问地址: http://localhost:5000"
        return
    fi
    
    # 后台启动
    nohup python web_app.py > logs/web.log 2>&1 &
    sleep 2
    
    if pgrep -f "web_app.py" > /dev/null; then
        echo "Web 应用已启动"
        echo "访问地址: http://localhost:5000"
    else
        echo "Web 应用启动失败，请检查 logs/web.log"
    fi
}

# 主逻辑
case "$ACTION" in
    "fetch")
        check_venv
        fetch_data
        ;;
    "sync")
        check_venv
        sync_qso_log
        ;;
    "web")
        check_venv
        start_web
        ;;
    "stop")
        stop_services
        ;;
    "db-check")
        check_venv
        check_remote_db
        exit $?
        ;;
    "db-start")
        start_remote_db
        exit $?
        ;;
    "all"|*)
        if [ "$ACTION" != "all" ] && [ "$ACTION" != "" ]; then
            show_usage
            exit 1
        fi
        
        echo "=========================================="
        echo "  PSK Reporter 数据获取工具"
        echo "  数据库: StarRocks (ham.vlsc.net:9030)"
        echo "=========================================="
        
        check_venv
        
        # DB 检查：非阻塞，失败只警告不退出
        echo ""
        echo ">>> 检查数据库连接..."
        if ! check_remote_db; then
            echo "⚠️  数据库连接失败，Web 仍可启动但数据可能不完整"
            echo "   后台数据获取会在 DB 恢复后自动重试"
        fi
        
        # 先启动 Web（秒级响应，立即可访问）
        start_web
        
        # 然后后台异步拉数据（不阻塞 Web）
        echo ""
        echo ">>> 后台数据同步 (约需 10-60 秒)..."
        nohup bash -c "
            cd '$SCRIPT_DIR'
            source venv/bin/activate
            echo '[fetch] 开始获取 PSK Reporter 数据...' >> logs/web.log
            python pskreporter_adif.py >> logs/web.log 2>&1
            echo '[fetch] 完成' >> logs/web.log
            echo '[sync]  开始同步通联日志...' >> logs/web.log
            python wsjtx_log_import.py >> logs/web.log 2>&1
            echo '[sync]  完成' >> logs/web.log
        " > /dev/null 2>&1 &
        BG_PID=$!
        echo "   后台 PID: $BG_PID (日志: logs/web.log)"
        
        echo ""
        echo "=========================================="
        echo "  Web 已就绪 → http://localhost:5000"
        echo "  数据同步在后台进行（不影响访问）"
        echo "  数据库: ham.vlsc.net:9030 (StarRocks)"
        echo "=========================================="
        ;;
esac
