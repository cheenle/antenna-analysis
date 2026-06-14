#!/bin/bash
# 在 ham.vlsc.net 上部署 LM API 服务端
# 复制此文件到 ham.vlsc.net 后执行

echo "=========================================="
echo "在 ham.vlsc.net 部署 LM API 服务端"
echo "=========================================="

# 创建服务目录
mkdir -p ~/lm_api_server
cd ~/lm_api_server

# 创建服务文件
cat > lm_api_server.py << 'PYTHON_EOF'
#!/usr/bin/env python3
"""LM Studio 远程 API 推理服务器"""

import os
import sys
import json
import time
import argparse
import logging
import secrets
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# 配置
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
HOST = "0.0.0.0"
PORT = 8888
LOG_DIR = "/tmp/lm_api_logs"
API_KEYS_FILE = os.path.expanduser("~/.lm_api_keys.json")
DEFAULT_MODEL = "qwen/qwen3.5-9b"

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "lm_api_server.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

def load_api_keys():
    if os.path.exists(API_KEYS_FILE):
        try:
            with open(API_KEYS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_api_keys(keys):
    with open(API_KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=2)
    os.chmod(API_KEYS_FILE, 0o600)

def generate_api_key(name="default"):
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
    if not key:
        return False
    keys = load_api_keys()
    if key in keys:
        keys[key]["last_used"] = datetime.now().isoformat()
        keys[key]["request_count"] += 1
        save_api_keys(keys)
        return True
    return False

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({"error": "缺少 API 密钥"}), 401
        if not validate_api_key(api_key):
            return jsonify({"error": "无效的 API 密钥"}), 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/health', methods=['GET'])
def health_check():
    try:
        response = requests.get("http://localhost:1234/v1/models", timeout=5)
        lm_status = "ok" if response.status_code == 200 else "error"
    except Exception as e:
        lm_status = f"error: {str(e)[:50]}"
    
    return jsonify({
        "status": "ok",
        "lm_studio": lm_status,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        
        if 'model' not in data or not data['model']:
            data['model'] = DEFAULT_MODEL
        
        headers = {"Content-Type": "application/json"}
        response = requests.post(
            LM_STUDIO_URL,
            headers=headers,
            json=data,
            timeout=180,
            stream=data.get('stream', False)
        )
        
        if data.get('stream', False):
            def generate():
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
            return Response(generate(), status=response.status_code,
                          content_type=response.headers.get('content-type', 'application/json'))
        
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.Timeout:
        return jsonify({"error": "推理超时"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "无法连接到 LM Studio"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/v1/models', methods=['GET'])
@require_api_key
def list_models():
    try:
        response = requests.get("http://localhost:1234/v1/models", timeout=5)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def initialize():
    keys = load_api_keys()
    if not keys:
        default_key = generate_api_key("default")
        print(f"\n{'='*60}")
        print("🎉 首次运行，已生成默认 API 密钥：")
        print(f"\n{default_key}\n")
        print("⚠️  请保存好此密钥，它只显示一次！")
        print(f"{'='*60}\n")
        
        # 同时保存到 key.txt 方便查看
        with open(os.path.expanduser("~/.lm_api_key.txt"), 'w') as f:
            f.write(default_key)
        os.chmod(os.path.expanduser("~/.lm_api_key.txt"), 0o600)
        print(f"密钥也已保存到: ~/.lm_api_key.txt")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate-key', metavar='NAME', help='生成新密钥')
    parser.add_argument('--list-keys', action='store_true', help='列出密钥')
    parser.add_argument('--host', default=HOST, help=f'监听地址 (默认: {HOST})')
    parser.add_argument('--port', type=int, default=PORT, help=f'监听端口 (默认: {PORT})')
    args = parser.parse_args()
    
    if args.generate_key:
        key = generate_api_key(args.generate_key)
        print(f"新密钥: {key}")
        sys.exit(0)
    
    if args.list_keys:
        keys = load_api_keys()
        for key, info in keys.items():
            masked = key[:8] + "..." + key[-4:]
            print(f"{masked}: {info.get('name', 'unnamed')} ({info.get('request_count', 0)} 次使用)")
        sys.exit(0)
    
    initialize()
    print(f"🚀 启动服务: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)
PYTHON_EOF

# 检查依赖
echo ""
echo "📦 检查 Python 依赖..."
python3 -c "import flask, flask_cors, requests" 2>/dev/null || {
    echo "安装依赖..."
    pip3 install flask flask-cors requests --user 2>/dev/null || pip3 install flask flask-cors requests --break-system-packages 2>/dev/null
}

# 检查 LM Studio
echo ""
echo "🔍 检查 LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo "✅ LM Studio 运行正常"
else
    echo "⚠️  LM Studio 未在 localhost:1234 响应"
    echo "请确保:"
    echo "  1. LM Studio 已启动"
    echo "  2. 已加载模型"
    echo "  3. 服务器模式已开启 (端口 1234)"
    echo ""
    read -p "按回车继续，或 Ctrl+C 退出..."
fi

# 启动服务
echo ""
echo "🚀 启动 LM API 服务..."
echo "=========================================="
cd ~/lm_api_server
python3 lm_api_server.py --host 0.0.0.0 --port 8888

