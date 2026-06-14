#!/bin/bash
# LM API 环境变量设置脚本
# 交互式配置 API 密钥

echo "=========================================="
echo "LM Studio 远程 API 环境配置"
echo "=========================================="
echo ""

# 检查是否已有配置
if [ -f ".env.lm.api" ]; then
    source .env.lm.api 2>/dev/null
fi

# 提示输入 API 密钥
echo "请输入从 ham.vlsc.net 获取的 API 密钥"
echo "格式如: lm_xxxxx..."
if [ -n "$LM_API_KEY" ]; then
    echo "(当前值: ${LM_API_KEY:0:15}..., 直接回车保持不变)"
fi
read -p "> " api_key

# 如果用户输入了新值，则更新
if [ -n "$api_key" ]; then
    LM_API_KEY="$api_key"
fi

# 提示输入 API URL
echo ""
echo "请输入 API 服务端地址"
echo "(默认: http://ham.vlsc.net:8888, 直接回车使用默认值)"
if [ -n "$LM_API_URL" ]; then
    echo "(当前值: $LM_API_URL)"
fi
read -p "> " api_url

# 如果用户输入了新值，则更新
if [ -n "$api_url" ]; then
    LM_API_URL="$api_url"
else
    LM_API_URL="${LM_API_URL:-http://ham.vlsc.net:8888}"
fi

# 写入配置文件
cat > .env.lm.api << EOF
# LM Studio 远程 API 配置
# 自动生成于 $(date)

export LM_API_KEY='$LM_API_KEY'
export LM_API_URL='$LM_API_URL'
EOF

echo ""
echo "=========================================="
echo "✅ 配置已保存到 .env.lm.api"
echo "=========================================="
echo ""
echo "当前配置:"
echo "  API URL: $LM_API_URL"
echo "  API Key: ${LM_API_KEY:0:15}..."
echo ""
echo "使用方式:"
echo "  1. 加载配置: source .env.lm.api"
echo "  2. 生成报告: python3 ai_report_generator.py"
echo "  3. 或直接运行: ./run_ai_report.sh"
echo ""
echo "添加到 ~/.zshrc 或 ~/.bashrc 可永久生效:"
echo "  echo 'source $(pwd)/.env.lm.api' >> ~/.zshrc"
echo ""

# 询问是否立即加载
read -p "是否立即加载配置? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    export LM_API_KEY="$LM_API_KEY"
    export LM_API_URL="$LM_API_URL"
    echo "✅ 环境变量已加载到当前会话"
fi
