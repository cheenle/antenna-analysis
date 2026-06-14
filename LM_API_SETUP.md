# LM Studio 远程 API 配置指南

## 概述

本文档说明如何在 `ham.vlsc.net` 上配置 LM Studio 远程 API 推理服务，以便其他机器可以通过 HTTP API 安全地调用 AI 推理功能。

## 架构

```
┌─────────────────┐      HTTP API      ┌──────────────────┐      Local      ┌──────────────┐
│   客户端机器     │  ────────────────> │ ham.vlsc.net     │  ────────────>  │ LM Studio    │
│                 │   X-API-Key 认证   │ :8888            │                 │ :1234        │
└─────────────────┘                    └──────────────────┘                 └──────────────┘
```

## 文件说明

| 文件 | 说明 | 部署位置 |
|------|------|----------|
| `lm_api_server.py` | API 服务端主程序 | ham.vlsc.net |
| `lm_remote_client.py` | 远程客户端 | 任意客户端机器 |
| `deploy_lm_api.sh` | 部署脚本 | ham.vlsc.net |
| `lm_api_nginx.conf` | Nginx 反向代理配置 | ham.vlsc.net (可选) |
| `ai_analyzer.py` | AI 分析模块（已更新） | 本地 |

## 部署步骤

### 1. 在 ham.vlsc.net 上部署服务端

```bash
# 复制文件到 ham.vlsc.net
scp lm_api_server.py deploy_lm_api.sh cheenle@ham.vlsc.net:~/

# SSH 登录到 ham.vlsc.net
ssh cheenle@ham.vlsc.net

# 运行部署脚本
cd ~
chmod +x deploy_lm_api.sh
./deploy_lm_api.sh
```

部署脚本会：
- 检查依赖（Python、Flask、requests）
- 检查 LM Studio 运行状态
- 安装所需的 Python 包
- 生成默认 API 密钥
- 创建启动/停止脚本

### 2. 启动服务

```bash
# 前台运行（调试用）
python3 ~/lm_api_server/lm_api_server.py

# 后台运行
python3 ~/lm_api_server/lm_api_server.py --daemon

# 或使用脚本
~/lm_api_server/start.sh
```

### 3. 验证服务

```bash
# 检查健康状态
curl http://ham.vlsc.net:8888/health

# 预期输出:
{
  "status": "ok",
  "lm_studio": "ok",
  "timestamp": "2026-04-06T...",
  "stats": {...}
}
```

## 客户端配置

### 方法 1: 环境变量配置

```bash
# 在客户端机器上设置环境变量
export LM_API_KEY='your-api-key-here'
export LM_API_URL='http://ham.vlsc.net:8888'
```

### 方法 2: Python 客户端直接使用

```python
from lm_remote_client import LMRemoteClient

client = LMRemoteClient(
    api_key='your-api-key-here',
    api_url='http://ham.vlsc.net:8888'
)

# 简单调用
response = client.chat_simple("你好，请介绍一下自己")
print(response)
```

### 方法 3: 命令行工具

```bash
# 设置环境变量后
export LM_API_KEY='your-api-key-here'

# 直接提问
python3 lm_remote_client.py "分析当前10米波段传播条件"

# 从文件读取提示词
python3 lm_remote_client.py --file prompt.txt

# 流式输出
python3 lm_remote_client.py --stream "写一首关于短波通联的诗"

# 检查服务状态
python3 lm_remote_client.py --health

# 列出可用模型
python3 lm_remote_client.py --list-models

# 执行传播分析
python3 lm_remote_client.py --analyze propagation
```

## API 端点

### 1. 健康检查 (无需认证)

```bash
GET /health
```

### 2. 聊天补全 (需要 API Key)

```bash
POST /v1/chat/completions
Content-Type: application/json
X-API-Key: your-api-key

{
  "model": "qwen/qwen3.5-9b",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false
}
```

### 3. 获取模型列表 (需要 API Key)

```bash
GET /v1/models
X-API-Key: your-api-key
```

### 4. 服务统计 (管理员)

```bash
GET /admin/stats
```

### 5. 管理 API 密钥 (需要管理员密码)

```bash
# 列出密钥
GET /admin/keys
X-Admin-Password: admin123

# 创建新密钥
POST /admin/keys
X-Admin-Password: admin123
{"name": "new-key"}

# 删除密钥
DELETE /admin/keys
X-Admin-Password: admin123
{"key": "lm_xxx..."}
```

## API 密钥管理

### 查看当前密钥

```bash
python3 lm_api_server.py --list-keys
```

### 生成新密钥

```bash
python3 lm_api_server.py --generate-key "my-app"
```

### 重置所有密钥

删除密钥文件：
```bash
rm ~/.lm_api_keys.json
```

重启服务后会自动生成新的默认密钥。

## 与 ai_analyzer.py 集成

`ai_analyzer.py` 已更新支持远程 API。只需设置环境变量：

```bash
export LM_API_KEY='your-api-key'
export LM_API_URL='http://ham.vlsc.net:8888'

python3 ai_analyzer.py
```

如果不设置这些变量，会回退到原来的 SSH 调用方式。

## Nginx 反向代理（可选）

如果需要 HTTPS 支持或使用域名：

```bash
# 复制配置
sudo cp lm_api_nginx.conf /etc/nginx/sites-available/lm-api
sudo ln -s /etc/nginx/sites-available/lm-api /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载配置
sudo systemctl reload nginx
```

## 故障排除

### 服务无法启动

1. 检查端口是否被占用：
   ```bash
   netstat -tlnp | grep 8888
   ```

2. 检查 LM Studio 是否运行：
   ```bash
   curl http://localhost:1234/v1/models
   ```

### API 返回 401/403

- 检查 API 密钥是否正确设置
- 在服务端查看密钥：`python3 lm_api_server.py --list-keys`

### 推理超时

- 检查 LM Studio 是否繁忙
- 调整客户端超时设置
- 查看日志：`tail -f /tmp/lm_api_logs/lm_api_server.log`

### SSH 连接问题（旧模式）

如果未配置远程 API 而使用 SSH 模式：
- 确保 SSH 密钥已配置（无密码登录）
- 检查 ham.vlsc.net 上的 LM Studio 端口

## 安全建议

1. **防火墙配置**：只开放必要的端口（8888）
2. **API 密钥**：定期轮换，不要硬编码在代码中
3. **HTTPS**：生产环境建议使用 Nginx + SSL
4. **访问控制**：可通过 Nginx 添加 IP 白名单
5. **管理员密码**：修改默认密码 `admin123`

## 性能优化

- LM Studio 的并发处理能力取决于硬件配置
- 建议根据 GPU 显存调整并发请求数
- 流式响应（stream=true）可减少等待时间

## 更新和维护

```bash
# 停止服务
python3 lm_api_server.py --stop

# 更新代码后重新启动
python3 lm_api_server.py --daemon

# 查看日志
tail -f /tmp/lm_api_logs/lm_api_server.log
```
