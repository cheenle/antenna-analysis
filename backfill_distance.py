#!/usr/bin/env python3
"""回填 distance — 单条 UPDATE CASE WHEN 避免 StarRocks version 爆炸"""
import math
import mysql.connector

def grid_to_latlon(grid):
    if not grid or len(grid) < 4: return None
    grid = grid.upper()
    try:
        lon1 = ord(grid[0]) - ord('A'); lat1 = ord(grid[1]) - ord('A')
        lon2 = int(grid[2]); lat2 = int(grid[3])
        lon3 = lat3 = 0
        if len(grid) >= 6:
            lon3 = ord(grid[4].lower()) - ord('a')
            lat3 = ord(grid[5].lower()) - ord('a')
        lon = -180 + lon1*20 + lon2*2 + lon3*(2/24) + 1/24
        lat = -90 + lat1*10 + lat2*1 + lat3*(1/24) + 1/48
        return (round(lat,4), round(lon,4))
    except: return None

def calc(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(lat1_r)*math.cos(lat2_r)*math.sin(dlon/2)**2
    d = 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))
    x = math.sin(dlon)*math.cos(lat2_r)
    y = math.cos(lat1_r)*math.sin(lat2_r) - math.sin(lat1_r)*math.cos(lat2_r)*math.cos(dlon)
    b = (math.degrees(math.atan2(x, y)) + 360) % 360
    return (round(d,1), round(b,1))

conn = mysql.connector.connect(
    host='ham.vlsc.net', port=9030, user='root', password='',
    database='pskreporter', charset='utf8mb4', connect_timeout=30
)
cur = conn.cursor(dictionary=True)

cur.execute('''
    SELECT id, grid_locator, my_grid_locator 
    FROM qso_log WHERE station_callsign='BG1SB' 
    AND grid_locator IS NOT NULL AND my_grid_locator IS NOT NULL AND distance IS NULL
''')
rows = cur.fetchall()
print(f"待计算: {len(rows)}")

grid_cache = {}
pairs = []
for row in rows:
    g1, g2 = row['grid_locator'], row['my_grid_locator']
    if g1 not in grid_cache: grid_cache[g1] = grid_to_latlon(g1)
    if g2 not in grid_cache: grid_cache[g2] = grid_to_latlon(g2)
    loc1, loc2 = grid_cache[g1], grid_cache[g2]
    if loc1 and loc2:
        dist, bear = calc(loc2[0], loc2[1], loc1[0], loc1[1])
        pairs.append((row['id'], dist, bear))

print(f"可计算: {len(pairs)}")

# 每200条一个 batch UPDATE（用 CASE WHEN，一次SQL只产生一个version）
BATCH = 200
for i in range(0, len(pairs), BATCH):
    batch = pairs[i:i+BATCH]
    ids = [p[0] for p in batch]
    dist_cases = ' '.join([f'WHEN {p[0]} THEN {p[1]}' for p in batch])
    bear_cases = ' '.join([f'WHEN {p[0]} THEN {p[2]}' for p in batch])
    id_list = ','.join(str(x) for x in ids)
    
    sql = f"UPDATE qso_log SET distance = CASE id {dist_cases} END, bearing = CASE id {bear_cases} END WHERE id IN ({id_list})"
    cur.execute(sql)
    conn.commit()
    print(f"  {min(i+BATCH, len(pairs))}/{len(pairs)}")

cur.execute("SELECT COUNT(*) as cnt, MAX(distance) as maxd, AVG(distance) as avgd FROM qso_log WHERE station_callsign='BG1SB' AND distance IS NOT NULL")
s = cur.fetchone()
print(f"完成! 有distance: {s['cnt']}, 最远: {s['maxd']:.0f}km, 平均: {s['avgd']:.0f}km")
cur.close(); conn.close()
