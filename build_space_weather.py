#!/usr/bin/env python3
"""Merge sunspot + Kp into space_weather_daily"""
import mysql.connector, urllib.request
from collections import defaultdict

c = mysql.connector.connect(host='ham.vlsc.net',port=9030,user='root',password='',database='pskreporter')
cur = c.cursor()

# Delete old sunspot-only rows
cur.execute("DELETE FROM space_weather_daily WHERE daily_kp_avg IS NULL")
c.commit()
print("Cleaned old rows")

# Fetch sunspot data
url = 'https://www.sidc.be/SILSO/DATA/SN_d_tot_V2.0.csv'
with urllib.request.urlopen(url, timeout=60) as r:
    lines = r.read().decode().split('\n')

sn = {}
for line in lines:
    p = line.strip().split(';')
    if len(p) < 5: continue
    try:
        yr, mo, dy = int(p[0]), int(p[1]), int(p[2])
        sn_val = round(float(p[4]), 2)
        dt = f"{yr:04d}-{mo:02d}-{dy:02d}"
        sn[dt] = sn_val
    except: continue
print(f"Sunspot: {len(sn)} days")

# Fetch Kp data
url2 = 'https://www-app3.gfz-potsdam.de/kp_index/Kp_ap_since_1932.txt'
with urllib.request.urlopen(url2, timeout=60) as r:
    kp_lines = r.read().decode().split('\n')

kp = defaultdict(lambda: {'sum': 0.0, 'cnt': 0})
for line in kp_lines:
    if line.startswith('#'): continue
    p = line.split()
    if len(p) < 9: continue
    try:
        yr, mo, dy = int(p[0]), int(p[1]), int(p[2])
        kp_val = float(p[7])
        dt = f"{yr:04d}-{mo:02d}-{dy:02d}"
        kp[dt]['sum'] += kp_val
        kp[dt]['cnt'] += 1
    except: continue
print(f"Kp: {len(kp)} days")

# Merge and INSERT
merged = 0; batch = []
for dt in kp:
    if dt in sn:
        kp_avg = round(kp[dt]['sum'] / kp[dt]['cnt'], 1)
        batch.append((dt, sn[dt], kp_avg))
        merged += 1
        if len(batch) >= 2000:
            cur.executemany(
                "INSERT INTO space_weather_daily (summary_date, daily_sunspot_avg, daily_kp_avg) VALUES (%s, %s, %s)",
                batch)
            batch = []
if batch:
    cur.executemany(
        "INSERT INTO space_weather_daily (summary_date, daily_sunspot_avg, daily_kp_avg) VALUES (%s, %s, %s)",
        batch)
c.commit()
print(f"Merged: {merged} days inserted")

# Verify
cur.execute("SELECT COUNT(*), MIN(summary_date), MAX(summary_date) FROM space_weather_daily WHERE daily_sunspot_avg IS NOT NULL AND daily_kp_avg IS NOT NULL")
r = cur.fetchone()
print(f"Total: {r[0]:,} days, {r[1]} ~ {r[2]}")

cur.execute("SELECT COUNT(*) FROM space_weather_daily WHERE summary_date >= '2025-01-01' AND summary_date <= '2026-05-31' AND daily_sunspot_avg IS NOT NULL AND daily_kp_avg IS NOT NULL")
print(f"2025-2026 overlap: {cur.fetchone()[0]} days")

cur.execute("SELECT summary_date, daily_sunspot_avg, daily_kp_avg FROM space_weather_daily WHERE summary_date >= '2025-01-01' AND summary_date <= '2025-01-05' ORDER BY summary_date")
print("Sample:")
for r in cur.fetchall():
    print(f"  {r[0]}  sunspot={r[1]}  Kp={r[2]}")

cur.close(); c.close()
