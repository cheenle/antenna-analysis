#!/bin/bash
# 远程启动脚本 - 上传到 ham.vlsc.net 执行

pkill -f lm_api_server.py 2>/dev/null
pkill -f lm_server_minimal.py 2>/dev/null
sleep 1

cd ~
nohup python3 lm_api_server.py 8889 > /tmp/lm_api_8889.log 2>&1 &
sleep 2

echo "服务已启动在端口 8889"
echo "API Key: $(cat ~/.lm_api_key.txt 2>/dev/null || echo 'unknown')"
netstat -tlnp 2>/dev/null | grep 8889 || ss -tlnp | grep 8889
