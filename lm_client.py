#!/usr/bin/env python3
"""
Shared LM (Language Model) API client — single source of truth.

All AI analysis modules (web_app, ai_analyzer, ai_analyzer_simple) call this
instead of maintaining separate HTTP/SSH logic.
"""

import os
import requests
from typing import Dict, Optional

# Configuration from environment
LM_API_KEY = os.environ.get('LM_API_KEY', '')
LM_API_URL = os.environ.get('LM_API_URL', 'http://ham.vlsc.net:8888')
DEFAULT_MODEL = "qwen/qwen3.5-9b"


def call_lm(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: int = 180,
) -> Dict:
    """Call the remote LM API for inference.

    Returns:
        dict: {"success": bool, "content": str, "model": str, "tokens": int,
               "error": str (if failed)}
    """
    if not LM_API_KEY:
        return {
            "success": False,
            "error": "未配置 LM_API_KEY 环境变量",
            "message": "请联系管理员配置远程 AI 推理服务"
        }

    model_name = model or DEFAULT_MODEL
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": LM_API_KEY
    }

    try:
        response = requests.post(
            f"{LM_API_URL}/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=timeout
        )
        response.raise_for_status()

        result = response.json()
        msg = result.get('choices', [{}])[0].get('message', {})
        content = msg.get('content', '')
        reasoning = msg.get('reasoning_content', '')

        return {
            "success": True,
            "content": content or reasoning or "AI未返回内容",
            "model": model_name,
            "tokens": result.get('usage', {}).get('total_tokens', 0)
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error": "AI 推理超时", "message": "请求超过180秒"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "无法连接到 AI 服务", "message": "请检查 LM_API_URL 配置"}
    except requests.exceptions.HTTPError as e:
        if e.response is not None:
            if e.response.status_code == 401:
                return {"success": False, "error": "API 密钥无效"}
            elif e.response.status_code == 403:
                return {"success": False, "error": "API 密钥无权访问"}
            return {"success": False, "error": f"API 错误: {e.response.status_code}"}
        return {"success": False, "error": f"API 错误: {e}"}
    except Exception as e:
        return {"success": False, "error": "推理失败", "message": str(e)[:100]}


def check_status() -> Dict:
    """Check if the LM API service is reachable."""
    has_key = bool(LM_API_KEY)

    status = {
        "configured": has_key,
        "api_url": LM_API_URL,
        "model": DEFAULT_MODEL
    }

    if has_key:
        try:
            response = requests.get(
                f"{LM_API_URL}/health",
                timeout=5
            )
            data = response.json()
            status["remote_status"] = data.get("status", "unknown")
            status["lm_studio"] = data.get("lm_studio", "unknown")
        except Exception as e:
            status["remote_status"] = "error"
            status["error"] = str(e)[:100]

    return status
