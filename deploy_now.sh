#!/bin/bash
# 一键部署 LM API 服务到 ham.vlsc.net

echo "🚀 部署 LM API 服务到 ham.vlsc.net..."

# 检查 SSH 连接
echo "📡 检查 SSH 连接..."
if ! ssh -o ConnectTimeout=3 cheenle@ham.vlsc.net "echo OK" 2>/dev/null | grep -q OK; then
    echo "❌ 无法 SSH 到 ham.vlsc.net"
    exit 1
fi
echo "✅ SSH 连接正常"

# 复制服务端文件
echo "📤 上传服务端文件..."
scp lm_server_minimal.py cheenle@ham.vlsc.net:~/lm_api_server.py

# 在远程执行部署和启动
ssh cheenle@ham.vlsc.net '
    echo "🔍 检查环境..."
    
    # 检查 Python 依赖
    python3 -c "import flask,requests" 2>/dev/null || {
        echo "📦 安装依赖..."
        pip3 install flask requests --user 2>/dev/null || pip3 install flask requests --break-system-packages
    }
    
    # 停止旧服务
    pkill -f "lm_api_server.py" 2>/dev/null
    pkill -f "lm_server_minimal.py" 2>/dev/null
    sleep 1
    
    # 检查端口 8888
    PORT_PID=$(netstat -tlnp 2>/dev/null | grep ":8888" | awk "{print \$7}" | cut -d"/" -f1)
    if [ -n "$PORT_PID" ]; then
        echo "⚠️  端口 8888 被占用，使用 8889..."
        PORT=8889
    else
        PORT=8888
    fi
    
    # 启动服务
    echo "🚀 启动服务 (端口 $PORT)..."
    cd ~
    nohup python3 lm_api_server.py --host 0.0.0.0 --port $PORT > /tmp/lm_api.log 2>&1 &
    sleep 2
    
    # 获取 API Key
    if [ -f ~/.lm_api_key.txt ]; then
        API_KEY=$(cat ~/.lm_api_key.txt)
    else
        API_KEY=$(python3 -c "import json; print(list(json.load(open('$HOME/.lm_api_keys.json')).keys())[0])" 2>/dev/null)
    fi
    
    echo ""
    echo "=========================================="
    echo "✅ 部署完成！"
    echo "=========================================="
    echo ""
    echo "API URL: http://ham.vlsc.net:$PORT"
    echo "API Key: $API_KEY"
    echo ""
    echo "本地配置命令:"
    echo "  echo \"export LM_API_KEY='$API_KEY'\" > .env.lm.api"
    echo "  echo \"export LM_API_URL='http://ham.vlsc.net:$PORT'\" >> .env.lm.api"
    echo "  source .env.lm.api"
    echo ""
'

echo ""
echo "📝 正在获取配置信息..."
ssh cheenle@ham.vlsc.net 'cat ~/.lm_api_key.txt 2>/dev/null || python3 -c "import json; print(list(json.load(open('$HOME/.lm_api_keys.json')).keys())[0])"' > /tmp/lm_key.txt

API_KEY=$(cat /tmp/lm_key.txt)
PORT=$(ssh cheenle@ham.vlsc.net 'netstat -tlnp 2>/dev/null | grep python3 | grep -oE ":[0-9]+" | head -1 | tr -d ":"')
PORT=${PORT:-8888}

# 更新本地配置
echo "export LM_API_KEY='$API_KEY'" > .env.lm.api
echo "export LM_API_URL='http://ham.vlsc.net:$PORT'" >> .env.lm.api

echo "✅ 本地配置已更新 (.env.lm.api)"
echo ""
echo "🧪 测试连接..."
source .env.lm.api
curl -s "$LM_API_URL/health" | python3 -m json.tool 2>/dev/null || curl -s "$LM_API_URL/health"

echo ""
echo "🎉 部署完成！现在可以使用了:"
echo "  python3 ai_report_generator.py"
