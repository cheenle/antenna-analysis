#!/bin/bash
# LM API 服务检查和重启脚本
# 在 ham.vlsc.net 上运行

echo "=========================================="
echo "LM API 服务诊断工具"
echo "=========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 1. 检查端口占用
echo -e "\n[1/5] 检查 8888 端口占用..."
PORT_PID=$(netstat -tlnp 2>/dev/null | grep ':8888' | awk '{print $7}' | cut -d'/' -f1)
if [ -n "$PORT_PID" ]; then
    echo -e "${YELLOW}⚠️  端口 8888 已被占用 (PID: $PORT_PID)${NC}"
    echo "进程信息:"
    ps -f -p $PORT_PID | head -2
else
    echo -e "${GREEN}✓ 端口 8888 空闲${NC}"
fi

# 2. 检查 LM API 服务进程
echo -e "\n[2/5] 检查 LM API 服务进程..."
LM_PID=$(pgrep -f "lm_api_server.py")
if [ -n "$LM_PID" ]; then
    echo -e "${GREEN}✓ LM API 服务正在运行 (PID: $LM_PID)${NC}"
    ps -f -p $LM_PID
else
    echo -e "${RED}✗ LM API 服务未运行${NC}"
fi

# 3. 检查 LM Studio
echo -e "\n[3/5] 检查 LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}✓ LM Studio 运行正常 (localhost:1234)${NC}"
else
    echo -e "${RED}✗ LM Studio 未响应${NC}"
    echo "   请确保 LM Studio 已启动并开启服务器模式"
fi

# 4. 测试服务响应
echo -e "\n[4/5] 测试服务响应..."
RESPONSE=$(curl -s http://localhost:8888/health 2>/dev/null)
if [ -n "$RESPONSE" ]; then
    echo -e "${GREEN}✓ 服务响应正常${NC}"
    echo "   响应: $RESPONSE"
else
    echo -e "${RED}✗ 服务无响应${NC}"
fi

# 5. 检查防火墙
echo -e "\n[5/5] 检查防火墙..."
if command -v ufw &> /dev/null; then
    if sudo ufw status | grep -q "8888"; then
        echo -e "${GREEN}✓ 防火墙已放行 8888 端口${NC}"
    else
        echo -e "${YELLOW}⚠️  防火墙未放行 8888 端口${NC}"
        echo "   运行: sudo ufw allow 8888/tcp"
    fi
fi

# 重启选项
echo -e "\n=========================================="
echo "诊断完成"
echo "=========================================="
echo ""
echo "选项:"
echo "  1. 重启 LM API 服务 (使用 8888 端口)"
echo "  2. 使用其他端口启动 (8889)"
echo "  3. 查看日志"
echo "  4. 退出"
echo ""
read -p "选择操作 [1-4]: " choice

case $choice in
    1)
        echo -e "\n🔄 重启服务..."
        # 停止现有服务
        if [ -n "$LM_PID" ]; then
            echo "停止现有进程 (PID: $LM_PID)..."
            kill $LM_PID 2>/dev/null
            sleep 2
        fi
        
        # 启动服务
        cd ~/lm_api_server 2>/dev/null || cd ~
        if [ -f "lm_api_server.py" ]; then
            nohup python3 lm_api_server.py --host 0.0.0.0 --port 8888 > /tmp/lm_api.log 2>&1 &
            echo $! > /tmp/lm_api.pid
            echo -e "${GREEN}✓ 服务已启动 (PID: $(cat /tmp/lm_api.pid))${NC}"
            echo "日志: tail -f /tmp/lm_api.log"
            sleep 2
            echo -e "\n测试连接:"
            curl -s http://localhost:8888/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8888/health
        else
            echo -e "${RED}✗ 未找到 lm_api_server.py${NC}"
            echo "请先部署服务"
        fi
        ;;
    2)
        echo -e "\n🔄 使用端口 8889 启动..."
        cd ~/lm_api_server 2>/dev/null || cd ~
        if [ -f "lm_api_server.py" ]; then
            nohup python3 lm_api_server.py --host 0.0.0.0 --port 8889 > /tmp/lm_api_8889.log 2>&1 &
            echo $! > /tmp/lm_api_8889.pid
            echo -e "${GREEN}✓ 服务已在 8889 端口启动${NC}"
            echo "请在客户端更新配置: export LM_API_URL='http://ham.vlsc.net:8889'"
        fi
        ;;
    3)
        echo -e "\n📋 查看日志..."
        if [ -f /tmp/lm_api.log ]; then
            tail -50 /tmp/lm_api.log
        elif [ -f /tmp/lm_api_logs/lm_api_server.log ]; then
            tail -50 /tmp/lm_api_logs/lm_api_server.log
        else
            echo "未找到日志文件"
        fi
        ;;
    *)
        echo "退出"
        ;;
esac
