#!/usr/bin/env python3
"""
每日数据采集 - 每天凌晨运行
采集：F10.7、太阳黑子
"""

import mysql.connector
import json
import urllib.request
import datetime
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
    log("🌞 每日数据采集开始")
    log("="*60)
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    total_inserted = 0
    
    # 1. F10.7数据
    log("[1/2] 采集F10.7...")
    try:
        url = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Collector/1.0"})
        
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        
        # 获取最近7天
        seen = set()
        inserted = 0
        
        for d in data[-21:]:  # 最近21条（约7天）
            date_str = d['time_tag'][:10]
            if date_str not in seen:
                seen.add(date_str)
                try:
                    flux = float(d['flux'])
                    cursor.execute(
                        "INSERT INTO solar_activity (observation_date, f107_flux, data_source) VALUES (%s, %s, %s)",
                        (date_str, flux, 'NOAA')
                    )
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    # 更新已有记录
                    cursor.execute(
                        "UPDATE solar_activity SET f107_flux = %s WHERE observation_date = %s",
                        (float(d['flux']), date_str)
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
        
        conn.commit()
        log(f"  ✓ 插入/更新 {inserted} 条F10.7记录")
        total_inserted += inserted
    except Exception as e:
        log(f"  ✗ 失败: {e}")
    
    # 2. 太阳黑子（文件大，简单处理）
    log("[2/2] 采集太阳黑子...")
    try:
        url = "http://www.sidc.be/silso/DATA/SN_d_tot_V2.0.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Collector/1.0"})
        
        with urllib.request.urlopen(req, timeout=60) as r:
            lines = r.read().decode('utf-8').strip().split('\n')
        
        # 只处理最近7天
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=7)
        
        inserted = 0
        for line in lines[-10:]:  # 最近10条
            parts = line.split(';')
            if len(parts) >= 5:
                try:
                    year = int(parts[0])
                    month = int(parts[1])
                    day = int(parts[2])
                    date = datetime.date(year, month, day)
                    
                    if start_date <= date <= end_date:
                        ssn = float(parts[4]) if parts[4].strip() else None
                        if ssn:
                            # 尝试更新
                            cursor.execute(
                                "UPDATE solar_activity SET sunspot_number = %s WHERE observation_date = %s",
                                (ssn, date.isoformat())
                            )
                            if cursor.rowcount == 0:
                                cursor.execute(
                                    "INSERT INTO solar_activity (observation_date, sunspot_number, data_source) VALUES (%s, %s, %s)",
                                    (date.isoformat(), ssn, 'SIDC')
                                )
                            inserted += 1
                except:
                    continue
        
        conn.commit()
        log(f"  ✓ 更新 {inserted} 条太阳黑子记录")
        total_inserted += inserted
    except Exception as e:
        log(f"  ✗ 失败: {e}")
    
    cursor.close()
    conn.close()
    
    log("="*60)
    log(f"✅ 完成! 共处理 {total_inserted} 条记录")
    log("="*60)

if __name__ == '__main__':
    main()
