#!/usr/bin/env python3
"""
LM API 配置向导
交互式配置并测试远程 AI 推理
"""

import os
import sys
import requests

def test_connection(api_url, api_key):
    """测试 API 连接"""
    try:
        response = requests.get(
            f"{api_url}/health",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return True, f"服务正常 - LM Studio: {data.get('lm_studio', 'unknown')}"
        return False, f"HTTP {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "无法连接到服务器"
    except Exception as e:
        return False, str(e)

def test_auth(api_url, api_key):
    """测试 API 认证"""
    try:
        response = requests.post(
            f"{api_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key
            },
            json={
                "model": "qwen/qwen3.5-9b",
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 50
            },
            timeout=30
        )
        if response.status_code == 200:
            return True, "认证成功"
        elif response.status_code == 401:
            return False, "API 密钥无效"
        elif response.status_code == 403:
            return False, "API 密钥无权访问"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def main():
    print("=" * 60)
    print("🤖 LM Studio 远程 API 配置向导")
    print("=" * 60)
    
    # 检查现有配置
    env_file = ".env.lm.api"
    current_key = os.environ.get('LM_API_KEY', '')
    current_url = os.environ.get('LM_API_URL', 'http://ham.vlsc.net:8888')
    
    if os.path.exists(env_file):
        print(f"\n📄 发现配置文件: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                if 'LM_API_KEY' in line and '=' in line:
                    parts = line.strip().split('=', 1)
                    if len(parts) == 2:
                        current_key = parts[1].strip("'\"")
    
    # 输入 API URL
    print(f"\n🌐 API 服务端地址")
    print(f"当前: {current_url}")
    new_url = input("输入新地址 (直接回车保持当前): ").strip()
    api_url = new_url if new_url else current_url
    
    # 输入 API Key
    print(f"\n🔑 API 密钥")
    if current_key and current_key != 'lm_xxxxxxxxxxxxxxxx':
        print(f"当前: {current_key[:20]}...")
    print("如何获取密钥:")
    print("  1. SSH 到 ham.vlsc.net: ssh cheenle@ham.vlsc.net")
    print("  2. 查看密钥: cat ~/.lm_api_key.txt")
    print("  3. 或运行: python3 ~/lm_api_server/lm_api_server.py --list-keys")
    
    new_key = input("\n输入 API 密钥 (直接回车保持当前): ").strip()
    api_key = new_key if new_key else current_key
    
    if not api_key or api_key == 'lm_xxxxxxxxxxxxxxxx':
        print("\n❌ 错误: 必须提供有效的 API 密钥")
        sys.exit(1)
    
    # 保存配置
    print(f"\n💾 保存配置到 {env_file}...")
    with open(env_file, 'w') as f:
        f.write(f"""# LM Studio 远程 API 配置
# 自动生成于配置向导

export LM_API_KEY='{api_key}'
export LM_API_URL='{api_url}'
""")
    
    # 设置环境变量
    os.environ['LM_API_KEY'] = api_key
    os.environ['LM_API_URL'] = api_url
    
    print(f"✅ 配置已保存")
    
    # 测试连接
    print(f"\n🧪 测试连接...")
    success, msg = test_connection(api_url, api_key)
    if success:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
        print("  请检查:")
        print("    - ham.vlsc.net 上的服务是否已启动")
        print("    - 防火墙是否放行 8888 端口")
        print("    - 网络连接是否正常")
    
    # 测试认证
    print(f"\n🔐 测试 API 认证...")
    success, msg = test_auth(api_url, api_key)
    if success:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
        print("  请检查 API 密钥是否正确")
    
    # 如果都通过，生成测试报告
    if success:
        print(f"\n🎉 配置成功！")
        print(f"\n快速开始:")
        print(f"  1. 加载配置: source {env_file}")
        print(f"  2. 生成报告: python3 ai_report_generator.py")
        print(f"  3. 快速测试: python3 lm_remote_client.py '你好'")
        
        # 询问是否立即生成报告
        answer = input(f"\n是否立即生成一份测试报告? (y/N): ").strip().lower()
        if answer == 'y':
            print(f"\n正在生成测试报告...")
            os.system("python3 ai_report_generator.py --type propagation --days 1")
    else:
        print(f"\n⚠️  配置已保存但测试未通过")
        print(f"请修复问题后重新运行本向导")

if __name__ == '__main__':
    main()
