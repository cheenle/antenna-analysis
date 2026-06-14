#!/usr/bin/env python3
"""每 5 分钟自动同步 JTDX 日志到数据库"""

import subprocess
import os
import sys
import time

JTDX_LOG = os.path.expanduser("~/Library/Application Support/JTDX/wsjtx_log.adi")
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wsjtx_log_import.py")

def sync():
    if not os.path.exists(JTDX_LOG):
        print(f"[{time.strftime('%H:%M:%S')}] JTDX 日志不存在: {JTDX_LOG}")
        return
    try:
        result = subprocess.run(
            [sys.executable, SCRIPT, "--file", JTDX_LOG],
            capture_output=True, text=True, timeout=60
        )
        # Show last few lines of output
        lines = result.stdout.strip().split('\n')
        new_lines = [l for l in lines if '新导入' in l or '已导入' in l]
        msg = ' '.join(new_lines) if new_lines else '无新数据'
        print(f"[{time.strftime('%H:%M:%S')}] 同步: {msg}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 同步失败: {e}")

if __name__ == '__main__':
    print(f"开始 JTDX 自动同步 (每 5 分钟)")
    print(f"日志文件: {JTDX_LOG}")
    while True:
        sync()
        time.sleep(300)  # 5 minutes
