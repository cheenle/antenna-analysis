#!/bin/bash
# AI 报告生成测试脚本

cd "$(dirname "$0")"

# 加载配置
if [ -f ".env.lm.api" ]; then
    source .env.lm.api
    echo "✅ 已加载 API 配置"
    echo "   URL: $LM_API_URL"
    echo "   Key: ${LM_API_KEY:0:20}..."
else
    echo "❌ 配置文件不存在，请先运行: python3 configure_lm_api.py"
    exit 1
fi

echo ""
echo "🧪 测试 API 连接..."
curl -s -o /dev/null -w "%{http_code}" "$LM_API_URL/health"
if [ $? -eq 0 ]; then
    echo "✅ 连接正常"
else
    echo "❌ 连接失败"
    exit 1
fi

echo ""
echo "🤖 生成 AI 分析报告..."
python3 ai_report_generator.py --type propagation --days 1
