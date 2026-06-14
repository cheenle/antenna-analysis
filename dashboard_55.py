#!/usr/bin/env python3
"""5.5 通联看板 - 动态从 StarRocks 读取 BG1SB 通联数据"""

import json
import mysql.connector
from flask import Flask, render_template, jsonify

app = Flask(__name__)

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter",
    "charset": "utf8mb4",
}

# 5.5 活动波段: HF 波段 + VHF/UHF
HF = ['80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m']
BANDS = HF + ['6m', '2m']
BN = [f'B{i}CRA' for i in range(10)]


def get_data():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT callsign, band, mode, "
        "GROUP_CONCAT(DISTINCT DATE_FORMAT(qso_time, '%Y-%m-%d %H:%i') "
        "ORDER BY qso_time SEPARATOR ', ') as dates "
        "FROM qso_log "
        "WHERE callsign REGEXP '^B[0-9]CRA$' "
        "AND qso_date >= '2026-01-01' "
        "GROUP BY callsign, band, mode "
        "ORDER BY band, callsign"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.route('/')
def dashboard():
    return render_template('dashboard_55.html',
                           hf_json=json.dumps(HF),
                           bands_json=json.dumps(BANDS))


@app.route('/api/data')
def api_data():
    data = get_data()
    return jsonify(data)


if __name__ == '__main__':
    print('看板地址: http://localhost:5555')
    app.run(host='::', port=5555, debug=False)
