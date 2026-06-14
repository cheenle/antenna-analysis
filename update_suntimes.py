#!/usr/bin/env python3
"""
更新日出日落时间
每6小时运行一次
"""

import mysql.connector
import datetime
import math

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 更新日出日落时间...")
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 北京坐标
    lat, lon = 39.9042, 116.4074
    
    inserted = 0
    for i in range(7):  # 未来7天
        date = (datetime.date.today() + datetime.timedelta(days=i)).isoformat()
        
        # 天文计算
        day_of_year = (datetime.date.today() + datetime.timedelta(days=i)).timetuple().tm_yday
        declination = 23.45 * math.sin(math.radians((360/365) * (day_of_year - 81)))
        
        lat_rad = math.radians(lat)
        dec_rad = math.radians(declination)
        
        try:
            hour_angle = math.degrees(math.acos(-math.tan(lat_rad) * math.tan(dec_rad)))
        except ValueError:
            hour_angle = 90
        
        noon_local = 12 - (lon / 15)
        sunrise_hour = noon_local - hour_angle / 15
        sunset_hour = noon_local + hour_angle / 15
        daylight = sunset_hour - sunrise_hour
        
        # 转换为UTC（北京时区+8）
        utc_offset = 8
        sunrise_utc = int((sunrise_hour + utc_offset) % 24)
        sunset_utc = int((sunset_hour + utc_offset) % 24)
        
        sunrise_time = f"{date} {sunrise_utc:02d}:00:00"
        sunset_time = f"{date} {sunset_utc:02d}:00:00"
        
        try:
            cursor.execute("""
                INSERT INTO sunrise_sunset 
                (location_date, station_callsign, station_lat, station_lon, sunrise_time, sunset_time, daylight_hours)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (date, 'BG1SB', lat, lon, sunrise_time, sunset_time, round(daylight, 2)))
            inserted += 1
        except mysql.connector.errors.IntegrityError:
            pass
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"  ✓ 插入/更新 {inserted} 条记录")

if __name__ == '__main__':
    main()
