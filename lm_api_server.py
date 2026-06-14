#!/usr/bin/env python3
"""
LM Studio 远程 API 推理服务器
部署在 ham.vlsc.net 上，提供带身份验证的远程 AI 推理 API

使用方法:
    python3 lm_api_server.py          # 前台运行
    python3 lm_api_server.py --daemon # 后台运行
    python3 lm_api_server.py --stop   # 停止服务
"""

import os
import sys
import json
import time
import signal
import argparse
import logging
import hashlib
import secrets
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# ==================== 配置 ====================

# LM Studio 本地 API 地址
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"

# 服务监听配置
HOST = "0.0.0.0"  # 允许所有IP访问
PORT = 8888       # 外部访问端口

# 日志配置
LOG_DIR = "/tmp/lm_api_logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "lm_api_server.log")

# PID 文件（用于后台运行管理）
PID_FILE = "/tmp/lm_api_server.pid"

# API 密钥文件
API_KEYS_FILE = os.path.expanduser("~/.lm_api_keys.json")

# 默认模型
DEFAULT_MODEL = "qwen/qwen3.5-9b"

# 请求超时（秒）
REQUEST_TIMEOUT = 180

# ==================== 初始化 Flask ====================

app = Flask(__name__)
CORS(app)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 请求统计
request_stats = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "start_time": datetime.now().isoformat()
}

# ==================== API 密钥管理 ====================

def load_api_keys():
    """加载 API 密钥"""
    if os.path.exists(API_KEYS_FILE):
        try:
            with open(API_KEYS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 API 密钥失败: {e}")
    return {}

def save_api_keys(keys):
    """保存 API 密钥"""
    try:
        with open(API_KEYS_FILE, 'w') as f:
            json.dump(keys, f, indent=2)
        os.chmod(API_KEYS_FILE, 0o600)  # 只允许所有者读写
    except Exception as e:
        logger.error(f"保存 API 密钥失败: {e}")

def generate_api_key(name="default"):
    """生成新的 API 密钥"""
    key = f"lm_{secrets.token_urlsafe(32)}"
    keys = load_api_keys()
    keys[key] = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "last_used": None,
        "request_count": 0
    }
    save_api_keys(keys)
    return key

def validate_api_key(key):
    """验证 API 密钥"""
    if not key:
        return False
    keys = load_api_keys()
    if key in keys:
        # 更新使用统计
        keys[key]["last_used"] = datetime.now().isoformat()
        keys[key]["request_count"] += 1
        save_api_keys(keys)
        return True
    return False

# ==================== 认证装饰器 ====================

def require_api_key(f):
    """API 密钥认证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从 Header 或 Query 参数获取 API 密钥
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')

        if not api_key:
            logger.warning(f"请求缺少 API 密钥: {request.remote_addr}")
            return jsonify({
                "error": "缺少 API 密钥",
                "message": "请在 Header 中提供 X-API-Key 或在 URL 中添加 ?api_key=xxx"
            }), 401

        if not validate_api_key(api_key):
            logger.warning(f"无效的 API 密钥: {api_key[:10]}... from {request.remote_addr}")
            return jsonify({
                "error": "无效的 API 密钥",
                "message": "请提供有效的 API 密钥"
            }), 403

        return f(*args, **kwargs)
    return decorated_function

# ==================== 健康检查 ====================

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点（无需认证）"""
    try:
        # 检查 LM Studio 是否可访问
        response = requests.get("http://localhost:1234/v1/models", timeout=5)
        lm_status = "ok" if response.status_code == 200 else "error"
    except Exception as e:
        lm_status = f"error: {str(e)[:50]}"

    return jsonify({
        "status": "ok",
        "lm_studio": lm_status,
        "timestamp": datetime.now().isoformat(),
        "stats": request_stats
    })

