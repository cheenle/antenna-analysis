#!/usr/bin/env python3
"""
快速数据采集 - 每小时运行
采集：太阳风、Kp指数
"""

import mysql.connector
import json
import urllib.request
import datetime
import math
import sys

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def main():
    log("="*60)
    log("🚀 快速数据采集开始")
    log("="*60)
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    total_inserted = 0
    
    # 1. 太阳风数据
    log("[1/2] 采集太阳风...")
    try:
        url_mag = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
        url_plasma = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
        
        req1 = urllib.request.Request(url_mag, headers={"User-Agent": "Collector/1.0"})
        req2 = urllib.request.Request(url_plasma, headers={"User-Agent": "Collector/1.0"})
        
        with urllib.request.urlopen(req1, timeout=30) as r1:
            mag_data = json.loads(r1.read().decode())
        with urllib.request.urlopen(req2, timeout=30) as r2:
            plasma_data = json.loads(r2.read().decode())
        
        # 构建等离子体字典
        plasma_dict = {}
        for p in plasma_data[1:]:
            if len(p) >= 3:
                plasma_dict[p[0][:16]] = {
                    'density': float(p[1]) if p[1] else None,
                    'speed': float(p[2]) if p[2] else None
                }
        
        # 插入最近1小时的数据（6条，每10分钟一条）
        inserted = 0
        for item in mag_data[1:][-6:]:
            if len(item) >= 4:
                try:
                    time_str = item[0][:19]
                    bx = float(item[1]) if item[1] else 0
                    by = float(item[2]) if item[2] else 0
                    bz = float(item[3]) if item[3] else 0
                    bt = math.sqrt(bx**2 + by**2 + bz**2)
                    
                    plasma = plasma_dict.get(item[0][:16], {})
                    density = plasma.get('density')
                    speed = plasma.get('speed')
                    
                    cursor.execute("""
                        INSERT INTO solar_wind (measurement_time, proton_density, proton_speed, bt, bz, satellite)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (time_str, density, speed, bt, bz, 'DSCOVR'))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
        
        conn.commit()
        log(f"  ✓ 插入 {inserted} 条太阳风记录")
        total_inserted += inserted
    except Exception as e:
        log(f"  ✗ 失败: {e}")
    
    # 2. Kp指数
    log("[2/2] 采集Kp指数...")
    try:
        url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Collector/1.0"})
        
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        
        inserted = 0
        for item in data[1:][-6:]:  # 最近6个预报点
            if len(item) >= 2:
                try:
                    time_str = item[0][:19]
                    kp = float(item[1]) if item[1] else None
                    date_str = time_str[:10]
                    
                    if kp is not None:
                        if kp < 5:
                            level, desc = 'G0', '平静'
                        elif kp < 6:
                            level, desc = 'G1', '小磁暴'
                        elif kp < 7:
                            level, desc = 'G2', '中等磁暴'
                        elif kp < 8:
                            level, desc = 'G3', '强磁暴'
                        else:
                            level, desc = 'G4', '严重磁暴'
                        
                        cursor.execute("""
                            INSERT INTO geomagnetic_indices (measurement_time, measurement_date, kp_value, storm_level, storm_description)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (time_str, date_str, kp, level, desc))
                        inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
        
        conn.commit()
        log(f"  ✓ 插入 {inserted} 条Kp记录")
        total_inserted += inserted
    except Exception as e:
        log(f"  ✗ 失败: {e}")
    
    cursor.close()
    conn.close()
    
    log("="*60)
    log(f"✅ 完成! 共插入 {total_inserted} 条记录")
    log("="*60)

if __name__ == '__main__':
    main()
