#!/usr/bin/env python3
"""5.5 通联看板 SSB 版 - 从 RumLogNG SQLite 实时读取"""

import json
import sqlite3
import os
from flask import Flask, render_template, jsonify
from datetime import datetime, timezone

app = Flask(__name__)

RUMLOG_DB = os.path.expanduser(
    "~/Library/Containers/de.dl2rum.RUMlogNG/Data/Library/"
    "Application Support/RUMlogNG/CoreQsoModel_1.sqlite"
)

# 5.5 活动波段: HF 波段 + VHF/UHF
HF = ['80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m']
BANDS = HF + ['6m', '2m']
BN = [f'B{i}CRA' for i in range(10)]

# Core Data 时间戳参考日期 (2001-01-01 00:00:00 UTC)
CD_REF = 978307200


def get_data():
    """从 RumLogNG 读取所有 BnCRA SSB QSO"""
    conn = sqlite3.connect(RUMLOG_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取所有 BnCRA SSB 通联 (Unix epoch > 2025-12-31)
    offset = CD_REF
    cur.execute(f"""
        SELECT ZCALLSIGN as callsign,
               ZBAND as band,
               ZMODE as mode,
               ZDATETIME + {offset} as unix_ts,
               ZRSTRX as rst_rx,
               ZRSTTX as rst_tx
        FROM ZCORE_QSO
        WHERE ZCALLSIGN LIKE 'B_CRA'
          AND ZMODE = 'SSB'
          AND (ZDATETIME + {offset}) >= 1735689600
        ORDER BY ZDATETIME
    """)

    rows = []
    for r in cur.fetchall():
        dt = datetime.fromtimestamp(int(r['unix_ts']), tz=timezone.utc)
        date_str = dt.strftime('%Y-%m-%d %H:%M')
        key = f"{r['callsign']}|{r['band']}|{r['mode']}"
        rows.append({
            'callsign': r['callsign'],
            'band': r['band'],
            'mode': r['mode'],
            'dates': date_str,
            'rst_rx': r['rst_rx'],
            'rst_tx': r['rst_tx'],
        })

    # 合并同一呼号/波段/模式的记录
    merged = {}
    for row in rows:
        key = f"{row['callsign']}|{row['band']}|{row['mode']}"
        if key not in merged:
            merged[key] = {
                'callsign': row['callsign'],
                'band': row['band'],
                'mode': row['mode'],
                'dates': [],
            }
        merged[key]['dates'].append(row['dates'])

    result = []
    for key, val in merged.items():
        val['dates'] = ', '.join(sorted(val['dates']))
        result.append(val)

    result.sort(key=lambda x: (x['callsign'], BANDS.index(x['band']) if x['band'] in BANDS else 99))
    conn.close()
    return result


@app.route('/')
def dashboard():
    return render_template('dashboard_55_ssb.html',
                           hf_json=json.dumps(HF),
                           bands_json=json.dumps(BANDS))


@app.route('/api/data')
def api_data():
    data = get_data()
    return jsonify(data)


if __name__ == '__main__':
    print('SSB 看板地址: http://localhost:5556')
    app.run(host='::', port=5556, debug=False)
