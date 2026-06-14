#!/usr/bin/env python3
"""
空间天气数据获取器
从多个数据源获取太阳活动、地磁指数、太阳风、电离层数据
用于与 PSK Reporter 无线电数据进行横向分析

数据源:
- 太阳活动: SIDC (sunspot), NOAA (F10.7, 耀斑)
- 太阳风: NOAA SWPC (ACE/DSCOVR)
- 地磁指数: GFZ Potsdam (Kp), WDC Kyoto (Dst)
- 电离层: IRI Model, Digisonde
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import math
from typing import Optional, List, Dict, Any, Tuple

# 默认配置
DEFAULT_CONFIG = {
    "database": {
        "host": "ham.vlsc.net",
        "port": 9030,
        "user": "root",
        "password": "",
        "name": "pskreporter"
    },
    "data_sources": {
        "sidc": "http://www.sidc.be/silso/DATA/SN_d_tot_V2.0.csv",
        "f107": "https://services.swpc.noaa.gov/json/f107_cm_flux.json",
        "solar_wind": "https://services.swpc.noaa.gov/products/solar-wind/",
        "kp": "ftp://ftp.gfz-potsdam.de/pub/home/obs/kp-ap/wdc/",
        "dst": "https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/",
    },
    "station": {
        "callsign": "BG1SB",
        "lat": 39.9042,
        "lon": 116.4074,
        "grid": "ON80da"
    }
}


class SpaceWeatherFetcher:
    """空间天气数据获取器"""
    
    def __init__(self, config: dict = None):
        self.config = config or DEFAULT_CONFIG
        self.db_config = self.config.get('database', DEFAULT_CONFIG['database'])
        
    def _fetch_url(self, url: str, timeout: int = 30) -> str:
        """获取URL内容"""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "SpaceWeatherFetcher/1.0")
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            print(f"  获取数据失败 {url}: {e}")
            return ""
    
    def fetch_sunspot_data(self, days: int = 30) -> List[Dict]:
        """
        获取太阳黑子数据 (SIDC)
        数据源: http://www.sidc.be/silso/datafiles
        
        CSV格式: YYYY MM DD  fraction  sunspot_number  std  obs  def/prov
        """
        print(f"\n[1/5] 获取太阳黑子数据 (SIDC)...")
        
        url = "http://www.sidc.be/silso/DATA/SN_d_tot_V2.0.csv"
        data = self._fetch_url(url, timeout=60)
        
        if not data:
            return []
        
        records = []
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days)
        
        for line in data.strip().split('\n'):
            parts = line.split(';')
            if len(parts) >= 7:
                try:
                    year = int(parts[0])
                    month = int(parts[1])
                    day = int(parts[2])
                    
                    record_date = datetime.date(year, month, day)
                    
                    # 只获取指定时间范围内的数据
                    if start_date <= record_date <= end_date:
                        records.append({
                            'observation_date': record_date.isoformat(),
                            'sunspot_number': float(parts[4]) if parts[4].strip() else None,
                            'sunspot_number_std': float(parts[5]) if parts[5].strip() else None,
                            'sunspot_area': float(parts[3]) if parts[3].strip() else None,
                            'data_source': 'SIDC'
                        })
                except (ValueError, IndexError):
                    continue
        
        print(f"  获取到 {len(records)} 条太阳黑子记录")
        return records
    
    def fetch_f107_data(self, days: int = 30) -> List[Dict]:
        """
        获取 F10.7 射电通量数据 (NOAA)
        数据源: https://services.swpc.noaa.gov/json/f107_cm_flux.json
        """
        print(f"\n[2/5] 获取 F10.7 射电通量 (NOAA)...")
        
        url = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
        data = self._fetch_url(url)
        
        if not data:
            return []
        
        try:
            json_data = json.loads(data)
            records = []
            
            end_date = datetime.date.today()
            start_date = end_date - datetime.timedelta(days=days)
            
            for item in json_data[-days:]:  # 取最近N天
                try:
                    obs_date = datetime.datetime.strptime(
                        item['time'].split('T')[0], '%Y-%m-%d'
                    ).date()
                    
                    if start_date <= obs_date <= end_date:
                        records.append({
                            'observation_date': obs_date.isoformat(),
                            'f107_flux': float(item.get('flux', 0)),
                            'f107_flux_adjusted': float(item.get('adjusted_flux', 0)),
                            'data_source': 'NOAA'
                        })
                except (ValueError, KeyError):
                    continue
            
            print(f"  获取到 {len(records)} 条 F10.7 记录")
            return records
            
        except json.JSONDecodeError as e:
            print(f"  JSON解析错误: {e}")
            return []
    
    def fetch_solar_wind(self, hours: int = 24) -> List[Dict]:
        """
        获取太阳风实时数据 (NOAA DSCOVR)
        数据源: https://services.swpc.noaa.gov/products/solar-wind/
        """
        print(f"\n[3/5] 获取太阳风数据 (DSCOVR)...")
        
        # 磁等离子体数据
        url_mag = "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json"
        url_plasma = "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"
        
        mag_data = self._fetch_url(url_mag)
        plasma_data = self._fetch_url(url_plasma)
        
        records = []
        
        try:
            mag_json = json.loads(mag_data) if mag_data else []
            plasma_json = json.loads(plasma_data) if plasma_data else []
            
            # 创建等离子体数据字典（按时间索引）
            plasma_dict = {}
            for item in plasma_json[1:]:  # 跳过表头
                if len(item) >= 3:
                    time_key = item[0][:16]  # 取到分钟
                    plasma_dict[time_key] = {
                        'density': float(item[1]) if item[1] else None,
                        'speed': float(item[2]) if item[2] else None,
                        'temperature': float(item[3]) if len(item) > 3 and item[3] else None
                    }
            
            # 合并磁场和等离子体数据
            end_time = datetime.datetime.utcnow()
            start_time = end_time - datetime.timedelta(hours=hours)
            
            for item in mag_json[1:]:  # 跳过表头
                if len(item) >= 4:
                    try:
                        # 解析时间
                        time_str = item[0]
                        record_time = datetime.datetime.strptime(
                            time_str[:19], '%Y-%m-%d %H:%M:%S'
                        )
                        
                        if start_time <= record_time <= end_time:
                            time_key = time_str[:16]
                            plasma = plasma_dict.get(time_key, {})
                            
                            # 计算总磁场强度
                            bx = float(item[1]) if item[1] else 0
                            by = float(item[2]) if item[2] else 0
                            bz = float(item[3]) if item[3] else 0
                            bt = math.sqrt(bx**2 + by**2 + bz**2)
                            
                            # 计算动压 (nPa) = 1.67e-6 * n * V^2
                            density = plasma.get('density', 0) or 0
                            speed = plasma.get('speed', 0) or 0
                            dynamic_pressure = 1.67e-6 * density * (speed ** 2)
                            
                            records.append({
                                'measurement_time': record_time.isoformat(),
                                'bx': bx if bx != 0 else None,
                                'by': by if by != 0 else None,
                                'bz': bz if bz != 0 else None,
                                'bt': bt if bt != 0 else None,
                                'proton_density': plasma.get('density'),
                                'proton_speed': plasma.get('speed'),
                                'proton_temperature': plasma.get('temperature'),
                                'dynamic_pressure': dynamic_pressure if dynamic_pressure > 0 else None,
                                'satellite': 'DSCOVR',
                                'data_quality': 'good'
                            })
                    except (ValueError, IndexError):
                        continue
            
            print(f"  获取到 {len(records)} 条太阳风记录")
            return records
            
        except json.JSONDecodeError as e:
            print(f"  JSON解析错误: {e}")
            return []
    
    def fetch_kp_index(self, days: int = 30) -> List[Dict]:
        """
        获取 Kp 地磁指数 (GFZ Potsdam)
        数据源: https://kp.gfz-potsdam.de/
        """
        print(f"\n[4/5] 获取 Kp 地磁指数 (GFZ)...")
        
        # GFZ提供JSON API
        url = "https://kp.gfz-potsdam.de/app/json/?startdate={}&enddate={}"
        
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=days)
        
        formatted_url = url.format(
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        
        data = self._fetch_url(formatted_url)
        records = []
        
        if data:
            try:
                json_data = json.loads(data)
                for item in json_data:
                    try:
                        # Kp数据每3小时一个值
                        date_str = item.get('date', '')
                        kp_values = item.get('Kp', [])
                        
                        for i, kp in enumerate(kp_values):
                            hour = i * 3
                            record_time = datetime.datetime.strptime(
                                f"{date_str} {hour:02d}:00:00", 
                                '%Y-%m-%d %H:%M:%S'
                            )
                            
                            # 确定磁暴等级
                            storm_level, storm_desc = self._get_storm_level(kp)
                            
                            records.append({
                                'measurement_time': record_time.isoformat(),
                                'measurement_date': date_str,
                                'kp_value': kp,
                                'ap_value': self._kp_to_ap(kp),
                                'storm_level': storm_level,
                                'storm_description': storm_desc,
                                'kp_source': 'GFZ'
                            })
                    except (ValueError, KeyError):
                        continue
                
                print(f"  获取到 {len(records)} 条 Kp 记录")
            except json.JSONDecodeError as e:
                print(f"  JSON解析错误: {e}")
        
        return records
    
    def _kp_to_ap(self, kp: float) -> int:
        """Kp 转 Ap 近似值"""
        # 近似转换表
        conversion = {
            0.0: 0, 0.3: 2, 0.7: 3, 1.0: 4, 1.3: 5, 1.7: 6, 2.0: 7,
            2.3: 9, 2.7: 12, 3.0: 15, 3.3: 18, 3.7: 22, 4.0: 27,
            4.3: 32, 4.7: 39, 5.0: 48, 5.3: 56, 5.7: 67, 6.0: 80,
            6.3: 94, 6.7: 111, 7.0: 132, 7.3: 154, 7.7: 179, 8.0: 207,
            8.3: 236, 8.7: 268, 9.0: 300
        }
        return conversion.get(kp, int(kp * 30))
    
    def _get_storm_level(self, kp: float) -> Tuple[str, str]:
        """根据Kp值获取磁暴等级"""
        if kp < 5:
            return ('G0', '平静')
        elif kp < 6:
            return ('G1', '小磁暴')
        elif kp < 7:
            return ('G2', '中等磁暴')
        elif kp < 8:
            return ('G3', '强磁暴')
        elif kp < 9:
            return ('G4', '严重磁暴')
        else:
            return ('G5', '极强磁暴')
    
    def fetch_dst_index(self, days: int = 30) -> List[Dict]:
        """
        获取 Dst 地磁指数 (WDC Kyoto)
        数据源: https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/
        """
        print(f"\n[5/5] 获取 Dst 地磁指数 (WDC Kyoto)...")
        
        # WDC Kyoto提供小时数据
        records = []
        end_date = datetime.date.today()
        
        for i in range(days):
            current_date = end_date - datetime.timedelta(days=i)
            date_str = current_date.strftime('%Y%m%d')
            
            # 尝试获取数据
            url = f"https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/{current_date.year}/{date_str}/index.html"
            data = self._fetch_url(url)
            
            if data and '404' not in data:
                # 解析HTML中的Dst数据（简化处理）
                # 实际实现可能需要更复杂的HTML解析
                pass
        
        print(f"  Dst数据获取需要更复杂的解析，建议使用NASA替代源")
        return records
    
    def calculate_sun_times(self, days: int = 30) -> List[Dict]:
        """
        计算日出日落时间
        使用天文算法计算
        """
        print(f"\n[附加] 计算日出日落时间...")
        
        station = self.config.get('station', DEFAULT_CONFIG['station'])
        lat = station['lat']
        lon = station['lon']
        callsign = station['callsign']
        
        records = []
        
        for i in range(days):
            date = datetime.date.today() - datetime.timedelta(days=i)
            
            # 使用简化公式计算日出日落
            # 实际应用中可以使用skyfield或ephem库
            sunrise, sunset, noon, max_elev = self._calculate_sun_rise_set(date, lat, lon)
            
            daylight = (sunset - sunrise).total_seconds() / 3600 if sunrise and sunset else None
            
            records.append({
                'location_date': date.isoformat(),
                'station_callsign': callsign,
                'station_lat': lat,
                'station_lon': lon,
                'sunrise_time': sunrise.isoformat() if sunrise else None,
                'sunset_time': sunset.isoformat() if sunset else None,
                'solar_noon': noon.isoformat() if noon else None,
                'daylight_hours': round(daylight, 2) if daylight else None,
                'sun_max_elevation': round(max_elev, 2) if max_elev else None
            })
        
        print(f"  计算了 {len(records)} 天的日出日落时间")
        return records
    
    def _calculate_sun_rise_set(self, date: datetime.date, lat: float, lon: float) -> Tuple:
        """
        简化版日出日落计算
        实际应用建议使用 skyfield 或 ephem 库
        """
        # 这里使用简化计算，精度约几分钟
        # 完整实现需要导入天文计算库
        
        day_of_year = date.timetuple().tm_yday
        
        # 太阳赤纬近似
        declination = 23.45 * math.sin(math.radians((360/365) * (day_of_year - 81)))
        
        # 日出日落时角
        lat_rad = math.radians(lat)
        dec_rad = math.radians(declination)
        
        try:
            hour_angle = math.degrees(math.acos(
                -math.tan(lat_rad) * math.tan(dec_rad)
            ))
        except ValueError:
            hour_angle = 90  # 极昼或极夜
        
        # 正午时间（本地太阳时）
        noon_local = 12 - (lon / 15)  # 经度修正
        
        sunrise_hour = noon_local - hour_angle / 15
        sunset_hour = noon_local + hour_angle / 15
        
        # 转换为UTC
        utc_offset = 8  # 北京时区 UTC+8
        
        sunrise_utc = datetime.datetime.combine(
            date, datetime.time(int(sunrise_hour + utc_offset) % 24, 0)
        )
        sunset_utc = datetime.datetime.combine(
            date, datetime.time(int(sunset_hour + utc_offset) % 24, 0)
        )
        noon_utc = datetime.datetime.combine(
            date, datetime.time(int(noon_local + utc_offset) % 24, 0)
        )
        
        # 太阳最大高度角
        max_elevation = 90 - abs(lat - declination)
        
        return sunrise_utc, sunset_utc, noon_utc, max_elevation
    
    def save_to_database(self, table: str, records: List[Dict]) -> int:
        """
        保存数据到数据库
        """
        if not records:
            return 0
        
        try:
            import mysql.connector
            
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            
            # 根据表名构建插入语句
            if table == 'solar_activity':
                sql = """
                INSERT INTO solar_activity 
                (observation_date, sunspot_number, sunspot_number_std, 
                 f107_flux, f107_flux_adjusted, data_source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                sunspot_number = VALUES(sunspot_number),
                f107_flux = VALUES(f107_flux)
                """
                values = [(
                    r.get('observation_date'),
                    r.get('sunspot_number'),
                    r.get('sunspot_number_std'),
                    r.get('f107_flux'),
                    r.get('f107_flux_adjusted'),
                    r.get('data_source')
                ) for r in records]
                
            elif table == 'solar_wind':
                sql = """
                INSERT INTO solar_wind 
                (measurement_time, proton_density, proton_speed, 
                 bt, bz, by, dynamic_pressure, satellite)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                proton_speed = VALUES(proton_speed),
                bz = VALUES(bz)
                """
                values = [(
                    r.get('measurement_time'),
                    r.get('proton_density'),
                    r.get('proton_speed'),
                    r.get('bt'),
                    r.get('bz'),
                    r.get('by'),
                    r.get('dynamic_pressure'),
                    r.get('satellite')
                ) for r in records]
                
            elif table == 'geomagnetic_indices':
                sql = """
                INSERT INTO geomagnetic_indices 
                (measurement_time, measurement_date, kp_value, ap_value,
                 storm_level, storm_description, kp_source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                kp_value = VALUES(kp_value),
                storm_level = VALUES(storm_level)
                """
                values = [(
                    r.get('measurement_time'),
                    r.get('measurement_date'),
                    r.get('kp_value'),
                    r.get('ap_value'),
                    r.get('storm_level'),
                    r.get('storm_description'),
                    r.get('kp_source')
                ) for r in records]
                
            elif table == 'sunrise_sunset':
                sql = """
                INSERT INTO sunrise_sunset 
                (location_date, station_callsign, sunrise_time, sunset_time,
                 solar_noon, daylight_hours, sun_max_elevation)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                sunrise_time = VALUES(sunrise_time),
                sunset_time = VALUES(sunset_time)
                """
                values = [(
                    r.get('location_date'),
                    r.get('station_callsign'),
                    r.get('sunrise_time'),
                    r.get('sunset_time'),
                    r.get('solar_noon'),
                    r.get('daylight_hours'),
                    r.get('sun_max_elevation')
                ) for r in records]
            else:
                return 0
            
            cursor.executemany(sql, values)
            conn.commit()
            inserted = cursor.rowcount
            cursor.close()
            conn.close()
            
            return inserted
            
        except Exception as e:
            print(f"  数据库保存错误: {e}")
            return 0
    
    def run(self, days: int = 7, save_db: bool = True):
        """
        运行完整的数据获取流程
        """
        print(f"\n{'='*70}")
        print(f"空间天气数据获取器 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        print(f"时间范围: 过去 {days} 天")
        print(f"目标数据库: {self.db_config['host']}:{self.db_config['port']}")
        
        # 1. 太阳活动数据
        sunspot_data = self.fetch_sunspot_data(days)
        f107_data = self.fetch_f107_data(days)
        
        # 合并太阳活动数据
        solar_merged = {}
        for r in sunspot_data:
            solar_merged[r['observation_date']] = r
        for r in f107_data:
            if r['observation_date'] in solar_merged:
                solar_merged[r['observation_date']].update(r)
            else:
                solar_merged[r['observation_date']] = r
        
        solar_records = list(solar_merged.values())
        
        # 2. 太阳风数据（最近24小时）
        solar_wind_records = self.fetch_solar_wind(min(24, days * 24))
        
        # 3. 地磁指数
        kp_records = self.fetch_kp_index(days)
        
        # 4. 日出日落
        sunrise_records = self.calculate_sun_times(days)
        
        # 保存到数据库
        if save_db:
            print(f"\n{'='*70}")
            print("保存数据到数据库...")
            print(f"{'='*70}")
            
            if solar_records:
                count = self.save_to_database('solar_activity', solar_records)
                print(f"  太阳活动: {count} 条")
            
            if solar_wind_records:
                count = self.save_to_database('solar_wind', solar_wind_records)
                print(f"  太阳风: {count} 条")
            
            if kp_records:
                count = self.save_to_database('geomagnetic_indices', kp_records)
                print(f"  地磁指数: {count} 条")
            
            if sunrise_records:
                count = self.save_to_database('sunrise_sunset', sunrise_records)
                print(f"  日出日落: {count} 条")
        
        print(f"\n{'='*70}")
        print("数据获取完成!")
        print(f"{'='*70}")
        
        return {
            'solar_activity': len(solar_records),
            'solar_wind': len(solar_wind_records),
            'geomagnetic': len(kp_records),
            'sunrise_sunset': len(sunrise_records)
        }


def main():
    parser = argparse.ArgumentParser(
        description='空间天气数据获取器 - 获取太阳活动、地磁指数等数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 获取最近7天数据
  %(prog)s --days 30                 # 获取最近30天数据
  %(prog)s --days 1 --no-db          # 仅获取，不保存到数据库
        """
    )
    
    parser.add_argument('--days', type=int, default=7,
                        help='获取过去多少天的数据 (默认: 7)')
    parser.add_argument('--no-db', action='store_true',
                        help='不保存到数据库，仅显示')
    parser.add_argument('--config', type=str, default='config.json',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    # 加载配置
    config = DEFAULT_CONFIG
    if os.path.exists(args.config):
        try:
            with open(args.config, 'r') as f:
                user_config = json.load(f)
                config.update(user_config)
        except json.JSONDecodeError:
            pass
    
    # 运行获取器
    fetcher = SpaceWeatherFetcher(config)
    results = fetcher.run(days=args.days, save_db=not args.no_db)
    
    print(f"\n获取统计:")
    for key, count in results.items():
        print(f"  {key}: {count} 条记录")


if __name__ == '__main__':
    main()
