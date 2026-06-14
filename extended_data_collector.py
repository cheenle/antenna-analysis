#!/usr/bin/env python3
"""
扩展跨领域数据采集器
获取气象、月球、雷电、流星雨等数据
与QSO日志时间对齐
"""

import mysql.connector
import json
import urllib.request
import datetime
import math
from typing import List, Dict, Optional, Tuple

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


class ExtendedDataCollector:
    """扩展跨领域数据采集器"""
    
    def __init__(self):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        self.stats = {'inserted': 0, 'errors': []}
    
    def log(self, msg: str):
        """打印日志"""
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] {msg}")
    
    def collect_moon_position(self, days: int = 30) -> int:
        """
        计算月球位置（影响EME通信和潮汐）
        使用简化天文算法
        """
        self.log(f"[1/7] 计算月球位置 (过去{days}天和未来7天)...")
        
        try:
            inserted = 0
            base_date = datetime.date.today() - datetime.timedelta(days=days)
            
            # 为过去days天和未来7天每小时计算一次
            for day_offset in range(-days, 8):
                for hour in range(0, 24, 3):  # 每3小时一次
                    dt = datetime.datetime.combine(
                        datetime.date.today() + datetime.timedelta(days=day_offset),
                        datetime.time(hour)
                    )
                    
                    # 简化月相计算
                    # 已知2026-01-01是新月，周期29.53天
                    days_since_new = (dt.date() - datetime.date(2026, 1, 1)).days
                    moon_age = days_since_new % 29.53
                    moon_phase = moon_age / 29.53
                    illumination = 50 * (1 - math.cos(moon_phase * 2 * math.pi))
                    
                    # 简化仰角计算（北京纬度39.9°）
                    hour_angle = (hour - 12) * 15  # 每小时15度
                    moon_elevation = 60 * math.cos(math.radians(hour_angle))
                    moon_azimuth = (hour * 15 + 180) % 360
                    
                    # 月地距离（平均384400km，变化±21000km）
                    distance_variation = 21000 * math.sin(moon_phase * 2 * math.pi)
                    moon_distance = 384400 + distance_variation
                    
                    try:
                        self.cursor.execute("""
                            INSERT INTO moon_position 
                            (observation_time, moon_phase, moon_elevation, moon_azimuth, moon_distance, illumination)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (dt, round(moon_phase, 4), round(moon_elevation, 2), 
                              round(moon_azimuth, 2), round(moon_distance, 2), round(illumination, 2)))
                        inserted += 1
                    except mysql.connector.errors.IntegrityError:
                        pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条月球位置记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"Moon: {e}")
            return 0
    
    def collect_meteor_showers(self) -> int:
        """
        加载主要流星雨数据
        """
        self.log("[2/7] 加载流星雨数据...")
        
        # 2026年主要流星雨
        showers = [
            # (名称, 峰值日期, 开始日期, 结束日期, ZHR, 速度, 月相)
            ("Quadrantids", "2026-01-03", "2026-01-01", "2026-01-05", 120, 41, 0.5),
            ("Lyrids", "2026-04-22", "2026-04-16", "2026-04-25", 18, 49, 0.3),
            ("Eta Aquariids", "2026-05-06", "2026-04-19", "2026-05-28", 50, 66, 0.8),
            ("Perseids", "2026-08-12", "2026-07-17", "2026-08-24", 100, 59, 0.9),
            ("Draconids", "2026-10-08", "2026-10-06", "2026-10-10", 10, 20, 0.2),
            ("Orionids", "2026-10-21", "2026-10-02", "2026-11-07", 20, 66, 0.4),
            ("Leonids", "2026-11-17", "2026-11-06", "2026-11-30", 15, 71, 0.1),
            ("Geminids", "2026-12-14", "2026-12-04", "2026-12-17", 150, 35, 0.7),
            ("Ursids", "2026-12-22", "2026-12-17", "2026-12-26", 10, 33, 0.8),
        ]
        
        try:
            inserted = 0
            for shower in showers:
                name, peak, start, end, zhr, velocity, moon_phase = shower
                
                # 确定活跃等级
                if zhr >= 100:
                    activity = " major"
                elif zhr >= 20:
                    activity = " medium"
                else:
                    activity = " minor"
                
                try:
                    self.cursor.execute("""
                        INSERT INTO meteor_shower 
                        (shower_name, peak_date, start_date, end_date, zhr, velocity, 
                         moon_phase_at_peak, activity_level)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (name, peak, start, end, zhr, velocity, moon_phase, activity))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条流星雨记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"Meteor: {e}")
            return 0
    
    def collect_human_activity(self) -> int:
        """
        加载人为活动/节假日数据
        """
        self.log("[3/7] 加载人为活动/节假日数据...")
        
        # 2026年主要HAM相关活动
        activities = [
            # (日期, 类型, 名称, 国家, 活跃程度, 预期增长)
            ("2026-01-01", "Holiday", "New Year's Day", "ALL", 8, 30.0),
            ("2026-02-28", "Contest", "CQ WW 160M CW", "ALL", 9, 150.0),
            ("2026-03-28", "Contest", "CQ WW WPX SSB", "ALL", 10, 200.0),
            ("2026-04-04", "Activity", "QSO Party - California", "US", 6, 50.0),
            ("2026-05-09", "Activity", "Ham Radio Day", "CN", 7, 80.0),
            ("2026-06-13", "Contest", "CQ WW WPX CW", "ALL", 10, 200.0),
            ("2026-07-04", "Holiday", "Independence Day", "US", 5, 40.0),
            ("2026-10-01", "Holiday", "National Day", "CN", 6, 60.0),
            ("2026-10-24", "Contest", "CQ WW SSB", "ALL", 10, 250.0),
            ("2026-11-28", "Contest", "CQ WW CW", "ALL", 10, 250.0),
            ("2026-12-25", "Holiday", "Christmas", "ALL", 4, 20.0),
            ("2026-12-31", "Holiday", "New Year's Eve", "ALL", 6, 40.0),
        ]
        
        try:
            inserted = 0
            for activity in activities:
                date, event_type, name, country, level, increase = activity
                
                try:
                    self.cursor.execute("""
                        INSERT INTO human_activity 
                        (event_date, event_type, event_name, country_code, activity_level, expected_qso_increase)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (date, event_type, name, country, level, increase))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条人为活动记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"HumanActivity: {e}")
            return 0
    
    def collect_weather_forecast(self) -> int:
        """
        获取天气预报数据（使用Open-Meteo免费API）
        """
        self.log("[4/7] 获取天气预报数据...")
        
        # Open-Meteo API (免费，无需API key)
        # 北京坐标
        lat, lon = 39.9042, 116.4074
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,relative_humidity_2m,surface_pressure,visibility,cloudcover&forecast_days=7"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HAM-WeatherCollector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            
            hourly = data.get('hourly', {})
            times = hourly.get('time', [])
            temps = hourly.get('temperature_2m', [])
            humidity = hourly.get('relative_humidity_2m', [])
            pressure = hourly.get('surface_pressure', [])
            visibility = hourly.get('visibility', [])
            cloudcover = hourly.get('cloudcover', [])
            
            inserted = 0
            for i in range(len(times)):
                try:
                    time_str = times[i][:19]
                    self.cursor.execute("""
                        INSERT INTO weather_data 
                        (observation_time, station_id, temperature, humidity, pressure, visibility, cloud_cover)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (time_str, 'BEIJING_FORECAST', temps[i], humidity[i], 
                          pressure[i], visibility[i]/1000 if visibility[i] else None, cloudcover[i]))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
                except Exception:
                    continue
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条天气预报记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"Weather: {e}")
            return 0
    
    def collect_atmospheric_indices(self) -> int:
        """
        加载大气环流指数（NAO/AO）
        使用NOAA CPC数据
        """
        self.log("[5/7] 加载大气环流指数...")
        
        # NOAA CPC NAO数据URL
        url = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HAM-DataCollector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                content = r.read().decode('utf-8')
            
            inserted = 0
            for line in content.strip().split('\n')[-12:]:  # 最近12个月
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        year = int(parts[0])
                        month = int(parts[1])
                        value = float(parts[2])
                        
                        date = datetime.date(year, month, 15)
                        phase = 'positive' if value > 0.5 else 'negative' if value < -0.5 else 'neutral'
                        
                        self.cursor.execute("""
                            INSERT INTO atmospheric_indices 
                            (index_date, index_type, index_value, phase)
                            VALUES (%s, %s, %s, %s)
                        """, (date, 'NAO', value, phase))
                        inserted += 1
                    except:
                        continue
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条大气指数记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"Atmospheric: {e}")
            return 0
    
    def simulate_lightning_data(self, hours: int = 24) -> int:
        """
        模拟雷电数据（作为示例）
        实际应接入Blitzortung或类似API
        """
        self.log(f"[6/7] 生成模拟雷电数据 (过去{hours}小时)...")
        
        try:
            import random
            inserted = 0
            base_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            
            # 随机生成雷电事件
            for _ in range(20):  # 20个事件
                event_time = base_time + datetime.timedelta(
                    hours=random.randint(0, hours),
                    minutes=random.randint(0, 59)
                )
                
                # 北京周边随机位置
                lat = 39.9 + random.uniform(-2, 2)
                lon = 116.4 + random.uniform(-2, 2)
                intensity = random.uniform(10, 100)
                
                # 计算距离（简化）
                distance = math.sqrt((lat - 39.9)**2 + (lon - 116.4)**2) * 111
                
                try:
                    self.cursor.execute("""
                        INSERT INTO lightning_data 
                        (strike_time, latitude, longitude, intensity, distance_from_station, stroke_type)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (event_time, lat, lon, intensity, distance, 'CG'))
                    inserted += 1
                except mysql.connector.errors.IntegrityError:
                    pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条雷电记录(模拟)")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"Lightning: {e}")
            return 0
    
    def simulate_cosmic_rays(self, days: int = 7) -> int:
        """
        模拟宇宙射线数据
        实际应接入 neutronmonitor.org API
        """
        self.log(f"[7/7] 生成模拟宇宙射线数据 (过去{days}天)...")
        
        try:
            import random
            inserted = 0
            base_date = datetime.date.today() - datetime.timedelta(days=days)
            
            for day_offset in range(days):
                for hour in range(0, 24, 6):  # 每6小时
                    dt = datetime.datetime.combine(
                        base_date + datetime.timedelta(days=day_offset),
                        datetime.time(hour)
                    )
                    
                    # 模拟中子计数（正常约2000-4000）
                    base_count = 3000
                    variation = random.gauss(0, 200)
                    neutron_count = int(base_count + variation)
                    
                    try:
                        self.cursor.execute("""
                            INSERT INTO cosmic_rays 
                            (measurement_time, neutron_count, station_name, pressure_corrected)
                            VALUES (%s, %s, %s, %s)
                        """, (dt, neutron_count, 'BEIJING_SIM', True))
                        inserted += 1
                    except mysql.connector.errors.IntegrityError:
                        pass
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条宇宙射线记录(模拟)")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'].append(f"CosmicRay: {e}")
            return 0
    
    def run_collection(self):
        """执行完整采集流程"""
        print("="*70)
        print("🌍 扩展跨领域数据采集")
        print("="*70)
        
        total_inserted = 0
        
        total_inserted += self.collect_moon_position(30)
        total_inserted += self.collect_meteor_showers()
        total_inserted += self.collect_human_activity()
        total_inserted += self.collect_weather_forecast()
        total_inserted += self.collect_atmospheric_indices()
        total_inserted += self.simulate_lightning_data(24)
        total_inserted += self.simulate_cosmic_rays(7)
        
        print("\n" + "="*70)
        print("📊 采集统计")
        print("="*70)
        print(f"  总计插入: {total_inserted} 条记录")
        
        if self.stats['errors']:
            print(f"  ⚠️  错误数: {len(self.stats['errors'])} 个")
            for err in self.stats['errors']:
                print(f"      - {err}")
        
        print("="*70)
        print("✅ 扩展数据采集完成！")
        print("="*70)
    
    def close(self):
        """关闭数据库连接"""
        self.cursor.close()
        self.conn.close()


def main():
    collector = ExtendedDataCollector()
    try:
        collector.run_collection()
    finally:
        collector.close()


if __name__ == '__main__':
    main()
