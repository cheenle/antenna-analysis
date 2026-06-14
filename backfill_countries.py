#!/usr/bin/env python3
"""回填 qso_log.country — 按 country 分组批量UPDATE，高效版"""
import mysql.connector
from collections import defaultdict
from dxcc_lookup import lookup_callsign

conn = mysql.connector.connect(
    host='ham.vlsc.net', port=9030, user='root', password='',
    database='pskreporter', charset='utf8mb4', 
    connect_timeout=10, autocommit=False
)
cur = conn.cursor(dictionary=True)

# 1. 获取 NULL country 的 distinct callsigns
print("Fetching NULL-country callsigns...")
cur.execute("SELECT DISTINCT callsign FROM qso_log WHERE station_callsign = 'BG1SB' AND country IS NULL")
callsigns = [row['callsign'] for row in cur.fetchall()]
print(f"待处理 unique callsigns: {len(callsigns)}")

# 2. 解析并构建 country -> [callsigns] 映射
print("Looking up callsigns...")
by_country = defaultdict(list)
unresolved = []
for cs in callsigns:
    r = lookup_callsign(cs)
    if r:
        by_country[r['name']].append(cs)
    else:
        unresolved.append(cs)

print(f"已解析: {len(callsigns)-len(unresolved)} callsigns -> {len(by_country)} countries, 未解析: {len(unresolved)}")

# 3. 按 country 批量 UPDATE（一次 SQL 更新一个 country 的所有 callsigns）
print("Updating database...")
total_updated = 0
for country, cs_list in sorted(by_country.items()):
    # Batch callsigns in chunks of 500 for the IN clause
    for i in range(0, len(cs_list), 500):
        chunk = cs_list[i:i+500]
        placeholders = ','.join(['%s'] * len(chunk))
        sql = f"UPDATE qso_log SET country = %s WHERE station_callsign = 'BG1SB' AND callsign IN ({placeholders}) AND country IS NULL"
        cur.execute(sql, [country] + chunk)
        total_updated += cur.rowcount
    conn.commit()
    if total_updated % 2000 == 0:
        print(f"  已更新 {total_updated} 条...")

print(f"\n回填完成，共更新 {total_updated} 条")

# 4. 验证
cur.execute("SELECT COUNT(DISTINCT country) as cnt FROM qso_log WHERE station_callsign = 'BG1SB' AND country IS NOT NULL")
new_cnt = cur.fetchone()['cnt']
cur.execute("SELECT COUNT(*) as cnt FROM qso_log WHERE station_callsign = 'BG1SB' AND country IS NULL")
null_cnt = cur.fetchone()['cnt']
print(f"DISTINCT country: {new_cnt}, 仍有NULL: {null_cnt}")

if unresolved:
    print(f"\n未解析呼号 ({len(unresolved)}):")
    for cs in sorted(unresolved)[:30]:
        print(f"  {cs}")

cur.close()
conn.close()
