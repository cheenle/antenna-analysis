#!/usr/bin/env python3
"""从 all_records 按小时聚合全球 FT8 指标，小时级 → 2000+ 数据点"""
import mysql.connector, json
conn = mysql.connector.connect(host='ham.vlsc.net', port=9030, user='root', password='', database='pskreporter', charset='utf8mb4')
cur = conn.cursor(dictionary=True)

print("按小时聚合 (2026-02-25+)...")
cur.execute("""
    SELECT DATE_FORMAT(qso_time, '%Y-%m-%d %H:00:00') hr, COUNT(*) spots,
           AVG(snr) snr_avg, MIN(snr) snr_min, MAX(snr) snr_max,
           COUNT(DISTINCT sender_callsign) senders,
           COUNT(DISTINCT receiver_callsign) receivers,
           COUNT(DISTINCT sender_dxcc) dxcc,
           COUNT(DISTINCT frequency) freqs
    FROM all_records WHERE qso_time >= '2026-02-25'
    GROUP BY hr ORDER BY hr
""")
hourly = cur.fetchall()
print(f"聚合完成: {len(hourly)} 小时")

out = [{
    'hour': r['hr'], 'spots': r['spots'],
    'snr_avg': round(float(r['snr_avg']),2),
    'snr_min': int(r['snr_min']), 'snr_max': int(r['snr_max']),
    'senders': r['senders'], 'receivers': r['receivers'],
    'dxcc': r['dxcc'], 'freqs': r['freqs']
} for r in hourly]

with open('/tmp/allspots_hourly.json', 'w') as f:
    json.dump(out, f)

print(f"保存: {len(out)} 小时, {out[0]['hour']} ~ {out[-1]['hour']}")
print(f"每小时平均: {sum(r['spots'] for r in out)/len(out):,.0f} spots")

cur.close(); conn.close()