# ==================== API 端点 ====================

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    """
    聊天补全 API（兼容 OpenAI 格式）

    请求格式:
    {
        "model": "qwen/qwen3.5-9b",
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "stream": false,
        "max_tokens": 1024,
        "temperature": 0.7
    }
    """
    global request_stats
    request_stats["total_requests"] += 1

    try:
        # 获取客户端请求数据
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400

        # 设置默认模型
        if 'model' not in data or not data['model']:
            data['model'] = DEFAULT_MODEL

        logger.info(f"推理请求: model={data.get('model')}, "
                   f"messages={len(data.get('messages', []))}, "
                   f"from={request.remote_addr}")

        # 转发请求到 LM Studio
        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(
            LM_STUDIO_URL,
            headers=headers,
            json=data,
            timeout=REQUEST_TIMEOUT,
            stream=data.get('stream', False)
        )

        # 处理流式响应
        if data.get('stream', False):
            def generate():
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
            return Response(
                generate(),
                status=response.status_code,
                content_type=response.headers.get('content-type', 'application/json')
            )

        # 非流式响应
        response_data = response.json()
        request_stats["successful_requests"] += 1

        logger.info(f"推理完成: tokens={response_data.get('usage', {}).get('total_tokens', 'N/A')}")

        return jsonify(response_data), response.status_code

    except requests.exceptions.Timeout:
        request_stats["failed_requests"] += 1
        logger.error("推理请求超时")
        return jsonify({"error": "推理请求超时", "message": f"请求超过 {REQUEST_TIMEOUT} 秒"}), 504

    except requests.exceptions.ConnectionError:
        request_stats["failed_requests"] += 1
        logger.error("无法连接到 LM Studio")
        return jsonify({
            "error": "LM Studio 连接失败",
            "message": "请确保 LM Studio 已在本地启动并加载模型"
        }), 503

    except Exception as e:
        request_stats["failed_requests"] += 1
        logger.error(f"推理错误: {e}")
        return jsonify({"error": "推理失败", "message": str(e)}), 500


@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    """获取可用模型列表"""
    try:
        response = requests.get("http://localhost:1234/v1/models", timeout=5)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({
            "error": "获取模型列表失败",
            "message": str(e)
        }), 500


@app.route('/v1/embeddings', methods=['POST'])
@require_api_key
def create_embeddings():
    """创建文本嵌入（如果 LM Studio 支持）"""
    try:
        data = request.get_json()
        response = requests.post(
            "http://localhost:1234/v1/embeddings",
            json=data,
            timeout=30
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": "嵌入生成失败", "message": str(e)}), 500

# ==================== 管理接口 ====================

@app.route('/admin/stats', methods=['GET'])
def get_stats():
    """获取服务统计信息（可添加额外认证）"""
    return jsonify({
        "status": "running",
        "stats": request_stats,
        "config": {
            "host": HOST,
            "port": PORT,
            "lm_studio_url": LM_STUDIO_URL,
            "default_model": DEFAULT_MODEL
        }
    })


@app.route('/admin/keys', methods=['GET', 'POST', 'DELETE'])
def manage_keys():
    """管理 API 密钥（需要管理员密码）"""
    admin_password = request.headers.get('X-Admin-Password')

    # 简单的管理员密码验证（生产环境应使用更安全的方式）
    expected_password = os.environ.get('LM_API_ADMIN_PASSWORD', 'admin123')

    if not admin_password or admin_password != expected_password:
        return jsonify({"error": "未授权", "message": "需要提供有效的管理员密码"}), 401

    if request.method == 'GET':
        # 列出所有密钥（隐藏完整密钥）
        keys = load_api_keys()
        masked_keys = {}
        for key, info in keys.items():
            masked_key = key[:8] + "..." + key[-4:]
            masked_keys[masked_key] = info
        return jsonify({"keys": masked_keys, "count": len(keys)})

    elif request.method == 'POST':
        # 创建新密钥
        data = request.get_json() or {}
        name = data.get('name', f"key_{int(time.time())}")
        new_key = generate_api_key(name)
        return jsonify({
            "message": "API 密钥创建成功",
            "key": new_key,
            "name": name
        })

    elif request.method == 'DELETE':
        # 删除密钥
        data = request.get_json() or {}
        key_to_delete = data.get('key')
        if not key_to_delete:
            return jsonify({"error": "缺少密钥参数"}), 400

        keys = load_api_keys()
        if key_to_delete in keys:
            del keys[key_to_delete]
            save_api_keys(keys)
            return jsonify({"message": "API 密钥已删除"})
        return jsonify({"error": "密钥不存在"}), 404

# ==================== 后台进程管理 ====================

def write_pid():
    """写入 PID 文件"""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def read_pid():
    """读取 PID 文件"""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                return int(f.read().strip())
    except:
        pass
    return None

def remove_pid():
    """删除 PID 文件"""
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def daemonize():
    """将进程转为守护进程"""
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork 失败: {e}")
        sys.exit(1)

    os.chdir("/")
    os.setsid()
    os.umask(0)

    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork 失败: {e}")
        sys.exit(1)

    sys.stdout.flush()
    sys.stderr.flush()

    si = open(os.devnull, 'r')
    so = open(os.devnull, 'a+')
    se = open(os.devnull, 'a+')

    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())

    write_pid()

