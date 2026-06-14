#!/usr/bin/env python3
"""
空间天气数据采集器
定期从多个数据源获取数据并保存到数据库
支持：太阳活动、太阳风、地磁指数、电离层数据
"""

import mysql.connector
import json
import urllib.request
import datetime
import math
import time
import sys
from typing import List, Dict, Optional

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


class SpaceWeatherCollector:
    """空间天气数据采集器"""
    
    def __init__(self):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        self.stats = {
            'solar_activity': 0,
            'solar_wind': 0,
            'geomagnetic': 0,
            'sunrise_sunset': 0,
            'ionosphere': 0,
            'errors': []
        }
    
    def log(self, message: str):
        """打印日志"""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message}")
    
    def collect_f107(self) -> int:
        """采集F10.7太阳射电通量"""
        self.log("[1/5] 采集F10.7数据...")
        url = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SpaceWeatherCollector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
                
                # 获取最近7天的唯一日期数据
                seen_dates = set()
                records = []
                
                for d in data[-30:]:  # 取最近30条
                    date_str = d['time_tag'][:10]
                    if date_str not in seen_dates:
                        seen_dates.add(date_str)
                        flux = float(d['flux'])
                        records.append((date_str, flux, 'NOAA'))
                
                # 插入数据库
                inserted = 0
                for record in records:
                    try:
                        self.cursor.execute(
                            "INSERT INTO solar_activity (observation_date, f107_flux, data_source) VALUES (%s, %s, %s)",
                            record
                        )
                        inserted += 1
                    except mysql.connector.errors.IntegrityError:
                        pass  # 重复数据，忽略
                
                self.conn.commit()
                self.log(f"  ✓ 插入 {inserted} 条F10.7记录")
                return inserted
                
        except Exception as e:
            self.log(f"  ✗ F10.7采集失败: {e}")
            self.stats['errors'].append(f"F10.7: {e}")
            return 0
    
    def collect_solar_wind(self) -> int:
        """采集太阳风数据"""
        self.log("[2/5] 采集太阳风数据...")
        
        urls = {
            'mag': "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json",
            'plasma': "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
        }
        
        try:
            # 获取磁场数据
            req_mag = urllib.request.Request(urls['mag'], headers={"User-Agent": "SpaceWeatherCollector/1.0"})
            with urllib.request.urlopen(req_mag, timeout=30) as r:
                mag_data = json.loads(r.read().decode())
            
            # 获取等离子体数据
            req_plasma = urllib.request.Request(urls['plasma'], headers={"User-Agent": "SpaceWeatherCollector/1.0"})
            with urllib.request.urlopen(req_plasma, timeout=30) as r:
                plasma_data = json.loads(r.read().decode())
            
            # 创建等离子体字典
            plasma_dict = {}
            for p in plasma_data[1:]:
                if len(p) >= 3:
                    plasma_dict[p[0][:16]] = {
                        'density': float(p[1]) if p[1] else None,
                        'speed': float(p[2]) if p[2] else None,
                        'temp': float(p[3]) if len(p) > 3 and p[3] else None
                    }
            
            # 合并数据并插入
            inserted = 0
            for item in mag_data[1:][-144:]:  # 最近24小时（每10分钟一条）
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
                        
                        # 计算动压
                        dynamic_pressure = None
                        if density and speed:
                            dynamic_pressure = 1.67e-6 * density * (speed ** 2)
                        
                        self.cursor.execute("""
                            INSERT INTO solar_wind 
                            (measurement_time, proton_density, proton_speed, bt, bx, by, bz, dynamic_pressure, satellite)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (time_str, density, speed, bt, bx, by, bz, dynamic_pressure, 'DSCOVR'))
                        inserted += 1
                    except mysql.connector.errors.IntegrityError:
                        pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条太阳风记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 太阳风采集失败: {e}")
            self.stats['errors'].append(f"SolarWind: {e}")
            return 0
    
    def collect_kp_index(self) -> int:
        """采集Kp地磁指数"""
        self.log("[3/5] 采集Kp地磁指数...")
        
        # NOAA Kp指数
        url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SpaceWeatherCollector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
                
                inserted = 0
                for item in data[1:]:
                    if len(item) >= 2:
                        try:
                            time_str = item[0][:19]
                            kp = float(item[1]) if item[1] else None
                            date_str = time_str[:10]
                            
                            if kp is not None:
                                # 判断磁暴等级
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
                                
                                self.cursor.execute("""
                                    INSERT INTO geomagnetic_indices 
                                    (measurement_time, measurement_date, kp_value, storm_level, storm_description)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (time_str, date_str, kp, level, desc))
                                inserted += 1
                        except mysql.connector.errors.IntegrityError:
                            pass
                
                self.conn.commit()
                self.log(f"  ✓ 插入 {inserted} 条Kp记录")
                return inserted
                
        except Exception as e:
            self.log(f"  ✗ Kp采集失败: {e}")
            self.stats['errors'].append(f"Kp: {e}")
            return 0
    
    def collect_sunspot(self) -> int:
        """采集太阳黑子数据"""
        self.log("[4/5] 采集太阳黑子数据...")
        
        url = "http://www.sidc.be/silso/DATA/SN_d_tot_V2.0.csv"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SpaceWeatherCollector/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                lines = r.read().decode('utf-8').strip().split('\n')
                
                # 取最近7天数据
                end_date = datetime.date.today()
                start_date = end_date - datetime.timedelta(days=7)
                
                inserted = 0
                for line in lines[-20:]:  # 最近20条
                    parts = line.split(';')
                    if len(parts) >= 5:
                        try:
                            year = int(parts[0])
                            month = int(parts[1])
                            day = int(parts[2])
                            
                            date = datetime.date(year, month, day)
                            if start_date <= date <= end_date:
                                ssn = float(parts[4]) if parts[4].strip() else None
                                if ssn is not None:
                                    # 更新已有记录或插入新记录
                                    self.cursor.execute("""
                                        UPDATE solar_activity 
                                        SET sunspot_number = %s 
                                        WHERE observation_date = %s
                                    """, (ssn, date.isoformat()))
                                    
                                    if self.cursor.rowcount == 0:
                                        self.cursor.execute("""
                                            INSERT INTO solar_activity 
                                            (observation_date, sunspot_number, data_source)
                                            VALUES (%s, %s, 'SIDC')
                                        """, (date.isoformat(), ssn))
                                    inserted += 1
                        except (ValueError, IndexError):
                            continue
                
                self.conn.commit()
                self.log(f"  ✓ 更新 {inserted} 条太阳黑子记录")
                return inserted
                
        except Exception as e:
            self.log(f"  ✗ 太阳黑子采集失败: {e}")
            self.stats['errors'].append(f"Sunspot: {e}")
            return 0
    
    def calculate_sun_times(self) -> int:
        """计算日出日落时间"""
        self.log("[5/5] 计算日出日落时间...")
        
        try:
            # 北京坐标
            lat, lon = 39.9042, 116.4074
            
            inserted = 0
            for i in range(7):  # 未来7天
                date = (datetime.date.today() + datetime.timedelta(days=i)).isoformat()
                
                # 简化计算（实际应使用天文算法）
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
                
                utc_offset = 8
                
                sunrise_time = f"{date} {int((sunrise_hour + utc_offset) % 24):02d}:00:00"
                sunset_time = f"{date} {int((sunset_hour + utc_offset) % 24):02d}:00:00"
                daylight = (sunset_hour - sunrise_hour)
                
                try:
                    self.cursor.execute("""
                        INSERT INTO sunrise_sunset 
                        (location_date, station_callsign, station_lat, station_lon, sunrise_time, sunset_time, daylight_hours)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (date, 'BG1SB', lat, lon, sunrise_time, sunset_time, round(daylight, 2)))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条日出日落记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 日出日落计算失败: {e}")
            self.stats['errors'].append(f"SunTimes: {e}")
            return 0
    
    def run_collection(self):
        """执行完整采集流程"""
        self.log("="*70)
        self.log("🚀 开始空间天气数据采集")
        self.log("="*70)
        
        start_time = time.time()
        
        # 执行各项采集
        self.stats['solar_activity'] = self.collect_f107()
        self.stats['solar_wind'] = self.collect_solar_wind()
        self.stats['geomagnetic'] = self.collect_kp_index()
        self.stats['sunspot'] = self.collect_sunspot()
        self.stats['sunrise_sunset'] = self.calculate_sun_times()
        
        elapsed = time.time() - start_time
        
        # 输出统计
        self.log("="*70)
        self.log("📊 采集统计")
        self.log("="*70)
        self.log(f"  F10.7数据:     {self.stats['solar_activity']} 条")
        self.log(f"  太阳黑子:      {self.stats['sunspot']} 条")
        self.log(f"  太阳风:        {self.stats['solar_wind']} 条")
        self.log(f"  Kp地磁指数:    {self.stats['geomagnetic']} 条")
        self.log(f"  日出日落:      {self.stats['sunrise_sunset']} 条")
        self.log(f"  总耗时:        {elapsed:.1f} 秒")
        
        if self.stats['errors']:
            self.log(f"  ⚠️  错误:        {len(self.stats['errors'])} 个")
            for err in self.stats['errors']:
                self.log(f"      - {err}")
        
        self.log("="*70)
        self.log("✅ 采集完成")
        self.log("="*70)
    
    def close(self):
        """关闭数据库连接"""
        self.cursor.close()
        self.conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='空间天气数据采集器')
    parser.add_argument('--daemon', action='store_true', help='守护进程模式（每小时运行一次）')
    parser.add_argument('--interval', type=int, default=3600, help='采集间隔（秒，默认3600=1小时）')
    args = parser.parse_args()
    
    if args.daemon:
        print(f"🔄 守护进程模式启动，每 {args.interval} 秒采集一次...")
        print("按 Ctrl+C 停止")
        try:
            while True:
                collector = SpaceWeatherCollector()
                try:
                    collector.run_collection()
                finally:
                    collector.close()
                
                print(f"\n⏱️  下次采集: {datetime.datetime.now() + datetime.timedelta(seconds=args.interval)}\n")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n🛑 采集器已停止")
    else:
        # 单次运行
        collector = SpaceWeatherCollector()
        try:
            collector.run_collection()
        finally:
            collector.close()


if __name__ == '__main__':
    main()
