#!/usr/bin/env python3
"""
历史数据批量导入工具
获取过去数月/数年的历史空间天气数据
"""

import mysql.connector
import json
import urllib.request
import datetime
import math
import sys
from typing import List, Tuple

DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter"
}


class HistoryDataLoader:
    """历史数据加载器"""
    
    def __init__(self):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        self.stats = {'inserted': 0, 'updated': 0, 'errors': 0}
    
    def log(self, msg: str):
        """打印日志"""
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] {msg}")
    
    def load_f107_history(self, days: int = 180) -> int:
        """
        加载F10.7历史数据
        NOAA提供最近1年的数据
        """
        self.log(f"[1/4] 加载F10.7历史数据 (过去{days}天)...")
        url = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HistoryLoader/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            
            # 获取指定天数的数据
            seen_dates = set()
            records = []
            
            for d in data:
                date_str = d['time_tag'][:10]
                if date_str not in seen_dates:
                    seen_dates.add(date_str)
                    date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                    if (datetime.date.today() - date).days <= days:
                        records.append((date_str, float(d['flux']), 'NOAA'))
            
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
                    # 已存在，更新
                    try:
                        self.cursor.execute(
                            "UPDATE solar_activity SET f107_flux = %s WHERE observation_date = %s",
                            (record[1], record[0])
                        )
                        if self.cursor.rowcount > 0:
                            self.stats['updated'] += 1
                    except Exception:
                        self.stats['errors'] += 1
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条，更新 {self.stats['updated']} 条F10.7记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'] += 1
            return 0
    
    def load_sunspot_history(self, days: int = 180) -> int:
        """
        加载太阳黑子历史数据
        SIDC提供完整历史数据（CSV格式）
        """
        self.log(f"[2/4] 加载太阳黑子历史数据 (过去{days}天)...")
        url = "http://www.sidc.be/silso/DATA/SN_d_tot_V2.0.csv"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HistoryLoader/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                lines = r.read().decode('utf-8').strip().split('\n')
            
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=days)
            
            inserted = 0
            for line in lines:
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
                                # 尝试更新已有记录
                                self.cursor.execute(
                                    "UPDATE solar_activity SET sunspot_number = %s WHERE observation_date = %s",
                                    (ssn, date.isoformat())
                                )
                                if self.cursor.rowcount == 0:
                                    # 插入新记录
                                    self.cursor.execute(
                                        "INSERT INTO solar_activity (observation_date, sunspot_number, data_source) VALUES (%s, %s, %s)",
                                        (date.isoformat(), ssn, 'SIDC')
                                    )
                                inserted += 1
                    except (ValueError, IndexError):
                        continue
            
            self.conn.commit()
            self.log(f"  ✓ 处理 {inserted} 条太阳黑子记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'] += 1
            return 0
    
    def load_kp_history(self, days: int = 90) -> int:
        """
        加载Kp历史数据
        使用NOAA数据源
        """
        self.log(f"[3/4] 加载Kp历史数据 (过去{days}天)...")
        url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HistoryLoader/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=days)
            
            inserted = 0
            for item in data[1:]:  # 跳过表头
                if len(item) >= 2:
                    try:
                        time_str = item[0][:19]
                        date_str = time_str[:10]
                        date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                        
                        if start_date <= date <= end_date:
                            kp = float(item[1]) if item[1] else None
                            
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
                                
                                try:
                                    self.cursor.execute("""
                                        INSERT INTO geomagnetic_indices 
                                        (measurement_time, measurement_date, kp_value, storm_level, storm_description)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (time_str, date_str, kp, level, desc))
                                    inserted += 1
                                except mysql.connector.errors.IntegrityError:
                                    pass
                    except (ValueError, IndexError):
                        continue
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条Kp记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'] += 1
            return 0
    
    def load_solar_wind_history(self, hours: int = 168) -> int:
        """
        加载太阳风历史数据
        NOAA提供7天历史数据
        """
        self.log(f"[4/4] 加载太阳风历史数据 (过去{hours}小时)...")
        
        urls = {
            'mag': "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json",
            'plasma': "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"
        }
        
        try:
            req1 = urllib.request.Request(urls['mag'], headers={"User-Agent": "HistoryLoader/1.0"})
            req2 = urllib.request.Request(urls['plasma'], headers={"User-Agent": "HistoryLoader/1.0"})
            
            with urllib.request.urlopen(req1, timeout=60) as r1:
                mag_data = json.loads(r1.read().decode())
            with urllib.request.urlopen(req2, timeout=60) as r2:
                plasma_data = json.loads(r2.read().decode())
            
            # 创建等离子体字典
            plasma_dict = {}
            for p in plasma_data[1:]:
                if len(p) >= 3:
                    plasma_dict[p[0][:16]] = {
                        'density': float(p[1]) if p[1] else None,
                        'speed': float(p[2]) if p[2] else None
                    }
            
            # 计算截止时间
            cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            
            inserted = 0
            for item in mag_data[1:]:
                if len(item) >= 4:
                    try:
                        time_str = item[0][:19]
                        record_time = datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                        
                        if record_time >= cutoff_time:
                            bx = float(item[1]) if item[1] else 0
                            by = float(item[2]) if item[2] else 0
                            bz = float(item[3]) if item[3] else 0
                            bt = math.sqrt(bx**2 + by**2 + bz**2)
                            
                            plasma = plasma_dict.get(item[0][:16], {})
                            density = plasma.get('density')
                            speed = plasma.get('speed')
                            
                            try:
                                self.cursor.execute("""
                                    INSERT INTO solar_wind 
                                    (measurement_time, proton_density, proton_speed, bt, bz, satellite)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (time_str, density, speed, bt, bz, 'DSCOVR'))
                                inserted += 1
                            except mysql.connector.errors.IntegrityError:
                                pass
                    except (ValueError, IndexError):
                        continue
            
            self.conn.commit()
            self.log(f"  ✓ 插入 {inserted} 条太阳风记录")
            return inserted
            
        except Exception as e:
            self.log(f"  ✗ 失败: {e}")
            self.stats['errors'] += 1
            return 0
    
    def generate_history_summary(self):
        """生成历史数据汇总"""
        self.log("\n" + "="*60)
        self.log("📊 历史数据加载完成汇总")
        self.log("="*60)
        
        # 查询各表数据量
        tables = [
            ('solar_activity', '太阳活动'),
            ('solar_wind', '太阳风'),
            ('geomagnetic_indices', '地磁指数'),
            ('sunrise_sunset', '日出日落')
        ]
        
        for table, name in tables:
            self.cursor.execute(f"SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM {table}")
            count, min_date, max_date = self.cursor.fetchone()
            self.log(f"  {name:12s}: {count:5d} 条记录")
        
        # 查询数据时间范围
        self.cursor.execute("SELECT MIN(observation_date), MAX(observation_date) FROM solar_activity")
        solar_range = self.cursor.fetchone()
        self.log(f"\n  太阳活动数据范围: {solar_range[0]} 至 {solar_range[1]}")
        
        self.cursor.execute("SELECT MIN(measurement_time), MAX(measurement_time) FROM solar_wind")
        wind_range = self.cursor.fetchone()
        self.log(f"  太阳风数据范围: {wind_range[0]} 至 {wind_range[1]}")
        
        self.cursor.execute("SELECT MIN(measurement_time), MAX(measurement_time) FROM geomagnetic_indices")
        kp_range = self.cursor.fetchone()
        self.log(f"  地磁指数数据范围: {kp_range[0]} 至 {kp_range[1]}")
        
        self.log("="*60)
    
    def close(self):
        """关闭连接"""
        self.cursor.close()
        self.conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='历史空间天气数据加载器')
    parser.add_argument('--f107-days', type=int, default=180, help='F10.7历史天数（默认180天）')
    parser.add_argument('--sunspot-days', type=int, default=180, help='太阳黑子历史天数（默认180天）')
    parser.add_argument('--kp-days', type=int, default=90, help='Kp历史天数（默认90天）')
    parser.add_argument('--wind-hours', type=int, default=168, help='太阳风历史小时数（默认168小时=7天）')
    parser.add_argument('--all', action='store_true', help='加载所有历史数据（可能耗时较长）')
    args = parser.parse_args()
    
    if args.all:
        args.f107_days = 365
        args.sunspot_days = 365
        args.kp_days = 180
        args.wind_hours = 168
    
    print("="*60)
    print("🚀 历史空间天气数据加载器")
    print("="*60)
    print(f"加载计划:")
    print(f"  • F10.7:     过去 {args.f107_days} 天")
    print(f"  • 太阳黑子:  过去 {args.sunspot_days} 天")
    print(f"  • Kp指数:    过去 {args.kp_days} 天")
    print(f"  • 太阳风:    过去 {args.wind_hours} 小时")
    print("="*60)
    
    loader = HistoryDataLoader()
    
    try:
        # 加载各类历史数据
        loader.load_f107_history(args.f107_days)
        loader.load_sunspot_history(args.sunspot_days)
        loader.load_kp_history(args.kp_days)
        loader.load_solar_wind_history(args.wind_hours)
        
        # 生成汇总
        loader.generate_history_summary()
        
    finally:
        loader.close()
    
    print("\n✅ 历史数据加载完成！")
    print("现在可以运行 cross_domain_analyzer.py 进行关联分析了")


if __name__ == '__main__':
    main()
