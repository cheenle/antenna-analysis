#!/bin/bash
# AI 分析报告自动生成脚本
# 可添加到 crontab 定期执行

# 设置环境变量
export LM_API_KEY="${LM_API_KEY:-}"
export LM_API_URL="${LM_API_URL:-http://ham.vlsc.net:8888}"

# 工作目录
 cd "$(dirname "$0")"

# 日志文件
LOG_FILE="logs/ai_report.log"
mkdir -p logs

# 参数
DAYS="${1:-7}"
TYPE="${2:-full}"

echo "========================================" >> "$LOG_FILE"
echo "AI 报告生成 - $(date)" >> "$LOG_FILE"
echo "类型: $TYPE, 天数: $DAYS" >> "$LOG_FILE"

# 运行报告生成器
python3 ai_report_generator.py --type "$TYPE" --days "$DAYS" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 报告生成成功" >> "$LOG_FILE"
else
    echo "❌ 报告生成失败 (exit code: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"

exit $EXIT_CODE
