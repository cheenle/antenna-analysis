#!/usr/bin/env python3
"""
LM Studio 远程 API 客户端
用于调用 ham.vlsc.net 上部署的远程推理服务

环境变量:
    LM_API_KEY: API 密钥
    LM_API_URL: API 基础 URL (默认: http://ham.vlsc.net:8888)
"""

import os
import sys
import json
import requests
from typing import List, Dict, Optional, Generator

# ==================== 配置 ====================

DEFAULT_API_URL = "http://ham.vlsc.net:8888"
API_KEY = os.environ.get('LM_API_KEY', '')
API_URL = os.environ.get('LM_API_URL', DEFAULT_API_URL)

# ==================== 客户端类 ====================

class LMRemoteClient:
    """LM Studio 远程 API 客户端"""

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """
        初始化客户端

        Args:
            api_key: API 密钥，默认从环境变量 LM_API_KEY 读取
            api_url: API 地址，默认从环境变量 LM_API_URL 读取
        """
        self.api_key = api_key or API_KEY
        self.api_url = (api_url or API_URL).rstrip('/')

        if not self.api_key:
            raise ValueError("必须提供 API 密钥。请设置环境变量 LM_API_KEY 或传入 api_key 参数")

    def _headers(self) -> Dict[str, str]:
        """构建请求头"""
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }

    def health_check(self) -> Dict:
        """
        检查服务健康状态

        Returns:
            服务状态信息
        """
        try:
            response = requests.get(
                f"{self.api_url}/health",
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def chat(self,
             messages: List[Dict[str, str]],
             model: str = "qwen/qwen3.5-9b",
             temperature: float = 0.7,
             max_tokens: int = 1024,
             stream: bool = False) -> Dict:
        """
        聊天补全

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            stream: 是否流式返回

        Returns:
            API 响应
        """
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        response = requests.post(
            f"{self.api_url}/v1/chat/completions",
            headers=self._headers(),
            json=data,
            timeout=180
        )

        response.raise_for_status()
        return response.json()

    def chat_simple(self, prompt: str, **kwargs) -> str:
        """
        简单聊天（只返回文本内容）

        Args:
            prompt: 提示词
            **kwargs: 其他参数

        Returns:
            生成的文本
        """
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages, **kwargs)

        try:
            return response['choices'][0]['message']['content']
        except (KeyError, IndexError):
            return json.dumps(response, indent=2, ensure_ascii=False)

    def stream_chat(self,
                    messages: List[Dict[str, str]],
                    model: str = "qwen/qwen3.5-9b",
                    **kwargs) -> Generator[str, None, None]:
        """
        流式聊天

        Args:
            messages: 消息列表
            model: 模型名称
            **kwargs: 其他参数

        Yields:
            生成的文本片段
        """
        data = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs
        }

        response = requests.post(
            f"{self.api_url}/v1/chat/completions",
            headers=self._headers(),
            json=data,
            stream=True,
            timeout=180
        )

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get('choices', [{}])[0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        pass

    def list_models(self) -> List[Dict]:
        """
        获取可用模型列表

        Returns:
            模型列表
        """
        response = requests.get(
            f"{self.api_url}/v1/models",
            headers=self._headers(),
            timeout=10
        )
        response.raise_for_status()
        return response.json().get('data', [])


# ==================== 便捷函数 ====================

def query_remote(prompt: str, timeout: int = 180, **kwargs) -> str:
    """
    快速调用远程 LM API（简化版）

    Args:
        prompt: 提示词
        timeout: 超时时间
        **kwargs: 其他参数

    Returns:
        生成的文本
    """
    client = LMRemoteClient()
    return client.chat_simple(prompt, **kwargs)


def analyze_propagation_remote(days: int = 7) -> str:
    """
    使用远程 API 分析传播条件

    Args:
        days: 分析过去几天的数据

    Returns:
        AI 分析结果
    """
    import mysql.connector

    # 数据库配置
    DB_CONFIG = {
        "host": "ham.vlsc.net",
        "port": 9030,
        "user": "root",
        "password": "",
        "database": "pskreporter"
    }

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        # 获取 QSO 统计
        cursor.execute(f"""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT callsign) as unique_calls,
                   COUNT(DISTINCT country) as unique_countries,
                   AVG(distance) as avg_distance
            FROM qso_log
            WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
        """)
        qso = cursor.fetchone()

        # 获取波段分布
        cursor.execute(f"""
            SELECT band, COUNT(*) as count
            FROM qso_log
            WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
            GROUP BY band
            ORDER BY count DESC
            LIMIT 8
        """)
        bands = cursor.fetchall()

        cursor.close()
        conn.close()

        bands_str = "\n".join([f"- {b.get('band', 'N/A')}: {b.get('count', 0)} 次" for b in bands])

        prompt = f"""作为业余无线电传播专家，请分析以下数据：

## 最近 {days} 天 QSO 统计
- 总通联: {qso.get('total', 0)} 次
- 独特呼号: {qso.get('unique_calls', 0)}
- 通联国家: {qso.get('unique_countries', 0)}
- 平均距离: {round(qso.get('avg_distance', 0), 0)} km

## 波段分布
{bands_str}

请提供：
1. 当前传播条件评估（优秀/良好/一般/较差）
2. 最佳操作波段建议
3. 操作建议

请用中文简洁回复。"""

        return query_remote(prompt)

    except Exception as e:
        return f"分析失败: {e}"


# ==================== 命令行接口 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='LM Studio 远程 API 客户端')
    parser.add_argument('prompt', nargs='?', help='提示词（直接输入）')
    parser.add_argument('--file', '-f', help='从文件读取提示词')
    parser.add_argument('--stream', '-s', action='store_true', help='流式输出')
    parser.add_argument('--model', '-m', default='qwen/qwen3.5-9b', help='模型名称')
    parser.add_argument('--temperature', '-t', type=float, default=0.7, help='温度参数')
    parser.add_argument('--max-tokens', type=int, default=1024, help='最大 token 数')
    parser.add_argument('--health', action='store_true', help='检查服务健康状态')
    parser.add_argument('--list-models', action='store_true', help='列出可用模型')
    parser.add_argument('--analyze', choices=['propagation'], help='执行特定分析')

    args = parser.parse_args()

    # 创建客户端
    try:
        client = LMRemoteClient()
    except ValueError as e:
        print(f"错误: {e}")
        print("\n请设置环境变量:")
        print("  export LM_API_KEY='your-api-key'")
        print("  export LM_API_URL='http://ham.vlsc.net:8888'")
        sys.exit(1)

    # 检查健康状态
    if args.health:
        status = client.health_check()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return

    # 列出模型
    if args.list_models:
        models = client.list_models()
        print("可用模型:")
        for model in models:
            print(f"  - {model.get('id', 'unknown')}")
        return

    # 执行特定分析
    if args.analyze == 'propagation':
        print("正在分析传播条件...")
        result = analyze_propagation_remote()
        print(result)
        return

    # 获取提示词
    prompt = None
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            prompt = f.read()
    elif args.prompt:
        prompt = args.prompt
    else:
        # 交互模式
        print("请输入提示词 (Ctrl+D 结束):")
        lines = []
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        prompt = '\n'.join(lines)

    if not prompt or not prompt.strip():
        print("错误: 提示词不能为空")
        sys.exit(1)

    # 发送请求
    try:
        if args.stream:
            print("正在生成...", end='', flush=True)
            for chunk in client.stream_chat(
                [{"role": "user", "content": prompt}],
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens
            ):
                print(chunk, end='', flush=True)
            print()
        else:
            print("正在生成...", end='', flush=True)
            response = client.chat_simple(
                prompt,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens
            )
            print("\r" + " " * 20 + "\r", end='')
            print(response)

    except requests.exceptions.HTTPError as e:
        print(f"\nAPI 错误: {e}")
        if e.response.status_code == 401:
            print("API 密钥无效或缺失")
        elif e.response.status_code == 403:
            print("API 密钥无权访问此资源")
    except Exception as e:
        print(f"\n错误: {e}")


if __name__ == '__main__':
    main()