def stop_daemon():
    """停止守护进程"""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            remove_pid()
            print(f"服务已停止 (PID: {pid})")
        except ProcessLookupError:
            print("服务未运行")
            remove_pid()
        except Exception as e:
            print(f"停止服务失败: {e}")
    else:
        print("未找到运行中的服务")

# ==================== 初始化 ====================

def initialize():
    """初始化服务"""
    # 确保至少有一个 API 密钥
    keys = load_api_keys()
    if not keys:
        default_key = generate_api_key("default")
        print(f"\n{'='*60}")
        print("初始化完成！已生成默认 API 密钥：")
        print(f"\n{default_key}\n")
        print("请保存好此密钥，它只显示一次！")
        print(f"{'='*60}\n")
        logger.info("已生成默认 API 密钥")

# ==================== 主函数 ====================

def main():
    parser = argparse.ArgumentParser(description='LM Studio 远程 API 服务器')
    parser.add_argument('--daemon', action='store_true', help='后台运行')
    parser.add_argument('--stop', action='store_true', help='停止服务')
    parser.add_argument('--host', default=HOST, help=f'监听地址 (默认: {HOST})')
    parser.add_argument('--port', type=int, default=PORT, help=f'监听端口 (默认: {PORT})')
    parser.add_argument('--generate-key', metavar='NAME', help='生成新的 API 密钥')
    parser.add_argument('--list-keys', action='store_true', help='列出所有 API 密钥')

    args = parser.parse_args()

    if args.stop:
        stop_daemon()
        return

    if args.generate_key:
        key = generate_api_key(args.generate_key)
        print(f"\n新 API 密钥已生成:\n{key}\n")
        return

    if args.list_keys:
        keys = load_api_keys()
        print("\n已配置的 API 密钥:")
        for key, info in keys.items():
            masked = key[:8] + "..." + key[-4:]
            print(f"  {masked}: {info.get('name', 'unnamed')} "
                  f"(使用 {info.get('request_count', 0)} 次)")
        print()
        return

    # 初始化
    initialize()

    if args.daemon:
        daemonize()
        logger.info(f"服务已启动 (守护进程模式) http://{HOST}:{args.port}")
    else:
        logger.info(f"服务已启动 http://{args.host}:{args.port}")
        print(f"\n服务已启动: http://{args.host}:{args.port}")
        print(f"健康检查: http://{args.host}:{args.port}/health")
        print(f"API 文档: http://{args.host}:{args.port}/docs")
        print(f"\n日志文件: {LOG_FILE}")
        print(f"按 Ctrl+C 停止服务\n")

    # 启动 Flask
    app.run(host=args.host, port=args.port, threaded=True)

if __name__ == '__main__':
    main()
