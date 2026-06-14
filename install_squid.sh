#!/bin/bash
# 在 www.vlsc.net 上安装和配置 Squid 代理服务器
# 监听端口: 3333

set -e

echo "=========================================="
echo "Squid 代理服务器安装脚本"
echo "目标: www.vlsc.net:3333"
echo "=========================================="

# 检测系统类型
if [ -f /etc/debian_version ]; then
    OS="debian"
    PKG_MANAGER="apt"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
    PKG_MANAGER="yum"
else
    echo "无法检测系统类型"
    exit 1
fi

echo "检测到系统: $OS"

# 1. 安装 Squid
echo ""
echo "[1/4] 安装 Squid..."
if [ "$PKG_MANAGER" = "apt" ]; then
    apt update -qq
    apt install -y squid
elif [ "$PKG_MANAGER" = "yum" ]; then
    yum install -y squid
fi

# 2. 备份原配置
echo ""
echo "[2/4] 备份原配置..."
cp /etc/squid/squid.conf /etc/squid/squid.conf.bak.$(date +%Y%m%d) 2>/dev/null || \
cp /etc/squid3/squid.conf /etc/squid3/squid.conf.bak.$(date +%Y%m%d) 2>/dev/null || true

# 3. 创建新配置
echo ""
echo "[3/4] 创建配置文件..."

# 确定配置文件路径
if [ -f /etc/squid/squid.conf ]; then
    SQUID_CONF="/etc/squid/squid.conf"
else
    SQUID_CONF="/etc/squid3/squid.conf"
fi

cat > "$SQUID_CONF" << 'EOF'
# Squid 配置文件
# 监听端口: 3333

# 基本设置
visible_hostname www.vlsc.net
cache_effective_user proxy
cache_effective_group proxy

# 监听端口
http_port 3333

# 缓存设置
cache_dir ufs /var/spool/squid 100 16 256
cache_mem 64 MB
maximum_object_size 10 MB
maximum_object_size_in_memory 1 MB

# 日志设置
access_log /var/log/squid/access.log squid
cache_log /var/log/squid/cache.log
pid_filename /var/run/squid.pid

# 访问控制 - 允许所有
acl all src all
acl localnet src 10.0.0.0/8      # RFC1918 内网
acl localnet src 172.16.0.0/12   # RFC1918 内网
acl localnet src 192.168.0.0/16  # RFC1918 内网
acl localnet src fc00::/7        # RFC4193 本地IPv6
acl localnet src fe80::/10       # 链路本地IPv6

# SSL 端口
acl SSL_ports port 443
acl Safe_ports port 80          # http
acl Safe_ports port 21          # ftp
acl Safe_ports port 443         # https
acl Safe_ports port 70          # gopher
acl Safe_ports port 210         # wais
acl Safe_ports port 1025-65535  # 未注册端口
acl Safe_ports port 280         # http-mgmt
acl Safe_ports port 488         # gss-http
acl Safe_ports port 591         # filemaker
acl Safe_ports port 777         # multiling http
acl CONNECT method CONNECT

# 访问规则
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow localhost manager
http_access deny manager
http_access allow localnet
http_access allow localhost
http_access allow all

# 刷新规则
refresh_pattern ^ftp:           1440    20%     10080
refresh_pattern ^gopher:        1440    0%      1440
refresh_pattern -i (/cgi-bin/|\?) 0     0%      0
refresh_pattern .               0       20%     4320

# 关闭转发
forwarded_for off

# 超时设置
connect_timeout 60 seconds
read_timeout 15 minutes
request_timeout 5 minutes

# 透明代理设置（可选）
# via off
# forwarded_for delete
EOF

echo "配置文件已创建: $SQUID_CONF"

# 4. 初始化并启动服务
echo ""
echo "[4/4] 初始化并启动服务..."

# 初始化缓存目录
squid -z 2>/dev/null || true

# 启动服务
if command -v systemctl &> /dev/null; then
    systemctl enable squid
    systemctl restart squid
    sleep 2
    systemctl status squid --no-pager || true
elif command -v service &> /dev/null; then
    service squid restart
fi

# 验证端口
echo ""
echo "=========================================="
echo "验证服务状态..."
echo "=========================================="

if netstat -tlnp 2>/dev/null | grep -q ":3333"; then
    echo "✅ Squid 已在 3333 端口监听"
elif ss -tlnp 2>/dev/null | grep -q ":3333"; then
    echo "✅ Squid 已在 3333 端口监听"
else
    echo "⚠️  端口 3333 未监听，请检查日志"
fi

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""
echo "代理地址: http://www.vlsc.net:3333"
echo "配置文件: $SQUID_CONF"
echo "日志目录: /var/log/squid/"
echo ""
echo "测试命令:"
echo "  curl -x http://www.vlsc.net:3333 http://www.google.com"
echo ""
echo "管理命令:"
echo "  systemctl restart squid   # 重启"
echo "  systemctl status squid    # 状态"
echo "  tail -f /var/log/squid/access.log  # 查看日志"