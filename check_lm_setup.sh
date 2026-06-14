#!/bin/bash
# LM Studio 远程 API  setup 检查脚本
# 在 ham.vlsc.net 上运行

echo "=========================================="
echo "LM Studio 远程 API 配置检查"
echo "=========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CHECKS_PASSED=0
CHECKS_FAILED=0

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((CHECKS_PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((CHECKS_FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# 1. 检查 LM Studio 是否运行
echo -e "\n[1/6] 检查 LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    check_pass "LM Studio 正在运行 (localhost:1234)"
    MODELS=$(curl -s http://localhost:1234/v1/models | python3 -c "import json,sys; data=json.load(sys.stdin); print(', '.join([m['id'] for m in data.get('data', [])]))" 2>/dev/null)
    if [ -n "$MODELS" ]; then
        echo "  已加载模型: $MODELS"
    fi
else
    check_fail "LM Studio 未响应 (localhost:1234)"
    echo "  请确保:"
    echo "    1. LM Studio 已启动"
    echo "    2. 已加载模型"
    echo "    3. 服务器模式已开启 (端口 1234)"
fi

# 2. 检查 Python 和依赖
echo -e "\n[2/6] 检查 Python 环境..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    check_pass "Python 已安装: $PYTHON_VERSION"
else
    check_fail "未找到 Python3"
fi

# 检查 Flask
if python3 -c "import flask" 2>/dev/null; then
    check_pass "Flask 已安装"
else
    check_fail "Flask 未安装"
    echo "  安装命令: pip3 install flask flask-cors requests"
fi

# 检查 requests
if python3 -c "import requests" 2>/dev/null; then
    check_pass "requests 已安装"
else
    check_fail "requests 未安装"
fi

# 3. 检查服务文件
echo -e "\n[3/6] 检查服务文件..."
if [ -f "$HOME/lm_api_server/lm_api_server.py" ]; then
    check_pass "服务文件已安装: ~/lm_api_server/lm_api_server.py"
else
    check_fail "服务文件未找到"
    echo "  请先运行: ./deploy_lm_api.sh"
fi

# 4. 检查 API 密钥
echo -e "\n[4/6] 检查 API 密钥..."
if [ -f "$HOME/.lm_api_keys.json" ]; then
    KEY_COUNT=$(python3 -c "import json; print(len(json.load(open('$HOME/.lm_api_keys.json'))))" 2>/dev/null)
    check_pass "API 密钥文件存在 ($KEY_COUNT 个密钥)"
    
    # 显示第一个密钥的前缀
    FIRST_KEY=$(python3 -c "import json; print(list(json.load(open('$HOME/.lm_api_keys.json')).keys())[0][:20]+'...')" 2>/dev/null)
    echo "  第一个密钥: $FIRST_KEY"
else
    check_warn "API 密钥文件不存在，首次运行时会自动创建"
fi

# 5. 检查端口占用
echo -e "\n[5/6] 检查端口..."
if netstat -tlnp 2>/dev/null | grep -q ":8888"; then
    check_pass "端口 8888 正在使用"
    PID=$(netstat -tlnp 2>/dev/null | grep ":8888" | awk '{print $7}' | cut -d'/' -f1)
    echo "  PID: $PID"
elif ss -tlnp 2>/dev/null | grep -q ":8888"; then
    check_pass "端口 8888 正在使用"
else
    check_warn "端口 8888 空闲"
fi

# 6. 防火墙检查
echo -e "\n[6/6] 检查防火墙..."
if command -v ufw &> /dev/null; then
    if sudo ufw status | grep -q "8888"; then
        check_pass "UFW 防火墙已放行 8888 端口"
    else
        check_warn "UFW 未放行 8888 端口"
        echo "  运行: sudo ufw allow 8888/tcp"
    fi
elif command -v firewall-cmd &> /dev/null; then
    if firewall-cmd --list-ports 2>/dev/null | grep -q "8888"; then
        check_pass "firewalld 已放行 8888 端口"
    else
        check_warn "firewalld 未放行 8888 端口"
        echo "  运行: sudo firewall-cmd --add-port=8888/tcp --permanent"
    fi
else
    check_warn "无法检测防火墙状态"
fi

# 总结
echo -e "\n=========================================="
echo -e "检查完成: ${GREEN}$CHECKS_PASSED 通过${NC}, ${RED}$CHECKS_FAILED 失败${NC}"
echo "=========================================="

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}所有检查通过！可以启动服务了。${NC}"
    echo ""
    echo "启动命令:"
    echo "  python3 ~/lm_api_server/lm_api_server.py"
    echo ""
    echo "后台运行:"
    echo "  python3 ~/lm_api_server/lm_api_server.py --daemon"
else
    echo -e "\n${YELLOW}请修复上述问题后再启动服务。${NC}"
fi
