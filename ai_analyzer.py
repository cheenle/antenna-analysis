#!/usr/bin/env python3
"""
AI 深度分析模块
基于 LM Studio qwen3.5-9b 大模型进行深度传播分析

支持两种调用方式:
1. 本地/SSH 直连: 直接连接 LM Studio (localhost:1234)
2. 远程 API: 通过 HTTP API 调用 (需要 LM_API_KEY 环境变量)

环境变量:
    LM_API_KEY: 远程 API 密钥（如果使用远程模式）
    LM_API_URL: 远程 API 地址（默认: http://ham.vlsc.net:8888）
"""

import json
import datetime
import os
from typing import Dict

from lm_client import call_lm, DEFAULT_MODEL

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


def query_lm(prompt: str, timeout: int = 180) -> str:
    """调用 LM API 进行推理（兼容旧接口，返回字符串）"""
    result = call_lm(prompt, timeout=timeout)
    if result.get("success"):
        return result.get("content", "").strip()
    return result.get("error", "AI调用失败")


def get_data_summary(days: int = 7) -> Dict:
    """获取数据摘要"""
    import mysql.connector
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    summary = {}
    
    cursor.execute(f"""
        SELECT COUNT(*) as total, 
               COUNT(DISTINCT callsign) as unique_calls,
               COUNT(DISTINCT country) as unique_countries,
               AVG(distance) as avg_distance
        FROM qso_log 
        WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
    """)
    summary['qso'] = cursor.fetchone()
    
    cursor.execute(f"""
        SELECT band, COUNT(*) as count 
        FROM qso_log 
        WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
        GROUP BY band 
        ORDER BY count DESC 
        LIMIT 10
    """)
    summary['bands'] = cursor.fetchall()
    
    cursor.execute("SELECT * FROM solar_activity ORDER BY observation_date DESC LIMIT 7")
    summary['solar'] = cursor.fetchall()
    
    cursor.execute("SELECT * FROM geomagnetic_indices ORDER BY measurement_date DESC LIMIT 7")
    summary['geomag'] = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return summary


def analyze_propagation(days: int = 7) -> str:
    """分析传播条件"""
    data = get_data_summary(days)
    qso = data.get('qso', {})
    bands = data.get('bands', [])
    
    bands_str = "\n".join([f"- {b.get('band', 'N/A')}: {b.get('count', 0)} 次" for b in bands[:8]])
    
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

    return query_lm(prompt)


def analyze_space_weather() -> str:
    """分析空间天气影响"""
    data = get_data_summary(7)
    solar = data.get('solar', [])
    geomag = data.get('geomag', [])
    
    latest_solar = solar[0] if solar else {}
    latest_geomag = geomag[0] if geomag else {}
    
    prompt = f"""作为空间天气分析师，请分析：

## 太阳活动
- F10.7: {latest_solar.get('f107_flux', 'N/A')}
- 太阳黑子: {latest_solar.get('sunspot_number', 'N/A')}

## 地磁状态
- Kp指数: {latest_geomag.get('kp_value', 'N/A')}
- 等级: {latest_geomag.get('storm_level', 'N/A')}

请分析对短波传播的影响和操作建议。用中文。"""

    return query_lm(prompt)


def analyze_dxcc() -> str:
    """分析DXCC进度"""
    import mysql.connector
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT country, COUNT(*) as count 
        FROM qso_log 
        GROUP BY country 
        ORDER BY count DESC 
        LIMIT 20
    """)
    dxcc = cursor.fetchall()
    cursor.close()
    conn.close()
    
    dxcc_str = "\n".join([f"- {d.get('country', 'N/A')}: {d.get('count', 0)} 次" for d in dxcc[:15]])
    
    prompt = f"""作为DXCC专家，请分析：

## 已通联国家
{dxcc_str}

请给出：
1. DXCC进度评估
2. 建议攻克的国家
3. 基于当前传播条件的可行性

用中文回复。"""

    return query_lm(prompt)


def generate_report() -> str:
    """生成完整AI分析报告"""
    print("正在生成AI分析报告...")
    
    print("  - 分析传播条件...")
    propagation = analyze_propagation(7)
    
    print("  - 分析空间天气...")
    space_weather = analyze_space_weather()
    
    print("  - 分析DXCC进度...")
    dxcc = analyze_dxcc()
    
    os.makedirs("visualizations", exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"ai_analysis_{timestamp}.html"
    filepath = os.path.join("visualizations", filename)
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>AI 深度传播分析报告</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: #fff;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{
            text-align: center;
            background: linear-gradient(45deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .section {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .ai-content {{
            background: rgba(0,210,255,0.05);
            padding: 15px;
            border-radius: 8px;
            white-space: pre-wrap;
            line-height: 1.8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 AI 深度传播分析报告</h1>
        <p style="text-align:center;color:#888">基于 qwen3.5-9b | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <div class="section">
            <h2>📡 传播条件分析</h2>
            <div class="ai-content">{propagation}</div>
        </div>
        
        <div class="section">
            <h2>🌌 空间天气影响</h2>
            <div class="ai-content">{space_weather}</div>
        </div>
        
        <div class="section">
            <h2>🌍 DXCC 进度分析</h2>
            <div class="ai-content">{dxcc}</div>
        </div>
    </div>
</body>
</html>'''
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"报告已生成: {filepath}")
    return filepath


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'propagation':
            print(analyze_propagation(7))
        elif cmd == 'space_weather':
            print(analyze_space_weather())
        elif cmd == 'dxcc':
            print(analyze_dxcc())
        else:
            generate_report()
    else:
        generate_report()
