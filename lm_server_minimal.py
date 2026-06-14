#!/usr/bin/env python3
"""LM API 服务端简化版 - 直接部署在 ham.vlsc.net"""

import os, sys, json, secrets
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
LM_URL = "http://localhost:1234/v1/chat/completions"
KEY_FILE = os.path.expanduser("~/.lm_api_keys.json")

# 加载/保存密钥
def load_keys():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            return json.load(f)
    return {}

def save_keys(keys):
    with open(KEY_FILE, 'w') as f:
        json.dump(keys, f)

# 生成默认密钥
if not load_keys():
    key = f"lm_{secrets.token_urlsafe(32)}"
    save_keys({key: {"name": "default", "created": datetime.now().isoformat(), "request_count": 0}})
    print(f"\n🔑 API Key: {key}\n")
    with open(os.path.expanduser("~/.lm_api_key.txt"), 'w') as f:
        f.write(key)

KEYS = load_keys()

def check_key(k):
    if k in KEYS:
        KEYS[k]["request_count"] = KEYS[k].get("request_count", 0) + 1
        save_keys(KEYS)
        return True
    return False

@app.route('/health')
def health():
    try:
        r = requests.get("http://localhost:1234/v1/models", timeout=3)
        lm_ok = r.status_code == 200
    except:
        lm_ok = False
    return jsonify({"status": "ok", "lm_studio": "ok" if lm_ok else "down"})

@app.route('/v1/chat/completions', methods=['POST'])
def chat():
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if not api_key or not check_key(api_key):
        return jsonify({"error": "Invalid API Key"}), 401
    
    try:
        data = request.get_json()
        # 增加超时到 5 分钟
        r = requests.post(LM_URL, json=data, timeout=300)
        return jsonify(r.json()), r.status_code
    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    print(f"🚀 Starting on port {port}...")
    app.run(host='0.0.0.0', port=port, threaded=True)