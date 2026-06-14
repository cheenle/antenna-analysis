#!/usr/bin/env python3
"""Check data structure and band/continent distribution for SNR analysis"""
import mysql.connector
import sys
sys.path.insert(0, '/Users/cheenle/pskreporter')
from band_utils import CASE_BAND_SQL

conn = mysql.connector.connect(host='ham.vlsc.net', port=9030, user='root', password='', database='pskreporter', charset='utf8mb4')
cur = conn.cursor(dictionary=True)

# Table structure
cur.execute('DESCRIBE all_records')
print('=== all_records columns ===')
for row in cur.fetchall():
    print(f'  {row["Field"]:30s} {row["Type"]:20s}')

# Band distribution
cur.execute(f'''
    SELECT {CASE_BAND_SQL} as band, 
           COUNT(*) cnt, AVG(snr) avg_snr, COUNT(DISTINCT sender_callsign) senders
    FROM all_records
    WHERE qso_time >= '2026-02-25'
    GROUP BY band ORDER BY cnt DESC
''')
print('\n=== Band distribution ===')
for row in cur.fetchall():
    print(f'  {row["band"]:10s} spots={row["cnt"]:>12,d}  avg_snr={row["avg_snr"]:>7.2f}  senders={row["senders"]:>7,d}')

# Total
cur.execute("SELECT COUNT(*) cnt FROM all_records WHERE qso_time >= '2026-02-25'")
total = cur.fetchone()['cnt']
print(f'\nTotal spots 2026-02-25+: {total:,d}')

# Date range
cur.execute("SELECT MIN(qso_time) mn, MAX(qso_time) mx FROM all_records WHERE qso_time >= '2026-02-25'")
r = cur.fetchone()
print(f'Date range: {r["mn"]} ~ {r["mx"]}')

cur.close()
conn.close()
