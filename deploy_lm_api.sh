#!/bin/bash
# LM Studio 远程 API 服务部署脚本
# 在 ham.vlsc.net 上执行

set -e

echo "=========================================="
echo "LM Studio 远程 API 服务部署"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否在 ham.vlsc.net 上
HOSTNAME=$(hostname -f 2>/dev/null || hostname)
if [[ "$HOSTNAME" != *"ham.vlsc.net"* ]] && [[ "$1" != "--force" ]]; then
    echo -e "${RED}错误: 此脚本应在 ham.vlsc.net 上运行${NC}"
    echo "当前主机: $HOSTNAME"
    echo "使用 --force 强制继续"
    exit 1
fi

# 检查依赖
echo -e "\n${YELLOW}[1/6] 检查依赖...${NC}"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 python3${NC}"
    exit 1
fi

# 检查 pip
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 pip3${NC}"
    exit 1
fi

# 检查 LM Studio 是否在运行
echo -e "\n${YELLOW}[2/6] 检查 LM Studio...${NC}"
if ! curl -s http://localhost:1234/v1/models &> /dev/null; then
    echo -e "${RED}警告: LM Studio 似乎没有在 localhost:1234 运行${NC}"
    echo "请确保:"
    echo "  1. LM Studio 已启动"
    echo "  2. 已加载模型"
    echo "  3. 服务器模式已开启 (端口 1234)"
    read -p "是否继续? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}LM Studio 运行正常${NC}"
fi

# 安装 Python 依赖
echo -e "\n${YELLOW}[3/6] 安装 Python 依赖...${NC}"
pip3 install --user flask flask-cors requests 2>/dev/null || pip3 install flask flask-cors requests

# 创建服务目录
echo -e "\n${YELLOW}[4/6] 创建服务目录...${NC}"
INSTALL_DIR="$HOME/lm_api_server"
mkdir -p "$INSTALL_DIR"
mkdir -p "$HOME/logs"

# 复制服务文件
echo -e "\n${YELLOW}[5/6] 安装服务文件...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/lm_api_server.py" ]; then
    cp "$SCRIPT_DIR/lm_api_server.py" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/lm_api_server.py"
else
    echo -e "${RED}错误: 未找到 lm_api_server.py${NC}"
    exit 1
fi

# 创建 systemd 服务文件 (如果系统是 systemd)
if command -v systemctl &> /dev/null; then
    echo "创建 systemd 服务..."
    SERVICE_FILE="/tmp/lm-api-server.service"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=LM Studio Remote API Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$HOME/.local/bin/python3 $INSTALL_DIR/lm_api_server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    echo -e "${GREEN}systemd 服务文件已创建: $SERVICE_FILE${NC}"
    echo "安装命令 (需要 root):"
    echo "  sudo cp $SERVICE_FILE /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable lm-api-server"
    echo "  sudo systemctl start lm-api-server"
fi

# 创建启动脚本
cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
nohup python3 lm_api_server.py > "$HOME/logs/lm_api_server.log" 2>&1 &
echo $! > /tmp/lm_api_server.pid
echo "服务已启动，PID: $(cat /tmp/lm_api_server.pid)"
echo "日志: $HOME/logs/lm_api_server.log"
EOF

cat > "$INSTALL_DIR/stop.sh" << 'EOF'
#!/bin/bash
if [ -f /tmp/lm_api_server.pid ]; then
    PID=$(cat /tmp/lm_api_server.pid)
    kill $PID 2>/dev/null && echo "服务已停止 (PID: $PID)" || echo "服务未运行"
    rm -f /tmp/lm_api_server.pid
else
    echo "未找到 PID 文件"
fi
EOF

chmod +x "$INSTALL_DIR/start.sh" "$INSTALL_DIR/stop.sh"

# 初始化并启动服务
echo -e "\n${YELLOW}[6/6] 初始化服务...${NC}"
cd "$INSTALL_DIR"
python3 lm_api_server.py --generate-key default > /tmp/lm_key.txt 2>&1

# 提取密钥
API_KEY=$(grep "lm_" /tmp/lm_key.txt | head -1 | tr -d ' ')

echo -e "\n=========================================="
echo -e "${GREEN}部署完成！${NC}"
echo "=========================================="
echo ""
echo "安装目录: $INSTALL_DIR"
echo "日志目录: $HOME/logs"
echo ""
echo "API 密钥:"
echo "  $API_KEY"
echo ""
echo "启动服务:"
echo "  $INSTALL_DIR/start.sh"
echo ""
echo "停止服务:"
echo "  $INSTALL_DIR/stop.sh"
echo ""
echo "或使用 Python 直接运行:"
echo "  python3 $INSTALL_DIR/lm_api_server.py"
echo ""
echo "API 端点:"
echo "  Health:  http://$(hostname -I | awk '{print $1}'):8888/health"
echo "  Chat:    http://$(hostname -I | awk '{print $1}'):8888/v1/chat/completions"
echo ""
echo "使用示例:"
echo "  export LM_API_KEY='$API_KEY'"
echo "  export LM_API_URL='http://ham.vlsc.net:8888'"
echo "  python3 lm_remote_client.py '你好，请介绍一下自己'"
echo ""
echo "=========================================="

# 保存密钥到文件
KEY_FILE="$HOME/.lm_api_key.txt"
echo "$API_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"
echo "密钥已保存到: $KEY_FILE"
