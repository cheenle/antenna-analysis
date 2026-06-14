#!/usr/bin/env python3
"""简化版空间天气数据获取测试"""
import json
import urllib.request
import datetime

def fetch_f107():
    """获取F10.7数据"""
    url = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Test/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            # 取最近7天
            recent = data[-7:] if len(data) > 7 else data
            print(f"✓ F10.7数据: 获取到 {len(recent)} 条记录")
            for d in recent:
                print(f"  {d['time_tag'][:10]}: {d['flux']:.1f} sfu")
            return True
    except Exception as e:
        print(f"✗ F10.7获取失败: {e}")
        return False

def fetch_solar_wind():
    """获取太阳风数据"""
    url = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Test/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            # 跳过表头，取最后10条
            records = data[1:][-10:] if len(data) > 10 else data[1:]
            print(f"\n✓ 太阳风数据: 获取到 {len(records)} 条记录")
            for item in records[-3:]:  # 只显示最后3条
                if len(item) >= 4:
                    print(f"  {item[0]}: Bz={item[3]} nT")
            return True
    except Exception as e:
        print(f"✗ 太阳风获取失败: {e}")
        return False

def fetch_kp():
    """获取Kp指数"""
    url = "https://kp.gfz-potsdam.de/app/json/?startdate=2026-03-08&enddate=2026-03-15"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Test/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            print(f"\n✓ Kp指数数据: 获取到 {len(data)} 天数据")
            # 显示最近一天的数据
            if data:
                latest = data[-1]
                print(f"  日期: {latest['date']}")
                print(f"  Kp值: {latest.get('Kp', [])}")
            return True
    except Exception as e:
        print(f"✗ Kp指数获取失败: {e}")
        return False

print("="*60)
print("空间天气数据获取测试")
print(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*60)

fetch_f107()
fetch_solar_wind()
fetch_kp()

print("\n" + "="*60)
print("测试完成!")
print("="*60)
