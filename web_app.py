#!/usr/bin/env python3
"""
PSK Reporter Web 应用
提供地图可视化展示接收/发射数据
"""

import json
import datetime
import os
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error as MySQLError

# DXCC lookup module
from dxcc_lookup import (
    lookup_callsign, get_continent, get_continent_full, get_dxcc_info, list_all_entities
)
# Shared band definitions (single source of truth)
import band_utils

app = Flask(__name__)
CORS(app)

# 数据库配置 (StarRocks)
DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter",
    "charset": "utf8mb4"
}

# 当前配置的呼号
def get_config_callsign():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            return config.get('callsign', 'BG1SB').upper()
    except:
        return 'BG1SB'

CALLSIGN = get_config_callsign()

# StarRocks hint: single-stage aggregation avoids per-tablet duplicate rows
# on distributed tables (all_records, psk_hdf5). Apply to all GROUP BY queries.
SR_HINT = "/*+ SET_VAR(new_planner_agg_stage=1) */"

# 呼号对应的网格定位（可扩展）
CALLSIGN_GRIDS = {
    'BG1SB': 'ON80da',
    # 可以添加更多呼号的网格定位
}

# ============ 内存缓存层（避免高频刷新打爆 StarRocks）============

import threading
import time as time_module

class TTLCache:
    """简单的 TTL 内存缓存，键值对 + 过期时间"""
    def __init__(self, default_ttl=120):
        self._cache = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key):
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                val, deadline = entry
                if time_module.time() < deadline:
                    return val
                del self._cache[key]
        return None

    def set(self, key, value, ttl=None):
        if ttl is None:
            ttl = self._default_ttl
        with self._lock:
            self._cache[key] = (value, time_module.time() + ttl)

    def invalidate(self, prefix=None):
        with self._lock:
            if prefix:
                self._cache = {k: v for k, v in self._cache.items()
                               if not k.startswith(prefix)}
            else:
                self._cache.clear()

# 全量数据页面缓存 120 秒（统计类数据变化慢，没必要秒级刷新）
ALL_CACHE = TTLCache(default_ttl=120)
# 天线分析缓存 300 秒（网格计算密集，更长的缓存时间）
ANTENNA_CACHE = TTLCache(default_ttl=300)

def all_cache_key(endpoint, hours, band, callsign, year):
    """生成缓存键"""
    return f"{endpoint}:h{hours}:b{band}:c{callsign}:y{year}"

def get_my_location(callsign=None):
    """获取呼号对应的坐标"""
    if callsign is None:
        callsign = CALLSIGN
    grid = CALLSIGN_GRIDS.get(callsign.upper(), 'ON80da')
    return grid_to_latlon(grid)

# DXCC prefix mapping is now handled by the dxcc_lookup module.
# All 290+ DXCC entities with proper prefix matching rules are available.
# Use lookup_callsign(callsign) from dxcc_lookup for callsign-to-entity resolution.
# Use get_continent(country_name) for continent mapping.

# 加载 ALLCALL7 呼号验证数据库
ALLCALL_DB = set()

def load_allcall_db():
    """加载 ALLCALL7 数据库"""
    global ALLCALL_DB
    script_dir = os.path.dirname(os.path.abspath(__file__))
    allcall_path = os.path.join(script_dir, 'ALLCALL7.TXT')
    
    if os.path.exists(allcall_path):
        try:
            with open(allcall_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('//'):
                        # 格式: "CALLSIGN,"
                        callsign = line.rstrip(',').strip()
                        if callsign:
                            ALLCALL_DB.add(callsign.upper())
            print(f"已加载 {len(ALLCALL_DB)} 个有效呼号到验证数据库")
        except Exception as e:
            print(f"加载 ALLCALL7 数据库失败: {e}")
    else:
        print(f"ALLCALL7.TXT 文件不存在: {allcall_path}")

def is_valid_callsign(callsign):
    """验证呼号是否在 ALLCALL7 数据库中"""
    if not callsign:
        return False
    return callsign.upper() in ALLCALL_DB

def get_dxcc_from_callsign(callsign):
    """
    根据呼号获取 DXCC 国家/地区
    
    委托给 dxcc_lookup 模块，该模块包含完整的 ARRL DXCC 实体映射。
    
    Args:
        callsign: 业余无线电呼号
    
    Returns:
        DXCC 实体名称，或 None
    """
    result = lookup_callsign(callsign)
    return result["name"] if result else None


def get_dxcc_continent(country_name: str) -> str:
    """
    根据 DXCC 实体名称获取大洲代码
    
    Args:
        country_name: DXCC 实体名称
    
    Returns:
        大洲名称（中文）
    """
    if not country_name:
        return "Unknown"
    
    code = get_continent(country_name)
    return get_continent_full(code)


# DXCC Entity name normalization table (PSK Reporter -> dxcc_lookup names)
# Maps common variant names to the canonical names used in dxcc_lookup
DXCC_NAME_ALIASES = {
    "United States of America": "United States",
    "USA": "United States",
    "US": "United States",
    "UK": "England",
    "Great Britain": "England",
    "Deutschland": "Germany",
    "Russian Federation": "European Russia",
    "South Korea": "Republic of Korea",
    "Korea": "Republic of Korea",
    "North Korea": "Democratic People's Republic of Korea",
    "DPRK": "Democratic People's Republic of Korea",
    "Holland": "Netherlands",
    "Czechia": "Czech Republic",
    "Slovakia": "Slovak Republic",
    "Taiwan (Province of China)": "Taiwan",
    "Macau": "Macao",
    "Democratic Republic of the Congo": "Congo (Dem. Rep.)",
    "Republic of the Congo": "Congo (Rep.)",
    "Swaziland": "Swaziland (Eswatini)",
    "Eswatini": "Swaziland (Eswatini)",
    "Federated States of Micronesia": "Micronesia",
    "Wallis and Futuna": "Wallis & Futuna",
    "Trinidad and Tobago": "Trinidad & Tobago",
    "Antigua and Barbuda": "Antigua & Barbuda",
    "St. Kitts and Nevis": "St. Kitts & Nevis",
    "St. Pierre and Miquelon": "St. Pierre & Miquelon",
    "Sao Tome and Principe": "Sao Tome & Principe",
    "Turks and Caicos": "Turks & Caicos",
    "Saba and St. Eustatius": "Saba & St. Eustatius",
    "St. Vincent and the Grenadines": "St. Vincent",
    "Myanmar (Burma)": "Myanmar",
    "Burma": "Myanmar",
    "Ivory Coast": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Timor-Leste": "East Timor",
    "Western Samoa": "Samoa",
}


def normalize_dxcc_name(name: str) -> str:
    """
    Normalize a DXCC entity name from external sources to the canonical form.
    
    Args:
        name: Entity name from PSK Reporter API or database
    
    Returns:
        Canonical entity name used in dxcc_lookup
    """
    if not name:
        return ""
    
    name = name.strip()
    
    # Direct alias match
    if name in DXCC_NAME_ALIASES:
        return DXCC_NAME_ALIASES[name]
    
    # Case-insensitive alias lookup
    name_lower = name.lower()
    for alias, canonical in DXCC_NAME_ALIASES.items():
        if alias.lower() == name_lower:
            return canonical
    
    return name

# 应用启动时加载数据库
load_allcall_db()

# Maidenhead 网格定位转换为经纬度
def grid_to_latlon(grid):
    """
    将 Maidenhead 网格定位转换为经纬度
    
    Args:
        grid: 网格定位字符串 (如 ON80da)
    
    Returns:
        (latitude, longitude) 或 None
    """
    if not grid or len(grid) < 4:
        return None
    
    grid = grid.upper()
    
    try:
        # 字段 (A-R -> 0-17)
        lon1 = ord(grid[0]) - ord('A')
        lat1 = ord(grid[1]) - ord('A')
        
        # 方格 (0-9)
        lon2 = int(grid[2])
        lat2 = int(grid[3])
        
        # 子方格 (a-x -> 0-23)
        lon3 = 0
        lat3 = 0
        if len(grid) >= 6:
            lon3 = ord(grid[4].lower()) - ord('a')
            lat3 = ord(grid[5].lower()) - ord('a')
        
        # 计算经纬度
        lon = -180 + (lon1 * 20) + (lon2 * 2) + (lon3 * (2/24)) + (1/24)
        lat = -90 + (lat1 * 10) + (lat2 * 1) + (lat3 * (1/24)) + (1/48)
        
        return (round(lat, 4), round(lon, 4))
    except (ValueError, IndexError):
        return None


def get_db_connection():
    """获取数据库连接"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except MySQLError as e:
        print(f"数据库连接错误: {e}")
        return None


@app.route('/api/config')
def get_config():
    """获取当前配置"""
    return jsonify({
        "callsign": CALLSIGN,
        "grid": CALLSIGN_GRIDS.get(CALLSIGN, 'ON80da'),
        "location": get_my_location()
    })


@app.route('/')
def index():
    """主页"""
    return render_template('index.html', active_page='index')


@app.route('/api/records')
def get_records():
    """
    获取记录数据 API
    
    参数:
        type: 'sender' 或 'receiver' 或 'all' (默认 'all')
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM:SS)
        end_time: 结束时间
        limit: 限制返回数量 (默认 1000)
        callsign: 指定呼号过滤 (可选，默认使用配置的呼号)
    """
    record_type = request.args.get('type', 'all')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    limit = int(request.args.get('limit', 1000))
    callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    results = {
        "sender_records": [],
        "receiver_records": [],
        "my_location": get_my_location(callsign),
        "total_sender": 0,
        "total_receiver": 0,
        "callsign": callsign
    }
    
    try:
        # 构建时间条件
        time_condition = ""
        params = []
        
        if start_time:
            time_condition += " AND qso_time >= %s"
            params.append(start_time)
        if end_time:
            time_condition += " AND qso_time <= %s"
            params.append(end_time)
        
        # 获取发送记录 (本台发射被他台接收，去重)
        if record_type in ['all', 'sender']:
            sender_sql = f"""
                SELECT DISTINCT receiver_callsign, receiver_locator, 
                       frequency, snr, mode, qso_time, 
                       distance, bearing, country
                FROM sender_records 
                WHERE sender_callsign = %s {time_condition}
                ORDER BY qso_time DESC 
                LIMIT %s
            """
            sender_params = [callsign] + params + [limit]
            cursor.execute(sender_sql, sender_params)
            sender_records = cursor.fetchall()
            
            for record in sender_records:
                # 获取对方位置
                other_loc = grid_to_latlon(record['receiver_locator'])
                if other_loc:
                    results["sender_records"].append({
                        "callsign": record['receiver_callsign'],
                        "locator": record['receiver_locator'],
                        "lat": other_loc[0],
                        "lon": other_loc[1],
                        "frequency": record['frequency'],
                        "snr": record['snr'],
                        "mode": record['mode'],
                        "qso_time": record['qso_time'].isoformat() if record['qso_time'] else None,
                        "distance": float(record['distance']) if record['distance'] else None,
                        "bearing": float(record['bearing']) if record['bearing'] else None,
                        "country": record['country'],
                        "type": "sender"
                    })
            
            # 获取总数（去重）
            count_sql = f"""
                SELECT COUNT(DISTINCT receiver_callsign, frequency, qso_time) as cnt 
                FROM sender_records 
                WHERE sender_callsign = %s {time_condition}
            """
            cursor.execute(count_sql, [callsign] + params)
            results["total_sender"] = cursor.fetchone()['cnt']
        
        # 获取接收记录 (本台接收到他台信号，去重)
        if record_type in ['all', 'receiver']:
            receiver_sql = f"""
                SELECT DISTINCT sender_callsign, sender_locator, 
                       frequency, snr, mode, qso_time, 
                       distance, bearing, country
                FROM receiver_records 
                WHERE receiver_callsign = %s {time_condition}
                ORDER BY qso_time DESC 
                LIMIT %s
            """
            receiver_params = [callsign] + params + [limit]
            cursor.execute(receiver_sql, receiver_params)
            receiver_records = cursor.fetchall()
            
            for record in receiver_records:
                # 获取对方位置
                other_loc = grid_to_latlon(record['sender_locator'])
                if other_loc:
                    results["receiver_records"].append({
                        "callsign": record['sender_callsign'],
                        "locator": record['sender_locator'],
                        "lat": other_loc[0],
                        "lon": other_loc[1],
                        "frequency": record['frequency'],
                        "snr": record['snr'],
                        "mode": record['mode'],
                        "qso_time": record['qso_time'].isoformat() if record['qso_time'] else None,
                        "distance": float(record['distance']) if record['distance'] else None,
                        "bearing": float(record['bearing']) if record['bearing'] else None,
                        "country": record['country'],
                        "type": "receiver"
                    })
            
            # 获取总数（去重）
            count_sql = f"""
                SELECT COUNT(DISTINCT sender_callsign, frequency, qso_time) as cnt 
                FROM receiver_records 
                WHERE receiver_callsign = %s {time_condition}
            """
            cursor.execute(count_sql, [callsign] + params)
            results["total_receiver"] = cursor.fetchone()['cnt']
        
    except MySQLError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
    
    return jsonify(results)


@app.route('/api/stats')
def get_stats():
    """获取统计数据 - 支持时间筛选和呼号过滤"""
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        stats = {"callsign": callsign}
        
        # 构建时间条件
        time_condition = ""
        params = [callsign]
        if start_time:
            time_condition += " AND qso_time >= %s"
            params.append(start_time)
        if end_time:
            time_condition += " AND qso_time <= %s"
            params.append(end_time)
        
        # 总记录数（去重：同一 spot 多次抓取只算一次）
        cursor.execute(f"""
            SELECT COUNT(DISTINCT receiver_callsign, frequency, qso_time) as cnt 
            FROM sender_records 
            WHERE sender_callsign = %s{time_condition}
        """, params)
        stats['total_sender'] = cursor.fetchone()['cnt']
        
        cursor.execute(f"""
            SELECT COUNT(DISTINCT sender_callsign, frequency, qso_time) as cnt 
            FROM receiver_records 
            WHERE receiver_callsign = %s{time_condition}
        """, params)
        stats['total_receiver'] = cursor.fetchone()['cnt']
        
        # 按模式统计（去重）
        cursor.execute(f"""
            SELECT mode, COUNT(*) as cnt 
            FROM (
                SELECT DISTINCT receiver_callsign, mode, frequency, qso_time
                FROM sender_records 
                WHERE sender_callsign = %s{time_condition}
            ) t
            GROUP BY mode 
            ORDER BY cnt DESC
        """, params)
        stats['modes'] = cursor.fetchall()
        
        # 按国家统计 (去重，过滤空值)
        cursor.execute(f"""
            SELECT country, COUNT(*) as cnt 
            FROM (
                SELECT DISTINCT receiver_callsign, country, frequency, qso_time
                FROM sender_records 
                WHERE sender_callsign = %s 
                  AND country IS NOT NULL 
                  AND country != ''{time_condition}
            ) t
            GROUP BY country 
            ORDER BY cnt DESC 
            LIMIT 10
        """, params)
        stats['top_countries'] = cursor.fetchall()
        
        # 时间范围
        cursor.execute(f"SELECT MIN(qso_time) as min_time, MAX(qso_time) as max_time FROM sender_records WHERE sender_callsign = %s{time_condition}", params)
        time_range = cursor.fetchone()
        stats['time_range'] = {
            "start": time_range['min_time'].isoformat() if time_range['min_time'] else None,
            "end": time_range['max_time'].isoformat() if time_range['max_time'] else None
        }
        
        return jsonify(stats)
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/fetch_log')
def get_fetch_log():
    """获取数据获取日志"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT id, callsign, fetch_time, sender_count, receiver_count, source, adif_file
            FROM fetch_log 
            ORDER BY fetch_time DESC 
            LIMIT 20
        """)
        logs = cursor.fetchall()
        
        for log in logs:
            log['fetch_time'] = log['fetch_time'].isoformat() if log['fetch_time'] else None
        
        return jsonify(logs)
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/validate/<callsign>')
def validate_callsign(callsign):
    """
    验证呼号是否有效
    
    Args:
        callsign: 要验证的呼号
    
    Returns:
        {
            "callsign": "呼号",
            "valid": true/false,
            "dxcc": "国家/地区",
            "dxcc_source": "数据库/前缀推断"
        }
    """
    callsign = callsign.upper().strip()
    
    result = {
        "callsign": callsign,
        "valid": is_valid_callsign(callsign),
        "dxcc": None,
        "dxcc_source": None
    }
    
    # 尝试从数据库获取 DXCC
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # 从发送记录查询
            cursor.execute("""
                SELECT DISTINCT country, dxcc FROM sender_records 
                WHERE sender_callsign = %s OR receiver_callsign = %s
                LIMIT 1
            """, (callsign, callsign))
            row = cursor.fetchone()
            if row and row['country']:
                result['dxcc'] = row['country']
                result['dxcc_source'] = 'database'
        finally:
            cursor.close()
            conn.close()
    
    # 如果数据库没有，尝试前缀推断
    if not result['dxcc']:
        dxcc = get_dxcc_from_callsign(callsign)
        if dxcc:
            result['dxcc'] = dxcc
            result['dxcc_source'] = 'prefix'
    
    return jsonify(result)


@app.route('/api/dxcc_analysis')
def dxcc_analysis():
    """
    DXCC 分析 API（改进版）
    
    使用 dxcc_lookup 模块进行完整 DXCC 实体解析。
    结合数据库中的 country 字段和呼号前缀推断。
    
    参数:
        type: 'sender' 或 'receiver' 或 'all' (默认 'all')
        start_time: 开始时间
        end_time: 结束时间
        callsign: 呼号过滤 (默认使用配置的呼号)
    """
    record_type = request.args.get('type', 'all')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        time_condition = ""
        params = [callsign]
        
        if start_time:
            time_condition += " AND qso_time >= %s"
            params.append(start_time)
        if end_time:
            time_condition += " AND qso_time <= %s"
            params.append(end_time)
        
        result = {
            "dxcc_stats": [],
            "total_unique_callsigns": 0,
            "unique_dxcc_entities": 0,
            "by_continent": {},
            "allcall_db_size": len(ALLCALL_DB),
            "callsign": callsign
        }
        
        # Collect unique callsigns with their database country
        unique_callsigns = {}
        
        if record_type in ['all', 'sender']:
            sql = f"""
                SELECT DISTINCT receiver_callsign as callsign, country 
                FROM sender_records 
                WHERE sender_callsign = %s {time_condition}
            """
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                cs = row['callsign']
                if cs and cs not in unique_callsigns:
                    unique_callsigns[cs] = row.get('country')
        
        if record_type in ['all', 'receiver']:
            sql = f"""
                SELECT DISTINCT sender_callsign as callsign, country 
                FROM receiver_records 
                WHERE receiver_callsign = %s {time_condition}
            """
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                cs = row['callsign']
                if cs and cs not in unique_callsigns:
                    unique_callsigns[cs] = row.get('country')
        
        # Use dxcc_lookup to resolve each callsign to its DXCC entity
        dxcc_data = {}  # entity_name -> {count, callsigns, continent}
        
        for callsign_str, db_country in unique_callsigns.items():
            # Determine DXCC entity: prefer database country, fall back to prefix lookup
            dxcc_name = None
            
            if db_country:
                # Try normalizing the database country name
                norm = normalize_dxcc_name(db_country)
                info = get_dxcc_info(norm)
                if info:
                    dxcc_name = info["name"]
                else:
                    dxcc_name = db_country  # Use as-is if not in our map
            
            if not dxcc_name:
                # Fall back to prefix-based lookup
                result_lookup = lookup_callsign(callsign_str)
                if result_lookup:
                    dxcc_name = result_lookup["name"]
            
            if not dxcc_name:
                dxcc_name = "Unknown"
            
            if dxcc_name not in dxcc_data:
                continent_code = get_continent(normalize_dxcc_name(dxcc_name))
                continent_full = get_continent_full(continent_code)
                dxcc_data[dxcc_name] = {
                    "count": 0,
                    "callsigns": [],
                    "continent": continent_full,
                    "continent_code": continent_code
                }
            
            dxcc_data[dxcc_name]["count"] += 1
            dxcc_data[dxcc_name]["callsigns"].append(callsign_str)
        
        # Build sorted DXCC stats
        dxcc_list = []
        for entity_name, data in dxcc_data.items():
            dxcc_list.append({
                "country": entity_name,
                "count": data["count"],
                "callsigns": data["callsigns"][:5],  # Sample of callsigns
                "continent": data["continent"]
            })
        
        dxcc_list.sort(key=lambda x: x["count"], reverse=True)
        
        # Build continent stats
        continent_stats = {}
        for item in dxcc_list:
            cont = item["continent"]
            if cont not in continent_stats:
                continent_stats[cont] = {"entities": 0, "callsigns": 0}
            continent_stats[cont]["entities"] += 1
            continent_stats[cont]["callsigns"] += item["count"]
        
        result["dxcc_stats"] = dxcc_list
        result["total_unique_callsigns"] = len(unique_callsigns)
        result["unique_dxcc_entities"] = len(dxcc_data)
        result["by_continent"] = continent_stats
        
        return jsonify(result)
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/unvalidated_callsigns')
def get_unvalidated_callsigns():
    """
    获取未验证的呼号列表
    
    参数:
        limit: 返回数量限制 (默认 50)
    """
    limit = int(request.args.get('limit', 50))
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        unique_callsigns = set()
        
        # 获取所有对方呼号
        cursor.execute("SELECT DISTINCT receiver_callsign FROM sender_records")
        for row in cursor.fetchall():
            if row['receiver_callsign']:
                unique_callsigns.add(row['receiver_callsign'])
        
        cursor.execute("SELECT DISTINCT sender_callsign FROM receiver_records")
        for row in cursor.fetchall():
            if row['sender_callsign']:
                unique_callsigns.add(row['sender_callsign'])
        
        # 筛选未验证的呼号
        unvalidated = []
        for cs in unique_callsigns:
            if not is_valid_callsign(cs):
                dxcc = get_dxcc_from_callsign(cs)
                unvalidated.append({
                    "callsign": cs,
                    "dxcc": dxcc or "Unknown"
                })
        
        # 按呼号排序
        unvalidated.sort(key=lambda x: x["callsign"])
        
        return jsonify({
            "total_unvalidated": len(unvalidated),
            "callsigns": unvalidated[:limit]
        })
        
    finally:
        cursor.close()
        conn.close()


def get_band_from_frequency(freq):
    """根据频率返回波段名称 — 委托给 band_utils"""
    return band_utils.get_band_from_frequency(freq)


@app.route('/api/band_analysis')
def band_analysis():
    """
    波段传播分析 API
    
    参数:
        start_time: 开始时间
        end_time: 结束时间
        callsign: 呼号过滤 (默认使用配置的呼号)
    
    返回:
        {
            "bands": [{"band": "40m", "count": 1000, "unique_stations": 500}],
            "hourly": [{"hour": 0, "band": "10m", "count": 100}, ...],
            "best_time": {"40m": {"best_hour": 21, "count": 285}, ...}
        }
    """
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        time_condition = ""
        params = [callsign]
        if start_time:
            time_condition += " AND qso_time >= %s"
            params.append(start_time)
        if end_time:
            time_condition += " AND qso_time <= %s"
            params.append(end_time)
        
        result = {
            "bands": [],
            "hourly": [],
            "best_time": {},
            "callsign": callsign
        }
        
        # 按波段统计（去重后用 CASE_BAND_SQL 聚合，避免按 Hz 粒度扫描）
        cursor.execute(f"""
            SELECT {band_utils.CASE_BAND_SQL} as band,
                   COUNT(*) as cnt,
                   COUNT(DISTINCT callsign) as unique_stations
            FROM (
                SELECT DISTINCT receiver_callsign as callsign, frequency
                FROM sender_records 
                WHERE sender_callsign = %s {time_condition}
            ) spots
            GROUP BY band
            ORDER BY cnt DESC
        """, params)
        
        for row in cursor.fetchall():
            result["bands"].append({
                "band": row['band'],
                "count": row['cnt'],
                "unique_stations": row['unique_stations']
            })
        
        # 按小时和波段统计（去重）
        cursor.execute(f"""
            SELECT {band_utils.CASE_BAND_SQL} as band,
                   HOUR(qso_time) as hour,
                   COUNT(*) as cnt
            FROM (
                SELECT DISTINCT receiver_callsign, frequency, qso_time
                FROM sender_records 
                WHERE sender_callsign = %s {time_condition}
            ) spots
            GROUP BY band, hour
            ORDER BY hour, cnt DESC
        """, params)
        # 计算每个波段的最佳时间（从去重后的 hourly 数据）
        band_hourly = {}
        for row in cursor.fetchall():
            hour = row['hour']
            band = row['band']
            cnt = row['cnt']
            if band not in band_hourly:
                band_hourly[band] = {}
            band_hourly[band][hour] = cnt
            
            result["hourly"].append({
                "hour": hour,
                "band": band,
                "count": cnt
            })
        
        for band, hours in band_hourly.items():
            if hours:
                best_hour = max(hours.items(), key=lambda x: x[1])
                result["best_time"][band] = {
                    "best_hour": best_hour[0],
                    "count": best_hour[1]
                }
        
        return jsonify(result)
        
    finally:
        cursor.close()
        conn.close()


# ============ 通联日志 API ============

@app.route('/qso')
def qso_page():
    """通联日志分析页面"""
    return render_template('qso.html', active_page='qso')


@app.route('/api/qso/records')
def get_qso_records():
    """
    获取通联记录 API
    
    参数:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        band: 波段过滤
        mode: 模式过滤
        country: 国家过滤
        limit: 限制返回数量 (默认 500)
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    band = request.args.get('band')
    mode = request.args.get('mode')
    country = request.args.get('country')
    limit = int(request.args.get('limit', 500))
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        conditions = []
        params = []
        
        if start_date:
            conditions.append("qso_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("qso_date <= %s")
            params.append(end_date)
        if band:
            conditions.append("band = %s")
            params.append(band)
        if mode:
            conditions.append("mode = %s")
            params.append(mode)
        if country:
            conditions.append("country = %s")
            params.append(country)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        sql = f"""
            SELECT id, callsign, station_callsign, grid_locator, my_grid_locator,
                   mode, rst_sent, rst_rcvd, qso_date, qso_time, band, frequency,
                   tx_pwr, distance, bearing, country, dxcc, comment
            FROM qso_log
            WHERE {where_clause}
            ORDER BY qso_time DESC
            LIMIT %s
        """
        params.append(limit)
        
        cursor.execute(sql, params)
        records = cursor.fetchall()
        
        for record in records:
            record['qso_date'] = record['qso_date'].isoformat() if record['qso_date'] else None
            record['qso_time'] = record['qso_time'].isoformat() if record['qso_time'] else None
            if record['frequency']:
                record['frequency'] = float(record['frequency'])
            if record['distance']:
                record['distance'] = float(record['distance'])
            if record['bearing']:
                record['bearing'] = float(record['bearing'])
        
        return jsonify({
            "records": records,
            "total": len(records)
        })
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/qso/stats')
def get_qso_stats():
    """获取通联统计数据"""
    station_callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        stats = {"station_callsign": station_callsign}
        
        # 总通联数
        cursor.execute("""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT callsign) as unique_callsigns,
                   COUNT(DISTINCT country) as unique_countries,
                   COUNT(DISTINCT band) as unique_bands,
                   COUNT(DISTINCT mode) as unique_modes
            FROM qso_log
            WHERE station_callsign = %s
        """, (station_callsign,))
        
        row = cursor.fetchone()
        stats['total_qsos'] = row['total']
        stats['unique_callsigns'] = row['unique_callsigns']
        stats['unique_countries'] = row['unique_countries']
        stats['unique_bands'] = row['unique_bands']
        stats['unique_modes'] = row['unique_modes']
        
        # 时间范围
        cursor.execute("""
            SELECT MIN(qso_date) as first_qso, MAX(qso_date) as last_qso
            FROM qso_log
            WHERE station_callsign = %s
        """, (station_callsign,))
        
        row = cursor.fetchone()
        stats['first_qso'] = row['first_qso'].isoformat() if row['first_qso'] else None
        stats['last_qso'] = row['last_qso'].isoformat() if row['last_qso'] else None
        
        # 按波段统计
        cursor.execute("""
            SELECT band, COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s AND band IS NOT NULL
            GROUP BY band
            ORDER BY count DESC
        """, (station_callsign,))
        stats['by_band'] = cursor.fetchall()
        
        # 按模式统计
        cursor.execute("""
            SELECT mode, COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s AND mode IS NOT NULL
            GROUP BY mode
            ORDER BY count DESC
        """, (station_callsign,))
        stats['by_mode'] = cursor.fetchall()
        
        # 按国家统计 TOP 20
        cursor.execute("""
            SELECT country, COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s AND country IS NOT NULL
            GROUP BY country
            ORDER BY count DESC
            LIMIT 20
        """, (station_callsign,))
        stats['by_country'] = cursor.fetchall()
        
        # 按年份月份统计
        cursor.execute("""
            SELECT 
                YEAR(qso_date) as year,
                MONTH(qso_date) as month,
                COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s
            GROUP BY year, month
            ORDER BY year DESC, month DESC
            LIMIT 24
        """, (station_callsign,))
        stats['by_month'] = cursor.fetchall()
        
        # 按小时统计 (UTC)
        cursor.execute("""
            SELECT 
                HOUR(qso_time) as hour,
                COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s
            GROUP BY hour
            ORDER BY hour
        """, (station_callsign,))
        stats['by_hour'] = cursor.fetchall()
        
        # 最远通联
        cursor.execute("""
            SELECT callsign, grid_locator, country, distance, band, mode, qso_date
            FROM qso_log
            WHERE station_callsign = %s AND distance IS NOT NULL
            ORDER BY distance DESC
            LIMIT 10
        """, (station_callsign,))
        stats['longest_qsos'] = cursor.fetchall()
        for row in stats['longest_qsos']:
            if row['qso_date']:
                row['qso_date'] = row['qso_date'].isoformat()
            if row['distance']:
                row['distance'] = float(row['distance'])
        
        return jsonify(stats)
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/qso/dxcc_progress')
def get_dxcc_progress():
    """
    DXCC 进度统计
    
    返回: 已通联的国家/地区列表及数量
    """
    station_callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 获取已通联的 DXCC 列表
        cursor.execute("""
            SELECT country, COUNT(*) as count,
                   MIN(qso_date) as first_qso,
                   MAX(qso_date) as last_qso
            FROM qso_log
            WHERE station_callsign = %s AND country IS NOT NULL
            GROUP BY country
            ORDER BY count DESC
        """, (station_callsign,))
        
        countries = cursor.fetchall()
        for row in countries:
            row['first_qso'] = row['first_qso'].isoformat() if row['first_qso'] else None
            row['last_qso'] = row['last_qso'].isoformat() if row['last_qso'] else None
        
        # 总 DXCC 数量统计
        total_dxcc = len(countries)
        
        # 按大洲分组（使用 dxcc_lookup 模块获取大洲）
        by_continent = {}
        for country in countries:
            name = country['country']
            # Normalize name for continent lookup
            norm_name = normalize_dxcc_name(name)
            continent_code = get_continent(norm_name)
            continent = get_continent_full(continent_code)
            
            if continent not in by_continent:
                by_continent[continent] = {"count": 0, "countries": []}
            by_continent[continent]["count"] += 1
            by_continent[continent]["countries"].append(name)
        
        return jsonify({
            "total_dxcc": total_dxcc,
            "countries": countries[:50],  # 返回前50个
            "by_continent": by_continent
        })
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/qso/band_analysis')
def get_qso_band_analysis():
    """
    波段传播分析
    
    分析每个波段的最佳通联时间、最远距离等
    """
    station_callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        result = {"bands": {}}
        
        # 按波段统计
        cursor.execute("""
            SELECT 
                band,
                COUNT(*) as total_qsos,
                COUNT(DISTINCT callsign) as unique_callsigns,
                COUNT(DISTINCT country) as unique_countries,
                MAX(distance) as max_distance,
                AVG(distance) as avg_distance
            FROM qso_log
            WHERE station_callsign = %s AND band IS NOT NULL
            GROUP BY band
            ORDER BY total_qsos DESC
        """, (station_callsign,))
        
        for row in cursor.fetchall():
            band = row['band']
            result['bands'][band] = {
                "total_qsos": row['total_qsos'],
                "unique_callsigns": row['unique_callsigns'],
                "unique_countries": row['unique_countries'],
                "max_distance": float(row['max_distance']) if row['max_distance'] else None,
                "avg_distance": round(float(row['avg_distance']), 1) if row['avg_distance'] else None
            }
        
        # 按波段和小时统计
        cursor.execute("""
            SELECT 
                band,
                HOUR(qso_time) as hour,
                COUNT(*) as count
            FROM qso_log
            WHERE station_callsign = %s AND band IS NOT NULL
            GROUP BY band, hour
            ORDER BY band, hour
        """, (station_callsign,))
        
        band_hours = {}
        for row in cursor.fetchall():
            band = row['band']
            if band not in band_hours:
                band_hours[band] = {}
            band_hours[band][row['hour']] = row['count']
        
        # 计算每个波段的最佳时间
        for band, hours in band_hours.items():
            if hours:
                best_hour = max(hours.items(), key=lambda x: x[1])
                if band in result['bands']:
                    result['bands'][band]['best_hour'] = best_hour[0]
                    result['bands'][band]['best_hour_count'] = best_hour[1]
                    result['bands'][band]['hourly'] = hours
        
        return jsonify(result)
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/qso/map_data')
def get_qso_map_data():
    """
    获取通联地图数据
    
    返回所有通联位置的坐标，用于地图展示
    """
    station_callsign = request.args.get('callsign', CALLSIGN).upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT DISTINCT
                callsign,
                grid_locator,
                country,
                COUNT(*) as qso_count,
                MAX(distance) as distance,
                MAX(qso_date) as last_qso
            FROM qso_log
            WHERE station_callsign = %s AND grid_locator IS NOT NULL AND grid_locator != ''
            GROUP BY callsign, grid_locator, country
        """, (station_callsign,))
        
        locations = []
        for row in cursor.fetchall():
            loc = grid_to_latlon(row['grid_locator'])
            if loc:
                locations.append({
                    "callsign": row['callsign'],
                    "grid": row['grid_locator'],
                    "lat": loc[0],
                    "lon": loc[1],
                    "country": row['country'],
                    "qso_count": row['qso_count'],
                    "distance": float(row['distance']) if row['distance'] else None,
                    "last_qso": row['last_qso'].isoformat() if row['last_qso'] else None
                })
        
        return jsonify({
            "locations": locations,
            "total": len(locations)
        })
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/qso/recent')
def get_recent_qsos():
    """获取最近的通联记录"""
    limit = int(request.args.get('limit', 20))
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT callsign, grid_locator, mode, rst_sent, rst_rcvd, 
                   band, frequency, distance, country, qso_date, qso_time
            FROM qso_log
            ORDER BY qso_time DESC
            LIMIT %s
        """, (limit,))
        
        records = cursor.fetchall()
        for record in records:
            record['qso_date'] = record['qso_date'].isoformat() if record['qso_date'] else None
            record['qso_time'] = record['qso_time'].isoformat() if record['qso_time'] else None
            if record['distance']:
                record['distance'] = float(record['distance'])
            if record['frequency']:
                record['frequency'] = float(record['frequency'])
        
        return jsonify({"records": records})
        
    finally:
        cursor.close()
        conn.close()


# ============ ALL 全量数据分析 API ============

def get_all_table(year=None):
    """根据年份返回对应的全量数据表名"""
    if year and int(year) == 2025:
        return 'psk_hdf5'
    return 'all_records'

SUMMARY_TABLE = 'psk_hdf5_summary'
SUMMARY_2026 = 'all_records_summary'
RAW_2025_PARTITIONS = ['p202501', 'p202502', 'p202503', 'p202504']

def get_summary_table(year):
    """返回对应年份的汇总表名"""
    return SUMMARY_TABLE if (year and int(year) == 2025) else SUMMARY_2026

def get_raw_table_and_partitions(year):
    """返回 (table, partitions_or_None) — 2025 用 psk_hdf5 分区, 2026 用 all_records 全表"""
    if year and int(year) == 2025:
        return 'psk_hdf5', RAW_2025_PARTITIONS
    return 'all_records', None

def use_summary(year, callsign_filter=''):
    """是否使用预聚合汇总表。2025/2026 都支持。呼号搜索时退化到原表。"""
    if callsign_filter:
        return False
    return True

def summary_time_filter(hours, year='2026'):
    """
    汇总表的时间过滤 — 将 hours 参数转换为 day 范围。
    hours=24 → 最近一天，hours=0 → 全量。
    """
    if hours > 0 and hours <= 720:
        # 按小时范围估算天数（汇总表 day 粒度）
        days = max(1, hours // 24)
        return f"day >= DATE_SUB((SELECT MAX(day) FROM {get_summary_table(year)}), INTERVAL {days} DAY)"
    return None  # 全量，不加过滤

def psk_hdf5_time_clause(hours):
    """
    原表 psk_hdf5 的时间过滤 — 将相对 hours 转换为 2025 年绝对日期范围。

    psk_hdf5 数据范围: 2025-01-01 ~ 2025-04-22。
    DATE_SUB(NOW(), INTERVAL X HOUR) 对 2025 年数据无效（NOW() 是 2026 年）。
    """
    if hours > 0 and hours <= 720:
        days = max(1, hours // 24)
        return "qso_time >= DATE_SUB('2025-04-22 23:59:59', INTERVAL %s DAY)", [days]
    return None, []  # 全量

def build_time_condition(table_name, hours):
    """
    为不同表构建正确的时间过滤条件。

    - all_records: 用相对时间 DATE_SUB(NOW(), ...)（数据接近实时）
    - psk_hdf5: 用绝对日期范围（历史数据，NOW() 对不上）
    """
    if table_name == 'psk_hdf5':
        clause, params = psk_hdf5_time_clause(hours)
        if clause:
            return [clause], params
        return [], []
    else:
        # all_records — 正常相对时间
        if hours > 0:
            capped = min(hours, 720)
            return ["qso_time >= DATE_SUB(NOW(), INTERVAL %s HOUR)"], [capped]
        return [], []

@app.route('/all')
def all_analysis_page():
    """全量数据分析页面"""
    return render_template('all.html', active_page='all')


def _get_all_stats_from_summary(hours, band_filter, callsign_filter, year, start_time):
    """从预聚合汇总表获取统计数据（毫秒级）"""
    import time
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        stats = {"_summary": True}

        # 时间过滤
        time_clause = summary_time_filter(hours, year)

        # 波段过滤
        band_clause = ""
        band_params = []
        if band_filter and band_filter in band_utils.BAND_FREQ_MAP:
            band_clause = " AND band = %s"
            band_params = [band_filter]

        # 总数、时间范围
        cursor.execute(f"""
            SELECT SUM(spot_count) as total,
                   MIN(day) as first_record,
                   MAX(day) as last_record
            FROM {get_summary_table(year)}
            WHERE 1=1 {' AND ' + time_clause if time_clause else ''} {band_clause}
        """, band_params)
        row = cursor.fetchone()
        stats['total_records'] = row['total'] or 0
        stats['first_record'] = row['first_record'].isoformat() if row['first_record'] else None
        stats['last_record'] = row['last_record'].isoformat() if row['last_record'] else None

        # 唯一呼号数 — 汇总表不存储独立呼号，改用 country/mode 维度作为参考
        # 直接从汇总表的 country/mode 维度估算活跃度（比全扫 psk_hdf5 快 1000x）
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                COUNT(DISTINCT sender_country) as unique_countries,
                   COUNT(DISTINCT mode) as unique_modes
            FROM {get_summary_table(year)}
            WHERE 1=1 {' AND ' + time_clause if time_clause else ''}
        """)
        urow = cursor.fetchone()
        stats['unique_senders'] = urow['unique_countries'] or 0  # 保守估计
        stats['unique_receivers'] = urow['unique_countries'] or 0
        stats['_unique_estimated'] = True
        stats['_note'] = 'Unique counts shown as country count (proxy); exact distinct callsigns not available in summary'

        # 按模式统计
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                mode, SUM(spot_count) as count
            FROM {get_summary_table(year)}
            WHERE 1=1 {' AND ' + time_clause if time_clause else ''} {band_clause}
            GROUP BY mode
            ORDER BY count DESC
            LIMIT 10
        """, band_params)
        stats['by_mode'] = cursor.fetchall()

        # 按波段统计
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                band, SUM(spot_count) as count
            FROM {get_summary_table(year)}
            WHERE 1=1 {' AND ' + time_clause if time_clause else ''}
            GROUP BY band
            ORDER BY count DESC
        """)
        stats['by_band'] = [{"band": r['band'], "count": r['count']} for r in cursor.fetchall()]

        # 按小时统计（取最近一天）
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                hour, SUM(spot_count) as count
            FROM {get_summary_table(year)}
            WHERE day = (SELECT MAX(day) FROM {get_summary_table(year)})
            GROUP BY hour
            ORDER BY hour
        """)
        stats['hourly_timeline'] = cursor.fetchall()
        # 转换为前端期望的格式
        stats['hourly_timeline'] = [
            {"minute": f"{r['hour']:02d}:00", "count": r['count']}
            for r in stats['hourly_timeline']
        ]

        stats['query_time_ms'] = int((time.time() - start_time) * 1000)

        resp = jsonify(stats)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    finally:
        cursor.close()
        conn.close()


@app.route('/api/all/stats')
def get_all_stats():
    """
    获取全量数据统计摘要（优化版）

    返回: 总记录数、唯一呼号数、时间范围等

    参数:
        band: 波段过滤（可选）
        callsign: 呼号搜索（可选）
        hours: 时间范围（默认24小时）
    """
    import time
    start_time = time.time()

    band_filter = request.args.get('band', '')
    callsign_filter = request.args.get('callsign', '')
    hours = int(request.args.get('hours', 24))
    year = request.args.get('year', '2026')
    table_name = get_all_table(year)

    # 缓存检查：相同参数 120 秒内直接返回缓存
    cache_key = all_cache_key('all_stats', hours, band_filter, callsign_filter, year)
    cached = ALL_CACHE.get(cache_key)
    if cached is not None:
        cached = dict(cached)  # 浅拷贝避免修改缓存中的原始对象
        cached['query_time_ms'] = int((time.time() - start_time) * 1000)
        cached['_cached'] = True
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    # ── 2025 年数据走预聚合汇总表（毫秒级），避免 psk_hdf5 55 亿行全扫 ──
    if use_summary(year, callsign_filter):
        return _get_all_stats_from_summary(hours, band_filter, callsign_filter, year, start_time)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        stats = {}

        # 优化策略：有时间范围限制时，先过滤再统计
        # 构建基础条件（hours=0 表示全量查询，最大支持720小时=30天）
        base_conditions, base_params = build_time_condition(table_name, hours)
        
        # 添加波段过滤 (unified via band_utils)
        if band_filter:
            base_conditions, base_params = band_utils.build_band_conditions(
                band_filter, base_conditions, base_params)
        
        # 添加呼号过滤
        if callsign_filter:
            base_conditions.append("(sender_callsign LIKE %s OR receiver_callsign LIKE %s)")
            like_pattern = f"{callsign_filter.upper()}%"  # 优化：使用前缀匹配而非模糊匹配
            base_params.extend([like_pattern, like_pattern])
        
        where_clause = " AND ".join(base_conditions) if base_conditions else "1=1"
        
        # 1. 快速获取总数和时间范围（使用覆盖索引）
        count_sql = f"""
            SELECT 
                COUNT(*) as total,
                MIN(qso_time) as first_record,
                MAX(qso_time) as last_record
            FROM {table_name}
            WHERE {where_clause}
        """
        cursor.execute(count_sql, base_params)
        row = cursor.fetchone()
        stats['total_records'] = row['total']
        stats['first_record'] = row['first_record'].isoformat() if row['first_record'] else None
        stats['last_record'] = row['last_record'].isoformat() if row['last_record'] else None
        
        # 2. 估算唯一呼号数（使用采样，避免 COUNT(DISTINCT) 全表扫描）
        # 对于大数据集，使用确定性的最近样本估算更高效
        if row['total'] > 100000:
            # 采样估算：取最近 100K 条记录的 DISTINCT，确定性排序
            sample_sql = f"""
                SELECT COUNT(DISTINCT sender_callsign) as unique_senders,
                       COUNT(DISTINCT receiver_callsign) as unique_receivers
                FROM (
                    SELECT sender_callsign, receiver_callsign
                    FROM {table_name}
                    WHERE {where_clause}
                    ORDER BY qso_time DESC
                    LIMIT 30000
                ) as sample
            """
            cursor.execute(sample_sql, base_params)
            sample_row = cursor.fetchone()
            # 保守线性外推：假设呼号增长率随数据量递减，使用 log 修正
            import math
            ratio = row['total'] / 100000
            log_factor = math.log(1 + ratio) / math.log(2)  # log2-style dampening
            stats['unique_senders'] = int(sample_row['unique_senders'] * log_factor)
            stats['unique_receivers'] = int(sample_row['unique_receivers'] * log_factor)
            stats['_unique_estimated'] = True  # flag that this is an estimate
        else:
            # 数据量小时直接计算
            distinct_sql = f"""
                SELECT 
                    COUNT(DISTINCT sender_callsign) as unique_senders,
                    COUNT(DISTINCT receiver_callsign) as unique_receivers
                FROM {table_name}
                WHERE {where_clause}
            """
            cursor.execute(distinct_sql, base_params)
            distinct_row = cursor.fetchone()
            stats['unique_senders'] = distinct_row['unique_senders']
            stats['unique_receivers'] = distinct_row['unique_receivers']
        
        # 3. 按模式统计（new_planner_agg_stage=1 避免 per-tablet 行）
        mode_sql = f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                mode, COUNT(*) as count
            FROM {table_name}
            WHERE {where_clause} AND mode IS NOT NULL
            GROUP BY mode
            ORDER BY count DESC
            LIMIT 10
        """
        cursor.execute(mode_sql, base_params)
        stats['by_mode'] = cursor.fetchall()
        
        # 4. 按波段统计（all_records 用 SUM_BAND_SQL 避免 GROUP BY bug）
        band_sql = f"""
            SELECT {band_utils.SUM_BAND_SQL}
            FROM {table_name}
            WHERE {where_clause} AND frequency IS NOT NULL
        """
        cursor.execute(band_sql, base_params)
        stats['by_band'] = band_utils.parse_sum_band_row(cursor.fetchone())
        
        # 5. 最近一小时时间线
        if table_name == 'psk_hdf5':
            # 2025 历史数据：取最后一天的小时分布
            timeline_sql = f"""
                SELECT {SR_HINT}
                    DATE_FORMAT(qso_time, '%H:%i') as minute,
                    COUNT(*) as count
                FROM {table_name}
                WHERE qso_time >= '2025-04-22 00:00:00'
                GROUP BY minute
                ORDER BY minute DESC
                LIMIT 30
            """
            cursor.execute(timeline_sql, [])
        else:
            timeline_sql = f"""
                SELECT {SR_HINT}
                    DATE_FORMAT(qso_time, '%H:%i') as minute,
                    COUNT(*) as count
                FROM {table_name}
                WHERE qso_time >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
                GROUP BY minute
                ORDER BY minute DESC
                LIMIT 30
            """
            cursor.execute(timeline_sql, [])
        stats['hourly_timeline'] = cursor.fetchall()
        
        # 添加查询耗时
        stats['query_time_ms'] = int((time.time() - start_time) * 1000)

        # 缓存结果
        ALL_CACHE.set(cache_key, dict(stats))

        resp = jsonify(stats)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp
        
    finally:
        cursor.close()
        conn.close()


def _get_all_band_from_summary(hours, band_filter, year, start_time):
    """从汇总表获取波段分析（2025 年）"""
    import time
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        time_clause = summary_time_filter(hours, year)
        where = f"1=1{' AND ' + time_clause if time_clause else ''}"

        # 按波段统计
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                band, SUM(spot_count) as count
            FROM {get_summary_table(year)} WHERE {where}
            GROUP BY band ORDER BY count DESC
        """)
        bands = [{"band": r['band'], "count": r['count']} for r in cursor.fetchall()]

        # 按小时统计
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                hour, band, SUM(spot_count) as count
            FROM {get_summary_table(year)} WHERE {where}
            GROUP BY hour, band ORDER BY hour, count DESC
        """)
        timeline = [{"hour": r['hour'], "band": r['band'], "count": r['count']}
                     for r in cursor.fetchall()]

        result = {"bands": bands, "timeline": timeline,
                  "query_time_ms": int((time.time() - start_time) * 1000), "_summary": True}
        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp
    finally:
        cursor.close()
        conn.close()


def _get_all_continent_from_summary(hours, band_filter, year, start_time):
    """从汇总表获取大洲分析（2025 年）"""
    import time
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        time_clause = summary_time_filter(hours, year)
        band_clause = f" AND band = %s" if band_filter and band_filter in band_utils.BAND_FREQ_MAP else ""
        band_params = [band_filter] if band_clause else []

        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                sender_country as country, SUM(spot_count) as count
            FROM {get_summary_table(year)}
            WHERE 1=1 {' AND ' + time_clause if time_clause else ''} {band_clause}
            GROUP BY sender_country
            ORDER BY count DESC
        """, band_params)
        all_countries = cursor.fetchall()
        top_countries = all_countries[:20]

        continent_data = {}
        for c in all_countries:
            norm_name = normalize_dxcc_name(c['country'])
            continent = get_continent_full(get_continent(norm_name))
            continent_data[continent] = continent_data.get(continent, 0) + c['count']

        continents = sorted([{"continent": k, "count": v} for k, v in continent_data.items()],
                           key=lambda x: x['count'], reverse=True)

        result = {"continents": continents, "top_countries": top_countries,
                  "query_time_ms": int((time.time() - start_time) * 1000), "_summary": True}
        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp
    finally:
        cursor.close()
        conn.close()


def _get_all_timeline_from_summary(hours, granularity, band_filter, year, start_time):
    """从汇总表获取时间线（2025 年）"""
    import time
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        time_clause = summary_time_filter(hours, year)
        where = f"1=1{' AND ' + time_clause if time_clause else ''}"

        if granularity == 'minute':
            # 汇总表只有 hour 粒度，降级为 hour
            cursor.execute(f"""
                SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                    CONCAT(day, ' ', LPAD(hour, 2, '0'), ':00') as time,
                       SUM(spot_count) as count
                FROM {get_summary_table(year)} WHERE {where}
                GROUP BY day, hour ORDER BY day, hour LIMIT 120
            """)
        elif granularity == 'day':
            cursor.execute(f"""
                SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                    CAST(day AS CHAR) as time, SUM(spot_count) as count
                FROM {get_summary_table(year)} WHERE {where}
                GROUP BY day ORDER BY day LIMIT 365
            """)
        else:
            cursor.execute(f"""
                SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                    CONCAT(day, ' ', LPAD(hour, 2, '0'), ':00') as time,
                       SUM(spot_count) as count
                FROM {get_summary_table(year)} WHERE {where}
                GROUP BY day, hour ORDER BY day, hour LIMIT 720
            """)

        timeline = cursor.fetchall()
        result = {"timeline": timeline,
                  "query_time_ms": int((time.time() - start_time) * 1000), "_summary": True}
        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/all/band_analysis')
def get_all_band_analysis():
    """
    波段分析（优化版）
    
    返回: 各波段记录数、唯一电台数、平均SNR
    
    参数:
        hours: 时间范围（小时，最大48）
        band: 波段过滤（可选）
        callsign: 呼号搜索（可选，支持前缀匹配）
        year: 年份（默认 2026，2025 查询 psk_hdf5）
    """
    import time
    start_time = time.time()
    
    hours = int(request.args.get('hours', 24))
    band_filter = request.args.get('band', '')
    callsign_filter = request.args.get('callsign', '')
    year = request.args.get('year', '2026')
    table_name = get_all_table(year)

    # 缓存检查
    cache_key = all_cache_key('all_band', hours, band_filter, callsign_filter, year)
    cached = ALL_CACHE.get(cache_key)
    if cached is not None:
        cached = dict(cached)
        cached['query_time_ms'] = int((time.time() - start_time) * 1000)
        cached['_cached'] = True
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    # ── 2025 年数据走预聚合汇总表 ──
    if use_summary(year, callsign_filter):
        return _get_all_band_from_summary(hours, band_filter, year, start_time)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        result = {"bands": [], "timeline": [], "query_time_ms": 0}

        # 构建过滤条件
        conditions, params = build_time_condition(table_name, hours)
        conditions.append("frequency IS NOT NULL")

        # 波段过滤 (unified via band_utils)
        if band_filter:
            conditions, params = band_utils.build_band_conditions(
                band_filter, conditions, params)

        # 呼号过滤（优化：使用前缀匹配而非模糊匹配）
        if callsign_filter:
            conditions.append("(sender_callsign LIKE %s OR receiver_callsign LIKE %s)")
            like_pattern = f"{callsign_filter.upper()}%"
            params.extend([like_pattern, like_pattern])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 波段统计 - 使用 SUM_BAND_SQL 避免 StarRocks GROUP BY bug
        sql = f"""
            SELECT {band_utils.SUM_BAND_SQL}
            FROM {table_name}
            WHERE {where_clause}
        """
        cursor.execute(sql, params)
        result['bands'] = band_utils.parse_sum_band_row(cursor.fetchone())
        
        # 时间线（SR_HINT 避免 per-tablet 行）
        timeline_where = ' AND '.join(conditions) if conditions else '1=1'
        timeline_sql = f"""
            SELECT {SR_HINT}
                DATE_FORMAT(qso_time, '%H:00') as hour,
                COUNT(*) as count
            FROM {table_name}
            WHERE {timeline_where}
            GROUP BY hour
            ORDER BY hour
            LIMIT 50
        """
        cursor.execute(timeline_sql, params)
        result['timeline'] = cursor.fetchall()
        
        result['query_time_ms'] = int((time.time() - start_time) * 1000)

        ALL_CACHE.set(cache_key, dict(result))

        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    finally:
        cursor.close()
        conn.close()


@app.route('/api/all/continent_analysis')
def get_all_continent_analysis():
    """
    大洲分布分析（优化版）
    
    直接在数据库端聚合，避免 Python 端处理大量数据
    
    参数:
        hours: 时间范围（小时，最大48）
        band: 波段过滤（可选）
        callsign: 呼号搜索（可选）
        year: 年份（默认 2026，2025 查询 psk_hdf5）
    """
    import time
    start_time = time.time()
    
    hours = int(request.args.get('hours', 24))
    band_filter = request.args.get('band', '')
    callsign_filter = request.args.get('callsign', '')
    year = request.args.get('year', '2026')
    table_name = get_all_table(year)

    # 缓存检查
    cache_key = all_cache_key('all_continent', hours, band_filter, callsign_filter, year)
    cached = ALL_CACHE.get(cache_key)
    if cached is not None:
        cached = dict(cached)
        cached['query_time_ms'] = int((time.time() - start_time) * 1000)
        cached['_cached'] = True
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    # ── 2025 年数据走预聚合汇总表 ──
    if use_summary(year, callsign_filter):
        return _get_all_continent_from_summary(hours, band_filter, year, start_time)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        result = {"continents": [], "top_countries": [], "query_time_ms": 0}

        conditions, params = build_time_condition(table_name, hours)

        # 波段过滤 (unified via band_utils)
        if band_filter:
            conditions, params = band_utils.build_band_conditions(
                band_filter, conditions, params)

        # 呼号过滤（前缀匹配）
        if callsign_filter:
            conditions.append("(sender_callsign LIKE %s OR receiver_callsign LIKE %s)")
            like_pattern = f"{callsign_filter.upper()}%"
            params.extend([like_pattern, like_pattern])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 按国家聚合（new_planner_agg_stage=1 避免 per-tablet 行）
        country_sql = f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                COALESCE(sender_country, 'Unknown') as country,
                COUNT(*) as count
            FROM {table_name}
            WHERE {where_clause}
            GROUP BY country
            ORDER BY count DESC
        """
        cursor.execute(country_sql, params)
        all_countries = cursor.fetchall()

        # Top 20 for display
        result['top_countries'] = all_countries[:20]

        # 基于所有国家计算大洲分布（使用 dxcc_lookup 模块）
        # 不再受 Top 20 截断影响
        continent_data = {}
        for c in all_countries:
            country = c['country']
            count = c['count']
            norm_name = normalize_dxcc_name(country)
            continent_code = get_continent(norm_name)
            continent = get_continent_full(continent_code)
            if continent not in continent_data:
                continent_data[continent] = 0
            continent_data[continent] += count

        result['continents'] = sorted(
            [{"continent": k, "count": v} for k, v in continent_data.items()],
            key=lambda x: x['count'],
            reverse=True
        )

        result['query_time_ms'] = int((time.time() - start_time) * 1000)

        ALL_CACHE.set(cache_key, dict(result))

        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    finally:
        cursor.close()
        conn.close()


@app.route('/api/space_weather')
def get_space_weather():
    """空间天气数据（缓存 5 分钟，每日更新一次）"""
    year = request.args.get('year', '2026')
    start = request.args.get('start', '')
    end = request.args.get('end', '')

    cache_key = f"space_weather:y{year}:s{start}:e{end}"
    cached = ALL_CACHE.get(cache_key)
    if cached is not None:
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        conditions = ["daily_sunspot_avg IS NOT NULL", "daily_kp_avg IS NOT NULL"]
        params = []

        if start:
            conditions.append("summary_date >= %s")
            params.append(start)
        if end:
            conditions.append("summary_date <= %s")
            params.append(end)
        elif year:
            conditions.append("YEAR(summary_date) = %s")
            params.append(int(year))

        where = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT summary_date as date, daily_sunspot_avg as sunspot,
                   daily_kp_avg as kp, daily_f107_avg as f107
            FROM space_weather_daily
            WHERE {where}
            ORDER BY summary_date
        """, params)
        rows = cursor.fetchall()

        for r in rows:
            r['date'] = r['date'].isoformat() if r['date'] else None

        result = {"data": rows, "count": len(rows)}
        ALL_CACHE.set(cache_key, result, ttl=300)  # 空间天气每日一变，缓存 5 分钟

        resp = jsonify(result)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/all/timeline')
def get_all_timeline():
    """
    时间线分析（优化版）
    
    返回: 按小时/分钟的记录数变化
    
    参数:
        hours: 时间范围（小时，最大48）
        granularity: 粒度（hour 或 minute）
        band: 波段过滤（可选）
        callsign: 呼号搜索（可选）
    """
    import time
    start_time = time.time()
    
    hours = int(request.args.get('hours', 24))
    year = request.args.get('year', '2026')
    table_name = get_all_table(year)
    granularity = request.args.get('granularity', 'auto')
    band_filter = request.args.get('band', '')
    callsign_filter = request.args.get('callsign', '')

    # 缓存检查
    cache_key = all_cache_key('all_timeline', hours, band_filter, callsign_filter, year) + f":g{granularity}"
    cached = ALL_CACHE.get(cache_key)
    if cached is not None:
        cached = dict(cached)
        cached['query_time_ms'] = int((time.time() - start_time) * 1000)
        cached['_cached'] = True
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp

    # ── 2025 年数据走预聚合汇总表 ──
    if use_summary(year, callsign_filter):
        return _get_all_timeline_from_summary(hours, granularity, band_filter, year, start_time)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        # 构建过滤条件（hours=0 表示全量查询，最大支持720小时=30天）
        conditions, params = build_time_condition(table_name, hours)
        
        # 波段过滤 (unified via band_utils)
        if band_filter:
            conditions, params = band_utils.build_band_conditions(
                band_filter, conditions, params)
        
        # 呼号过滤（前缀匹配）
        if callsign_filter:
            conditions.append("(sender_callsign LIKE %s OR receiver_callsign LIKE %s)")
            like_pattern = f"{callsign_filter.upper()}%"
            params.extend([like_pattern, like_pattern])
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # 确定粒度和返回数量（SR_HINT 避免 per-tablet 行）
        if granularity == 'minute':
            if table_name == 'psk_hdf5':
                min_conds = list(conditions)
                min_conds.append("qso_time >= '2025-04-22 00:00:00'")
                min_where = " AND ".join(min_conds)
            else:
                min_conds = [c for c in conditions if "qso_time >= DATE_SUB" not in c]
                min_conds.append("qso_time >= DATE_SUB(NOW(), INTERVAL 2 HOUR)")
                min_where = " AND ".join(min_conds)
            sql = f"""
                SELECT {SR_HINT}
                    DATE_FORMAT(qso_time, '%Y-%m-%d %H:%i') as time,
                    COUNT(*) as count
                FROM {table_name}
                WHERE {min_where}
                GROUP BY time
                ORDER BY time
                LIMIT 120
            """
            cursor.execute(sql, params)
            timeline = cursor.fetchall()
        elif granularity == 'day':
            g_limit = 365 if hours == 0 else 60
            sql = f"""
                SELECT {SR_HINT}
                    DATE_FORMAT(qso_time, '%Y-%m-%d') as time,
                    COUNT(*) as count
                FROM {table_name}
                WHERE {where_clause}
                GROUP BY time
                ORDER BY time
                LIMIT {g_limit}
            """
            cursor.execute(sql, params)
            timeline = cursor.fetchall()
        else:
            g_limit = 720 if hours == 0 or hours > 168 else 200
            sql = f"""
                SELECT {SR_HINT}
                    DATE_FORMAT(qso_time, '%Y-%m-%d %H:00') as time,
                    COUNT(*) as count
                FROM {table_name}
                WHERE {where_clause}
                GROUP BY time
                ORDER BY time
                LIMIT {g_limit}
            """
            cursor.execute(sql, params)
            timeline = cursor.fetchall()
        
        result_data = {
            "timeline": timeline,
            "query_time_ms": int((time.time() - start_time) * 1000)
        }
        ALL_CACHE.set(cache_key, dict(result_data))

        resp = jsonify(result_data)
        resp.headers['X-Cache'] = 'MISS'
        resp.headers['Cache-Control'] = 'public, max-age=120'
        return resp
        
    finally:
        cursor.close()
        conn.close()


# ==================== 深度分析看板 API ====================

# ── 网格坐标转换工具 ──
import math

def grid_to_latlon(grid):
    """Maidenhead grid locator → (lat, lon) 中心点"""
    if not grid or len(grid) < 4:
        return None, None
    grid = grid.upper()[:6]
    try:
        lon = (ord(grid[0]) - ord('A')) * 20 - 180
        lat = (ord(grid[1]) - ord('A')) * 10 - 90
        lon += int(grid[2]) * 2
        lat += int(grid[3]) * 1
        if len(grid) >= 6:
            lon += (ord(grid[4]) - ord('A')) * (2/24)
            lat += (ord(grid[5]) - ord('A')) * (1/24)
        lon += 1.0 / 24  # sub-square center
        lat += 0.5 / 24
        return lat, lon
    except (ValueError, IndexError):
        return None, None

def compute_bearing(lat1, lon1, lat2, lon2):
    """计算大圆方位角 (0-360°)"""
    dlon = math.radians(lon2 - lon1)
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360

def compute_distance_km(lat1, lon1, lat2, lon2):
    """Haversine 距离 (km)"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.route('/advanced')
def advanced_page():
    """深度分析看板页面"""
    return render_template('advanced.html', active_page='advanced')


@app.route('/api/advanced/stats')
def advanced_stats():
    """快速概览统计"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    role = request.args.get('role', 'tx')
    call = request.args.get('callsign', CALLSIGN).upper()

    if int(year) == 2025:
        table = get_summary_table(year)
        band_clause = f" AND band = %s" if band_filter else ""
        band_params = [band_filter] if band_clause else []
        callsign_clause = f" AND sender_callsign = %s" if role == 'tx' else f" AND receiver_callsign = %s"
        table = 'psk_hdf5'
        band_clause = band_clause.replace('band', f'({band_utils.CASE_BAND_SQL})')
    else:
        table = 'all_records'
        band_clause, band_params = ("", []) if not band_filter else band_utils.build_band_conditions(
            band_filter, [], [])
        callsign_clause = f" AND sender_callsign = %s" if role == 'tx' else f" AND receiver_callsign = %s"
    params = band_params + [call]

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                COUNT(*) as total,
                COUNT(DISTINCT CASE WHEN {role == 'tx'} THEN receiver_callsign ELSE sender_callsign END) as unique_stations
            FROM {table}
            WHERE 1=1 {callsign_clause} {band_clause}
        """, params)
        row = cursor.fetchone()
        return jsonify({"total": row['total'], "countries": row['unique_stations']})
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/radiation')
def advanced_radiation():
    """2D 辐射图 — 呼号 发射/接收方位角 (5°分箱)，从网格坐标实时计算"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    role = request.args.get('role', 'tx')
    call = request.args.get('callsign', CALLSIGN).upper()
    table, partitions = get_raw_table_and_partitions(year)

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
        ref_loc_col, target_loc_col = "sender_locator", "receiver_locator"
    else:
        callsign_clause = "AND receiver_callsign = %s"
        ref_loc_col, target_loc_col = "receiver_locator", "sender_locator"

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    params = [call] + ([band_filter] if band_filter else [])

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        results = {}
        parts = partitions or [None]  # 2026: single pass without PARTITION()
        for part in parts:
            from_clause = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr,
                       {target_loc_col} as station_id
                FROM {from_clause}
                WHERE {ref_loc_col} IS NOT NULL AND {target_loc_col} IS NOT NULL
                  AND snr IS NOT NULL AND {ref_loc_col} != ''
                  {callsign_clause} {band_clause}
                LIMIT 25000
            """, params)
            for row in cursor.fetchall():
                ref_lat, ref_lon = grid_to_latlon(row['ref_loc'])
                target_lat, target_lon = grid_to_latlon(row['target_loc'])
                if ref_lat is None or target_lat is None: continue
                bearing = compute_bearing(ref_lat, ref_lon, target_lat, target_lon)
                az_bin = int(bearing // 5) * 5
                if az_bin not in results:
                    results[az_bin] = {'azimuth': az_bin, 'count': 0, 'snr_sum': 0, 'snr_max': -999, 'stations': set()}
                results[az_bin]['count'] += 1
                results[az_bin]['snr_sum'] += row['snr']
                results[az_bin]['snr_max'] = max(results[az_bin]['snr_max'], row['snr'])
                if row['station_id']: results[az_bin]['stations'].add(row['station_id'])

        output = []
        for az in sorted(results.keys()):
            r = results[az]
            output.append({'azimuth': az, 'count': r['count'], 'unique_stations': len(r['stations']),
                          'avg_snr': round(r['snr_sum']/r['count'], 1), 'max_snr': r['snr_max']})
        return jsonify(output)
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/distance')
def advanced_distance():
    """距离分布 vs SNR — BG1SB 发射/接收 距离分布 (500km分箱)"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
        ref_loc_col = "sender_locator"
        target_loc_col = "receiver_locator"
    else:
        callsign_clause = "AND receiver_callsign = %s"
        ref_loc_col = "receiver_locator"
        target_loc_col = "sender_locator"

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    call = request.args.get('callsign', CALLSIGN).upper()
    params = [call] + ([band_filter] if band_filter else [])

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        results = {}
        parts = partitions or [None]
        for part in parts:
            from_clause = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr
                FROM {from_clause}
                WHERE {ref_loc_col} IS NOT NULL AND {target_loc_col} IS NOT NULL
                  AND snr IS NOT NULL AND {ref_loc_col} != ''
                  {callsign_clause} {band_clause}
                LIMIT 25000
            """, params)
            for row in cursor.fetchall():
                ref_lat, ref_lon = grid_to_latlon(row['ref_loc'])
                target_lat, target_lon = grid_to_latlon(row['target_loc'])
                if ref_lat is None or target_lat is None:
                    continue
                dist = compute_distance_km(ref_lat, ref_lon, target_lat, target_lon)
                if dist <= 0 or dist > 20000:
                    continue
                range_bin = int(dist // 500) * 500
                if range_bin not in results:
                    results[range_bin] = {'range_km': range_bin, 'count': 0, 'snr_sum': 0, 'snr_max': -999}
                results[range_bin]['count'] += 1
                results[range_bin]['snr_sum'] += row['snr']
                results[range_bin]['snr_max'] = max(results[range_bin]['snr_max'], row['snr'])

        output = []
        for km in sorted(results.keys()):
            r = results[km]
            output.append({
                'range_km': km,
                'count': r['count'],
                'avg_snr': round(r['snr_sum'] / r['count'], 1),
                'max_snr': r['snr_max']
            })
        return jsonify(output)
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/heatmap')
def advanced_heatmap():
    """传播热力图 — 月份 × 小时 × 报文密度 (BG1SB 视角)"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    role = request.args.get('role', 'tx')

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
    else:
        callsign_clause = "AND receiver_callsign = %s"
    call = request.args.get('callsign', CALLSIGN).upper()
    params = [call]

    if int(year) == 2025:
        table = 'psk_hdf5'
        if band_filter:
            callsign_clause += f" AND ({band_utils.CASE_BAND_SQL}) = %s"
            params.append(band_filter)
    else:
        table = 'all_records'
        if band_filter:
            callsign_clause, params = band_utils.build_band_conditions(
                band_filter, [callsign_clause], params)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                MONTH(qso_time) as month,
                HOUR(qso_time) as hour,
                COUNT(*) as count
            FROM {table}
            WHERE 1=1 {callsign_clause}
            GROUP BY month, hour
            ORDER BY month, hour
        """, params)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/band_snr')
def advanced_band_snr():
    """各波段 SNR 分布 + 报文数 (BG1SB 视角)"""
    year = request.args.get('year', '2025')
    role = request.args.get('role', 'tx')

    table = 'psk_hdf5' if int(year) == 2025 else 'all_records'
    callsign_clause = "AND sender_callsign = %s" if role == 'tx' else "AND receiver_callsign = %s"
    call = request.args.get('callsign', CALLSIGN).upper()
    params = [call]

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                {band_utils.CASE_BAND_SQL} as band,
                COUNT(*) as spot_count,
                AVG(snr) as avg_snr
            FROM {table}
            WHERE snr IS NOT NULL AND frequency IS NOT NULL {callsign_clause}
            GROUP BY band ORDER BY spot_count DESC
        """, params)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/hourly_efficiency')
def advanced_hourly_efficiency():
    """每小时通联效率 (BG1SB 视角)"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    role = request.args.get('role', 'tx')

    table = 'psk_hdf5' if int(year) == 2025 else 'all_records'
    callsign_clause = "AND sender_callsign = %s" if role == 'tx' else "AND receiver_callsign = %s"
    call = request.args.get('callsign', CALLSIGN).upper()
    params = [call]
    if band_filter:
        callsign_clause += f" AND ({band_utils.CASE_BAND_SQL}) = %s"
        params.append(band_filter)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                HOUR(qso_time) as hour,
                COUNT(*) / COUNT(DISTINCT DATE(qso_time)) as avg_spots,
                AVG(snr) as avg_snr
            FROM {table}
            WHERE snr IS NOT NULL {callsign_clause}
            GROUP BY hour ORDER BY hour
        """, params)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/grid_compare')
def advanced_grid_compare():
    """同网格电台效率对比 — BG1SB vs ON80 邻居，同一接收方同一时段 SNR 差异"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    call = request.args.get('callsign', CALLSIGN).upper()
    table, partitions = get_raw_table_and_partitions(year)
    from_c = table  # grid lookup 用全表(布隆过滤器加速, 不需分区裁剪)

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    band_params = [band_filter] if band_filter else []

    # 获取该呼号的网格前缀 (前4位，如 ON80)
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"""
            SELECT DISTINCT sender_locator FROM {from_c}
            WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1
        """, (call,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": f"未找到 {call} 的网格数据"}), 404
        grid_prefix = row['sender_locator'][:4]  # e.g. 'ON80'

        # 找到同一网格内的其他电台（至少 1000 spots 够统计意义）
        cursor.execute(f"""
            SELECT sender_callsign, COUNT(*) c
            FROM {from_c}
            WHERE sender_locator LIKE %s AND sender_callsign != %s
              {band_clause}
            GROUP BY sender_callsign HAVING c > 1000
            ORDER BY c DESC LIMIT 20
        """, [grid_prefix + '%', call] + band_params)
        peers = [r['sender_callsign'] for r in cursor.fetchall()]
        if not peers:
            return jsonify({"error": f"网格 {grid_prefix} 内无足够数据对比"}), 404

        # 对比查询: 同一接收方 + 同一波段 + 5分钟内 → BG1SB vs peer SNR
        results = {}
        placeholders = ','.join(['%s'] * len(peers))
        sql = f"""
            SELECT /*+ SET_VAR(new_planner_agg_stage=1) */
                {band_utils.CASE_BAND_SQL} as band,
                AVG(CASE WHEN sender_callsign = %s THEN snr END) as my_snr,
                AVG(CASE WHEN sender_callsign != %s THEN snr END) as peer_snr,
                COUNT(DISTINCT receiver_callsign) as common_rx,
                COUNT(*) as spots
            FROM {from_c}
            WHERE sender_callsign IN (%s, {placeholders})
              AND snr IS NOT NULL AND frequency IS NOT NULL
              AND receiver_callsign IS NOT NULL
              {band_clause}
            GROUP BY band
            HAVING COUNT(DISTINCT receiver_callsign) >= 3
            ORDER BY spots DESC
        """
        all_params = [call, call, call] + peers + (band_params if band_filter else [])
        cursor.execute(sql, all_params)

        for r in cursor.fetchall():
            my = r['my_snr']; peer = r['peer_snr']
            if my is None or peer is None: continue  # 无数据跳过
            diff = round(my - peer, 1)
            results[r['band']] = {
                'band': r['band'],
                'my_snr': round(r['my_snr'] or -99, 1),
                'peer_snr': round(r['peer_snr'] or -99, 1),
                'diff': diff,
                'common_rx': r['common_rx'],
                'spots': r['spots'],
                'verdict': '优' if diff > 2 else ('良' if diff > -2 else ('差' if diff < -5 else '持平'))
            }

        return jsonify({
            'grid': grid_prefix,
            'callsign': call,
            'peers': peers[:10],
            'peer_count': len(peers),
            'bands': sorted(results.values(), key=lambda x: x['spots'], reverse=True)
        })
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/grid_radiation')
def advanced_grid_radiation():
    """同网格辐射方向对比 — BG1SB vs ON80 邻居的方位角 SNR 分布"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    call = request.args.get('callsign', CALLSIGN).upper()

    call = request.args.get('callsign', CALLSIGN).upper()
    table, partitions = get_raw_table_and_partitions(year)
    from_c = table  # grid lookup 用全表(布隆过滤器加速, 不需分区裁剪)

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    band_params = [band_filter] if band_filter else []

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT DISTINCT sender_locator FROM {from_c} WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1", (call,))
        row = cursor.fetchone()
        if not row: return jsonify({"error": f"未找到 {call}"}), 404
        grid_prefix = row['sender_locator'][:4]

        cursor.execute(f"SELECT sender_locator FROM {from_c} WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1", (call,))
        my_grid = cursor.fetchone()['sender_locator']

        my_bins = {}
        peer_bins = {}

        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            # BG1SB data
            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr
                FROM {from_p}
                WHERE sender_callsign = %s AND sender_locator != '' AND receiver_locator != ''
                  AND snr IS NOT NULL {band_clause} LIMIT 25000
            """, [call] + band_params)
            for r in cursor.fetchall():
                my_lat, my_lon = grid_to_latlon(r['sender_locator'])
                rx_lat, rx_lon = grid_to_latlon(r['receiver_locator'])
                if not my_lat or not rx_lat: continue
                az = int(compute_bearing(my_lat, my_lon, rx_lat, rx_lon)//5)*5
                if az not in my_bins: my_bins[az] = {'snr_sum':0,'count':0,'stations':set()}
                my_bins[az]['snr_sum'] += r['snr']
                my_bins[az]['count'] += 1
                my_bins[az]['stations'].add(r['receiver_locator'])

            # Peer data (same grid, NOT the callsign)
            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr
                FROM {from_p}
                WHERE sender_locator LIKE %s AND sender_callsign != %s
                  AND sender_locator != '' AND receiver_locator != ''
                  AND snr IS NOT NULL {band_clause} LIMIT 25000
            """, [grid_prefix+'%', call] + band_params)
            for r in cursor.fetchall():
                peer_lat, peer_lon = grid_to_latlon(r['sender_locator'])
                rx_lat, rx_lon = grid_to_latlon(r['receiver_locator'])
                if not peer_lat or not rx_lat: continue
                az = int(compute_bearing(peer_lat, peer_lon, rx_lat, rx_lon)//5)*5
                if az not in peer_bins: peer_bins[az] = {'snr_sum':0,'count':0,'stations':set()}
                peer_bins[az]['snr_sum'] += r['snr']
                peer_bins[az]['count'] += 1
                peer_bins[az]['stations'].add(r['receiver_locator'])

        output = []
        for az in range(0,360,5):
            m = my_bins.get(az, {'snr_sum':0,'count':0,'stations':set()})
            p = peer_bins.get(az, {'snr_sum':0,'count':0,'stations':set()})
            output.append({
                'azimuth': az,
                'my_snr': round(m['snr_sum']/m['count'],1) if m['count']>0 else None,
                'my_count': m['count'],
                'my_stations': len(m['stations']),
                'peer_snr': round(p['snr_sum']/p['count'],1) if p['count']>0 else None,
                'peer_count': p['count'],
                'peer_stations': len(p['stations']),
            })

        return jsonify({'grid': grid_prefix, 'callsign': call, 'radiation': output})
    finally:
        cursor.close()
        conn.close()


@app.route('/api/advanced/station_audit')
def advanced_station_audit():
    """电台综合审计 — BG1SB vs ON80 邻居的多维度差异分析"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()
    table, partitions = get_raw_table_and_partitions(year)
    from_c = table  # grid lookup 用全表(布隆过滤器, 不需要分区)

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT DISTINCT sender_locator FROM {from_c} WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1", (call,))
        row = cursor.fetchone()
        if not row: return jsonify({"error": f"未找到 {call}"}), 404
        grid_prefix = row['sender_locator'][:4]
        grid_cond = f"sender_locator LIKE '{grid_prefix}%'"

        audit = {'callsign': call, 'grid': grid_prefix}

        # ── 1. TX/RX 活跃度对比 ──
        cursor.execute(f"""
            SELECT 'tx_peers' as metric, COUNT(DISTINCT sender_callsign) as val FROM {from_c} WHERE {grid_cond}
            UNION ALL
            SELECT 'rx_peers', COUNT(DISTINCT receiver_callsign) FROM {from_c} WHERE receiver_locator LIKE '{grid_prefix}%'
            UNION ALL
            SELECT 'my_tx_spots', COUNT(*) FROM {from_c} WHERE sender_callsign = %s
            UNION ALL
            SELECT 'my_rx_spots', COUNT(*) FROM {from_c} WHERE receiver_callsign = %s
            UNION ALL
            SELECT 'my_tx_unique_rx', COUNT(DISTINCT receiver_callsign) FROM {from_c} WHERE sender_callsign = %s
            UNION ALL
            SELECT 'my_rx_unique_tx', COUNT(DISTINCT sender_callsign) FROM {from_c} WHERE receiver_callsign = %s
        """, (call,)*4)
        txrx = {r['metric']: int(r['val']) for r in cursor.fetchall()}
        audit['txrx'] = {
            'grid_tx_stations': txrx.get('tx_peers', 0),
            'grid_rx_stations': txrx.get('rx_peers', 0),
            'my_tx_spots': txrx.get('my_tx_spots', 0),
            'my_rx_spots': txrx.get('my_rx_spots', 0),
            'my_tx_unique_rx': txrx.get('my_tx_unique_rx', 0),
            'my_rx_unique_tx': txrx.get('my_rx_unique_tx', 0),
        }
        a = audit['txrx']
        a['tx_rx_ratio'] = round(a['my_tx_unique_rx'] / max(a['my_rx_unique_tx'], 1), 1)
        a['activity_pct'] = round(a['my_tx_spots'] / max(txrx.get('tx_peers', 1) * 10000, 1) * 100, 0)

        # ── 2. 时段覆盖对比 (工作时间分布) ──
        cursor.execute(f"""
            SELECT HOUR(qso_time) as h, COUNT(*) c FROM {from_c}
            WHERE sender_callsign = %s GROUP BY h ORDER BY h
        """, (call,))
        my_hours = {r['h']: r['c'] for r in cursor.fetchall()}
        cursor.execute(f"""
            SELECT HOUR(qso_time) as h, COUNT(*) c FROM {from_c}
            WHERE {grid_cond} AND sender_callsign != %s GROUP BY h ORDER BY h
        """, (call,))
        peer_hours = {r['h']: r['c'] for r in cursor.fetchall()}
        audit['hourly'] = [{
            'hour': h,
            'my_spots': my_hours.get(h, 0),
            'peer_spots': peer_hours.get(h, 0),
            'peer_avg': round(peer_hours.get(h, 0) / max(audit['txrx']['grid_tx_stations'], 1), 0)
        } for h in range(24)]

        # ── 3. 距离效率: BG1SB vs peer SNR per 1000km ──
        my_dist = {}
        peer_dist = {}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr FROM {from_p}
                WHERE sender_callsign = %s AND sender_locator != '' AND receiver_locator != '' AND snr IS NOT NULL LIMIT 50000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['sender_locator']); rl = grid_to_latlon(r['receiver_locator'])
                if not sl[0] or not rl[0]: continue
                d = int(compute_distance_km(sl[0], sl[1], rl[0], rl[1]) // 1000) * 1000
                if d not in my_dist: my_dist[d] = {'snr_sum': 0, 'n': 0}
                my_dist[d]['snr_sum'] += r['snr']; my_dist[d]['n'] += 1

            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr FROM {from_p}
                WHERE {grid_cond} AND sender_callsign != %s AND sender_locator != '' AND receiver_locator != '' AND snr IS NOT NULL LIMIT 50000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['sender_locator']); rl = grid_to_latlon(r['receiver_locator'])
                if not sl[0] or not rl[0]: continue
                d = int(compute_distance_km(sl[0], sl[1], rl[0], rl[1]) // 1000) * 1000
                if d not in peer_dist: peer_dist[d] = {'snr_sum': 0, 'n': 0}
                peer_dist[d]['snr_sum'] += r['snr']; peer_dist[d]['n'] += 1

        audit['distance_efficiency'] = []
        for d in sorted(set(list(my_dist.keys()) + list(peer_dist.keys()))):
            if d > 20000: continue
            m = my_dist.get(d, {'snr_sum':0,'n':0})
            p = peer_dist.get(d, {'snr_sum':0,'n':0})
            if m['n'] >= 5 and p['n'] >= 5:
                audit['distance_efficiency'].append({
                    'range_km': d,
                    'my_snr': round(m['snr_sum']/m['n'], 1),
                    'peer_snr': round(p['snr_sum']/p['n'], 1),
                    'my_count': m['n'], 'peer_count': p['n']
                })

        # ── 4. SNR 稳定性 (标准差) ──
        cursor.execute(f"""
            SELECT {band_utils.CASE_BAND_SQL} as band, STDDEV(snr) as snr_std, AVG(snr) as snr_avg, COUNT(*) as n
            FROM {from_c} WHERE sender_callsign = %s AND snr IS NOT NULL AND frequency IS NOT NULL
            GROUP BY band HAVING n > 20 ORDER BY n DESC
        """, (call,))
        my_stability = {r['band']: {'std': round(r['snr_std'], 1), 'avg': round(r['snr_avg'], 1), 'n': r['n']} for r in cursor.fetchall()}
        cursor.execute(f"""
            SELECT {band_utils.CASE_BAND_SQL} as band, STDDEV(snr) as snr_std, AVG(snr) as snr_avg
            FROM {from_c} WHERE {grid_cond} AND sender_callsign != %s AND snr IS NOT NULL AND frequency IS NOT NULL
            GROUP BY band
        """, (call,))
        peer_stability = {r['band']: {'std': round(r['snr_std'], 1), 'avg': round(r['snr_avg'], 1)} for r in cursor.fetchall()}
        audit['stability'] = []
        for band in sorted(set(list(my_stability.keys()) + list(peer_stability.keys()))):
            m = my_stability.get(band, {})
            p = peer_stability.get(band, {})
            if m and p:
                audit['stability'].append({
                    'band': band,
                    'my_std': m['std'], 'my_avg': m['avg'], 'my_n': m['n'],
                    'peer_std': p['std'], 'peer_avg': p['avg'],
                    'verdict': '稳定' if m['std'] < p['std'] else ('波动大' if m['std'] > p['std'] * 1.3 else '正常')
                })

        # ── 5. 方向性均匀度 (SNR 方差越小 = 天线越全向) ──
        az_snrs = []
        cursor.execute(f"""
            SELECT sender_locator, receiver_locator, snr FROM {from_c}
            WHERE sender_callsign = %s AND sender_locator != '' AND receiver_locator != '' AND snr IS NOT NULL LIMIT 30000
        """, (call,))
        for r in cursor.fetchall():
            sl = grid_to_latlon(r['sender_locator']); rl = grid_to_latlon(r['receiver_locator'])
            if not sl[0] or not rl[0]: continue
            az_snrs.append(r['snr'])
        if az_snrs:
            mean = sum(az_snrs) / len(az_snrs)
            variance = sum((x - mean) ** 2 for x in az_snrs) / len(az_snrs)
        else:
            mean, variance = 0, -1
        audit['pattern_quality'] = {
            'snr_variance': round(variance, 1),
            'snr_mean': round(mean, 1),
            'samples': len(az_snrs)
        }

        return jsonify(audit)
    finally:
        cursor.close()
        conn.close()


# ==================== 天线分析 API ====================

# 电离层高度预设 (km)
IONO_HEIGHTS = {'D': 80, 'E': 120, 'F1': 200, 'F2': 300, 'F2_MAX': 400}

def elevation_angle_deg(distance_km, iono_height_km=300, earth_radius_km=6371):
    """大圆距离 → 辐射仰角 (度)，多跳球面地球模型

    单跳几何：反射点位于路径中点正上方 iono_height_km 处。在地心 O、
    发射台 T(半径 R)、反射点 P(半径 R+h) 构成的三角形中，地心半角
    γ = (单跳地面距离/2)/R，则仰角 β 满足
        tan(β) = (cos γ − R/(R+h)) / sin γ
    β 随单跳距离单调下降，0° 出现在最大单跳距离处。
    长距离超过最大单跳时按整数跳数等分，仰角由单跳距离决定（多跳模式），
    因此 DX 远距对应低仰角，NVIS 近距对应高仰角。
    """
    import math
    if distance_km <= 0:
        return 90.0
    R = earth_radius_km
    h = iono_height_km
    ratio = R / (R + h)
    # 仰角=0° 时的最大单跳地面距离 (F2@300km ≈ 3822km)
    max_hop_km = 2 * math.acos(ratio) * R
    n_hops = max(1, math.ceil(distance_km / max_hop_km))
    hop_km = distance_km / n_hops
    gamma = (hop_km / 2) / R  # 单跳地心半角
    tan_elev = (math.cos(gamma) - ratio) / max(math.sin(gamma), 1e-9)
    elev = math.degrees(math.atan(tan_elev))
    return round(max(0.0, elev), 1)

@app.route('/antenna')
def antenna_page():
    """天线分析页面"""
    return render_template('antenna.html', active_page='antenna')


@app.route('/api/antenna/elevation')
def antenna_elevation():
    """天线仰角分布 — 距离→仰角转换，对比同网格邻居"""
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    call = request.args.get('callsign', CALLSIGN).upper()
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
        ref_loc_col, target_loc_col, peer_callsign_col = "sender_locator", "receiver_locator", "sender_callsign"
    else:
        callsign_clause = "AND receiver_callsign = %s"
        ref_loc_col, target_loc_col, peer_callsign_col = "receiver_locator", "sender_locator", "receiver_callsign"

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    params = [call] + ([band_filter] if band_filter else [])

    cache_key = f"ant_elev:{year}:{call}:{role}:{band_filter}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None:
        resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(f"SELECT DISTINCT {ref_loc_col} FROM {from_c} WHERE sender_callsign = %s AND {ref_loc_col} != '' LIMIT 1", (call,))
        row = cursor.fetchone()
        grid_prefix = row[ref_loc_col][:4] if row else '????'

        my_bins = {}
        peer_bins = {}

        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table

            # My data
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr, {target_loc_col} as station_id
                FROM {from_p}
                WHERE {ref_loc_col} != '' AND {target_loc_col} != '' AND snr IS NOT NULL
                  {callsign_clause} {band_clause} LIMIT 25000
            """, params)
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if not sl[0] or not rl[0]: continue
                dist = compute_distance_km(sl[0], sl[1], rl[0], rl[1])
                elev = elevation_angle_deg(dist)
                ang = int(elev // 2) * 2
                if ang not in my_bins: my_bins[ang] = {'count': 0, 'snr_sum': 0, 'stations': set()}
                my_bins[ang]['count'] += 1
                my_bins[ang]['snr_sum'] += r['snr']
                if r['station_id']: my_bins[ang]['stations'].add(r['station_id'])

            # Peer data
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr
                FROM {from_p}
                WHERE {ref_loc_col} LIKE %s AND {peer_callsign_col} != %s
                  AND {ref_loc_col} != '' AND {target_loc_col} != '' AND snr IS NOT NULL
                  {band_clause} LIMIT 25000
            """, [grid_prefix+'%', call] + ([band_filter] if band_filter else []))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if not sl[0] or not rl[0]: continue
                dist = compute_distance_km(sl[0], sl[1], rl[0], rl[1])
                elev = elevation_angle_deg(dist)
                ang = int(elev // 2) * 2
                if ang not in peer_bins: peer_bins[ang] = {'count': 0, 'snr_sum': 0}
                peer_bins[ang]['count'] += 1
                peer_bins[ang]['snr_sum'] += r['snr']

        output = []
        for ang in range(0, 91, 2):
            m = my_bins.get(ang, {'count': 0, 'snr_sum': 0, 'stations': set()})
            p = peer_bins.get(ang, {'count': 0, 'snr_sum': 0})
            output.append({
                'angle': ang,
                'my_count': m['count'],
                'my_snr': round(m['snr_sum']/m['count'], 1) if m['count'] > 5 else None,
                'my_stations': len(m['stations']),
                'peer_count': p['count'],
                'peer_snr': round(p['snr_sum']/p['count'], 1) if p['count'] > 5 else None,
            })

        result = {'callsign': call, 'grid': grid_prefix, 'elevation': output,
                  'ionosphere': 'F2层 ~300km', 'note': '仰角=atan((h+R(1-cos(d/R)))/(R*sin(d/R)))'}
        ANTENNA_CACHE.set(cache_key, result)
        resp = jsonify(result); resp.headers['X-Cache'] = 'MISS'; return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/band_angle')
def antenna_band_angle():
    """各波段仰角分布 — 每个波段的最佳辐射仰角"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table
    callsign_clause = "sender_callsign = %s" if role == 'tx' else "receiver_callsign = %s"
    ref_loc_col = "sender_locator" if role == 'tx' else "receiver_locator"
    target_loc_col = "receiver_locator" if role == 'tx' else "sender_locator"

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)

    try:
        bands = {}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr,
                       {band_utils.CASE_BAND_SQL} as band
                FROM {from_p}
                WHERE {callsign_clause} AND {ref_loc_col} != '' AND {target_loc_col} != ''
                  AND snr IS NOT NULL AND frequency IS NOT NULL LIMIT 30000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if not sl[0] or not rl[0]: continue
                dist = compute_distance_km(sl[0], sl[1], rl[0], rl[1])
                elev = elevation_angle_deg(dist)
                band = r['band']
                if band not in bands: bands[band] = {'angles': [], 'snrs': [], 'count': 0}
                bands[band]['angles'].append(elev)
                bands[band]['snrs'].append(r['snr'])
                bands[band]['count'] += 1

        output = []
        for band, data in sorted(bands.items(), key=lambda x: -x[1]['count']):
            if data['count'] < 10: continue
            angles = data['angles']
            angles.sort()
            p10 = angles[int(len(angles)*0.1)] if len(angles) >= 10 else angles[0]
            p50 = angles[int(len(angles)*0.5)]
            p90 = angles[int(len(angles)*0.9)] if len(angles) >= 10 else angles[-1]
            avg_angle = sum(angles) / len(angles)
            avg_snr = sum(data['snrs']) / len(data['snrs'])
            output.append({
                'band': band, 'count': data['count'],
                'avg_angle': round(avg_angle, 1), 'median_angle': round(p50, 1),
                'p10_angle': round(p10, 1), 'p90_angle': round(p90, 1),
                'avg_snr': round(avg_snr, 1),
                'type': 'DX远距离低仰角' if p50 < 8 else ('中距离' if p50 < 20 else 'NVIS高仰角')
            })

        return jsonify({'callsign': call, 'bands': output})
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/hop_analysis')
def antenna_hop_analysis():
    """跳距分析 — E层/F2层 单跳/双跳 分箱，观察天线在不同电离层模式下的能量分布"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table
    callsign_clause = "sender_callsign = %s" if role == 'tx' else "receiver_callsign = %s"
    ref_loc_col = "sender_locator" if role == 'tx' else "receiver_locator"
    target_loc_col = "receiver_locator" if role == 'tx' else "sender_locator"

    cache_key = f"ant_hop:{year}:{call}:{role}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None: resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    # Hop model: E-layer ~100km, F2-layer ~300km
    # Single-hop max: E ~2000km, F2 ~4000km
    # Double-hop: F2 ~8000km
    HOP_BINS = [
        (0, 500, '地波/直达波', 'Ground'),
        (500, 2000, 'E/F2 单跳(近)', '1-hop near'),
        (2000, 4000, 'F2 单跳(远)', '1-hop far'),
        (4000, 8000, 'F2 双跳', '2-hop'),
        (8000, 16000, '多跳/长路径', 'Multi-hop'),
        (16000, 99999, '超长路径', 'Long path'),
    ]

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        hop_data = {label: {'count': 0, 'snr_sum': 0, 'snrs': [], 'stations': set()} for _, _, label, _ in HOP_BINS}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr, {target_loc_col} as stn
                FROM {from_p}
                WHERE {callsign_clause} AND {ref_loc_col} != '' AND {target_loc_col} != ''
                  AND snr IS NOT NULL LIMIT 30000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if not sl[0] or not rl[0]: continue
                dist = compute_distance_km(sl[0], sl[1], rl[0], rl[1])
                for lo, hi, label, _ in HOP_BINS:
                    if lo <= dist < hi:
                        hop_data[label]['count'] += 1
                        hop_data[label]['snr_sum'] += r['snr']
                        hop_data[label]['snrs'].append(r['snr'])
                        if r['stn']: hop_data[label]['stations'].add(r['stn'])
                        break

        output = []
        for lo, hi, label, eng in HOP_BINS:
            d = hop_data[label]
            if d['count'] > 0:
                snrs = d['snrs']
                snrs.sort()
                output.append({
                    'label': label, 'eng': eng, 'range': f'{lo}-{hi}km',
                    'count': d['count'], 'stations': len(d['stations']),
                    'avg_snr': round(d['snr_sum']/d['count'], 1),
                    'p10_snr': round(snrs[int(len(snrs)*0.1)], 1),
                    'p90_snr': round(snrs[int(len(snrs)*0.9)], 1),
                    'snr_std': round((sum((x-d['snr_sum']/d['count'])**2 for x in snrs)/len(snrs))**0.5, 1)
                })

        total = sum(o['count'] for o in output)
        for o in output: o['pct'] = round(o['count']/total*100, 1) if total else 0

        # Evaluate TX vs RX capability imbalance if this is a TX request
        insight_extra = ""
        if role == 'tx':
            dx_pct = sum(o["count"] for o in output if "双跳" in o["label"] or "多跳" in o["label"] or "长路径" in o["label"]) / max(total,1) * 100
            if dx_pct < 10:
                insight_extra = f" · ⚠ TX 远距离(>4000km)仅占 {dx_pct:.1f}%，如果 RX 能听到大量 DX，说明存在严重的非对称性(能听不能叫)，典型原因为发射仰角过高或馈线/地网损耗大"
            else:
                insight_extra = f" · ✅ TX 远距离(>4000km)达 {dx_pct:.1f}%，低仰角辐射能力良好"

        result = {'callsign': call, 'hops': output,
                  'insight': f'双跳占比={sum(o["count"] for o in output if "双跳" in o["label"] or "多跳" in o["label"])/max(total,1)*100:.0f}%' + insight_extra}
        ANTENNA_CACHE.set(cache_key, result)
        resp = jsonify(result); resp.headers['X-Cache'] = 'MISS'; return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/noise_floor')
def antenna_noise_floor():
    """方向性噪声底限 — 每方位最低 SNR，发现本地噪声源方向"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table

    cache_key = f"ant_noise:{year}:{call}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None: resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        az_bins = {}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT receiver_locator as ref_loc, sender_locator as target_loc, snr
                FROM {from_p}
                WHERE receiver_callsign = %s AND receiver_locator != '' AND sender_locator != ''
                  AND snr IS NOT NULL LIMIT 30000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if not sl[0] or not rl[0]: continue
                bearing = compute_bearing(sl[0], sl[1], rl[0], rl[1])
                az = int(bearing // 10) * 10
                if az not in az_bins: az_bins[az] = {'snrs': [], 'min_snr': 99, 'max_snr': -99, 'sum_snr': 0, 'count': 0}
                az_bins[az]['snrs'].append(r['snr'])
                az_bins[az]['min_snr'] = min(az_bins[az]['min_snr'], r['snr'])
                az_bins[az]['max_snr'] = max(az_bins[az]['max_snr'], r['snr'])
                az_bins[az]['sum_snr'] += r['snr']
                az_bins[az]['count'] += 1

        output = []
        for az in sorted(az_bins.keys()):
            d = az_bins[az]
            d['snrs'].sort()
            n = len(d['snrs'])
            output.append({
                'azimuth': az,
                'count': d['count'],
                'min_snr': d['min_snr'],
                'p5_snr': d['snrs'][int(n*0.05)] if n >= 20 else d['min_snr'],
                'avg_snr': round(d['sum_snr']/n, 1),
                'max_snr': d['max_snr'],
                'noise_warning': d['min_snr'] > -18  # 最低SNR都高于-18dB → 可能有噪声源
            })

        # Detect noise direction
        worst = min(output, key=lambda x: x['min_snr']) if output else None
        noisy_dirs = [o for o in output if o['noise_warning']]

        return jsonify({
            'callsign': call, 'noise_floor': output,
            'best_hearing': worst['min_snr'] if worst else None,
            'noisy_directions': [f'{o["azimuth"]}°(min={o["min_snr"]}dB)' for o in noisy_dirs],
            'insight': f'最安静方向能听到{worst["min_snr"]}dB信号 · ' +
                       (f'{len(noisy_dirs)}个方向疑似噪声源' if noisy_dirs else '各方向噪声底限均匀')
        })
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/tx_quality')
def antenna_tx_quality():
    """TX 发射质量诊断 — SNR 方差揭示天线/馈线/功放健康度"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Get grid peer avg std for comparison
        cursor.execute(f"SELECT DISTINCT sender_locator FROM {from_c} WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1", (call,))
        row = cursor.fetchone()
        grid_prefix = row['sender_locator'][:4] if row else '????'
        grid_cond = f"sender_locator LIKE '{grid_prefix}%'"

        quality = {}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table

            # BG1SB per-band SNR std and per-receiver variance
            cursor.execute(f"""
                SELECT {band_utils.CASE_BAND_SQL} as band,
                       receiver_callsign, snr, qso_time
                FROM {from_p}
                WHERE sender_callsign = %s AND snr IS NOT NULL AND frequency IS NOT NULL
                  AND receiver_callsign IS NOT NULL LIMIT 200000
            """, (call,))
            my_rows = list(cursor.fetchall())

            # Peer per-band SNR std
            cursor.execute(f"""
                SELECT {band_utils.CASE_BAND_SQL} as band,
                       STDDEV(snr) as peer_std, AVG(snr) as peer_avg
                FROM {from_p}
                WHERE {grid_cond} AND sender_callsign != %s AND snr IS NOT NULL AND frequency IS NOT NULL
                GROUP BY band
            """, (call,))
            peer_stats = {r['band']: {'std': round(r['peer_std'], 2), 'avg': round(r['peer_avg'], 1)} for r in cursor.fetchall()}

        # Aggregate my data
        band_data = {}
        for r in my_rows:
            b = r['band']
            if b not in band_data: band_data[b] = {'snrs': [], 'rx_var': {}}
            band_data[b]['snrs'].append(r['snr'])
            rx = r['receiver_callsign']
            if rx not in band_data[b]['rx_var']: band_data[b]['rx_var'][rx] = []
            band_data[b]['rx_var'][rx].append(r['snr'])

        output = []
        for band, data in sorted(band_data.items(), key=lambda x: -len(x[1]['snrs'])):
            if len(data['snrs']) < 30: continue
            snrs = data['snrs']
            my_std = round((sum((x-sum(snrs)/len(snrs))**2 for x in snrs)/len(snrs))**0.5, 1)
            my_avg = round(sum(snrs)/len(snrs), 1)

            # Per-receiver SNR variance (high variance = instability)
            rx_vars = []
            for rx, rx_snrs in data['rx_var'].items():
                if len(rx_snrs) >= 3:
                    rx_vars.append((sum((x-sum(rx_snrs)/len(rx_snrs))**2 for x in rx_snrs)/len(rx_snrs))**0.5)
            rx_avg_var = round(sum(rx_vars)/len(rx_vars), 1) if rx_vars else 0

            peer = peer_stats.get(band, {})
            peer_std = peer.get('std', my_std)

            # Diagnosis
            if my_std > peer_std * 1.5:
                diag = '⚠ SNR波动异常大 → 检查天线驻波/馈线接头/功放稳定性'
            elif rx_avg_var > 8:
                diag = '⚠ 同一接收台SNR抖动量 > 8dB → 天线可能受风摆/极化不稳'
            elif my_std < peer_std:
                diag = '✅ SNR稳定,优于邻居'
            else:
                diag = '➖ 正常范围内'

            output.append({
                'band': band, 'count': len(snrs), 'my_std': my_std, 'my_avg': my_avg,
                'peer_std': peer_std, 'peer_avg': peer.get('avg', 0),
                'rx_variance': rx_avg_var, 'diagnosis': diag
            })

        # Overall diagnosis
        high_std_bands = [o['band'] for o in output if '异常' in o['diagnosis']]
        unstable_bands = [o['band'] for o in output if '抖动量' in o['diagnosis']]

        return jsonify({
            'callsign': call, 'grid': grid_prefix, 'quality': output,
            'overall': '✅ TX质量良好' if not high_std_bands and not unstable_bands else
                       f'⚠ {len(high_std_bands)}个波段SNR异常, {len(unstable_bands)}个波段抖动超标'
        })
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/polar_pattern')
def antenna_polar_pattern():
    """二维方向图 — 方位角(0-355°/5°bin) × 仰角(0-60°/3°bin) 极坐标热力图。

    角向(方位)= compute_bearing 实测大圆方位，是硬数据。
    径向(仰角)= elevation_angle_deg 球面多跳模型从距离反推，是估计值。
    每个 (方位×仰角) 单元累加报文数与 SNR，得到天线在真实电离层下的方向图投影。
    """
    year = request.args.get('year', '2025')
    band_filter = request.args.get('band', '')
    call = request.args.get('callsign', CALLSIGN).upper()
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
        ref_loc_col, target_loc_col, station_col = "sender_locator", "receiver_locator", "receiver_callsign"
    else:
        callsign_clause = "AND receiver_callsign = %s"
        ref_loc_col, target_loc_col, station_col = "receiver_locator", "sender_locator", "sender_callsign"

    band_clause = f"AND ({band_utils.CASE_BAND_SQL}) = %s" if band_filter else ""
    params = [call] + ([band_filter] if band_filter else [])

    cache_key = f"ant_polar:{year}:{call}:{role}:{band_filter}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None:
        resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    AZ_BIN, EL_BIN, EL_MAX = 5, 3, 60  # 方位5°、仰角3°、仰角上限60°

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cells = {}  # (az_bin, el_bin) -> {count, snr_sum, snr_max, stations}
        total = 0
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr,
                       {station_col} as station_id
                FROM {from_p}
                WHERE {ref_loc_col} != '' AND {target_loc_col} != '' AND snr IS NOT NULL
                  {callsign_clause} {band_clause} LIMIT 50000
            """, params)
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if sl[0] is None or rl[0] is None: continue
                dist = compute_distance_km(sl[0], sl[1], rl[0], rl[1])
                if dist <= 0: continue
                az = compute_bearing(sl[0], sl[1], rl[0], rl[1])
                elev = elevation_angle_deg(dist)
                az_b = int(az // AZ_BIN) * AZ_BIN
                el_b = min(int(elev // EL_BIN) * EL_BIN, EL_MAX)
                key = (az_b, el_b)
                c = cells.get(key)
                if c is None:
                    c = {'count': 0, 'snr_sum': 0, 'snr_max': -999, 'stations': set()}
                    cells[key] = c
                c['count'] += 1
                c['snr_sum'] += r['snr']
                c['snr_max'] = max(c['snr_max'], r['snr'])
                if r['station_id']: c['stations'].add(r['station_id'])
                total += 1

        output = []
        peak = None
        for (az_b, el_b), c in cells.items():
            cell = {
                'azimuth': az_b,
                'elevation': el_b,
                'count': c['count'],
                'avg_snr': round(c['snr_sum'] / c['count'], 1),
                'max_snr': c['snr_max'],
                'stations': len(c['stations']),
            }
            output.append(cell)
            if peak is None or c['count'] > peak['count']:
                peak = cell

        result = {
            'callsign': call, 'role': role, 'band': band_filter or 'all',
            'az_bin': AZ_BIN, 'el_bin': EL_BIN, 'el_max': EL_MAX,
            'total': total, 'cells': output, 'peak': peak,
            'note': '角向=方位角(实测大圆方位) · 径向=辐射仰角(F2@300km球面模型反推,为估计值) · 颜色=报文密度',
        }
        ANTENNA_CACHE.set(cache_key, result)
        resp = jsonify(result); resp.headers['X-Cache'] = 'MISS'; return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/antenna/lobe_drift')
def antenna_lobe_drift():
    """主瓣方位漂移 — 逐波段计算主辐射方位，判断定向 vs 全向天线。

    方位是圆形量(350°与10°相邻),不能用算术平均。采用圆形统计:
    每条报文视为单位向量 (cos az, sin az),按报文数加权累加。
      - 合向量角度 = 真正的主瓣方位(mean bearing)
      - 合向量长度 R∈[0,1] = 方向集中度(集中度=1 高度聚焦/定向, =0 均匀/全向)
    各波段主瓣方位一致 → 定向天线固定指向; 方位随波段大幅漂移或 R 普遍很低 → 全向特征。
    """
    import math
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()
    role = request.args.get('role', 'tx')

    table, partitions = get_raw_table_and_partitions(year)

    if role == 'tx':
        callsign_clause = "AND sender_callsign = %s"
        ref_loc_col, target_loc_col = "sender_locator", "receiver_locator"
    else:
        callsign_clause = "AND receiver_callsign = %s"
        ref_loc_col, target_loc_col = "receiver_locator", "sender_locator"

    cache_key = f"ant_lobe:{year}:{call}:{role}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None:
        resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    def compass16(az):
        return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][round(az / 22.5) % 16]

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # band -> {sin_sum, cos_sum, count, snr_sum, az_hist{az_bin:count}}
        bands = {}
        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table
            cursor.execute(f"""
                SELECT {ref_loc_col} as ref_loc, {target_loc_col} as target_loc, snr,
                       {band_utils.CASE_BAND_SQL} as band
                FROM {from_p}
                WHERE {ref_loc_col} != '' AND {target_loc_col} != '' AND snr IS NOT NULL
                  AND frequency IS NOT NULL {callsign_clause} LIMIT 60000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['ref_loc']); rl = grid_to_latlon(r['target_loc'])
                if sl[0] is None or rl[0] is None: continue
                az = compute_bearing(sl[0], sl[1], rl[0], rl[1])
                b = r['band']
                d = bands.get(b)
                if d is None:
                    d = {'sin': 0.0, 'cos': 0.0, 'count': 0, 'snr_sum': 0, 'hist': {}}
                    bands[b] = d
                rad = math.radians(az)
                d['sin'] += math.sin(rad)
                d['cos'] += math.cos(rad)
                d['count'] += 1
                d['snr_sum'] += r['snr']
                az_b = int(az // 10) * 10
                d['hist'][az_b] = d['hist'].get(az_b, 0) + 1

        # band ordering for display (low→high freq)
        band_order = {b: i for i, b in enumerate(
            ['160m','80m','60m','40m','30m','20m','17m','15m','12m','10m','6m','4m','2m'])}
        output = []
        for band, d in bands.items():
            if d['count'] < 30: continue
            mean_az = (math.degrees(math.atan2(d['sin'], d['cos'])) + 360) % 360
            R = math.hypot(d['sin'], d['cos']) / d['count']  # 集中度 0..1
            # 峰值方位桶
            peak_bin = max(d['hist'].items(), key=lambda x: x[1])
            if R >= 0.6:
                kind = '强定向'
            elif R >= 0.35:
                kind = '弱定向'
            elif R >= 0.15:
                kind = '准全向'
            else:
                kind = '全向'
            output.append({
                'band': band,
                'mean_azimuth': round(mean_az, 1),
                'compass': compass16(mean_az),
                'concentration': round(R, 3),
                'peak_azimuth': peak_bin[0],
                'peak_count': peak_bin[1],
                'count': d['count'],
                'avg_snr': round(d['snr_sum'] / d['count'], 1),
                'type': kind,
            })
        output.sort(key=lambda x: band_order.get(x['band'], 99))

        # 跨波段一致性: 用各波段主瓣方位再做一次圆形统计
        diag = '数据不足'
        spread = None
        if len(output) >= 2:
            s = sum(math.sin(math.radians(o['mean_azimuth'])) for o in output)
            c = sum(math.cos(math.radians(o['mean_azimuth'])) for o in output)
            cross_R = math.hypot(s, c) / len(output)
            overall_az = (math.degrees(math.atan2(s, c)) + 360) % 360
            # 角向离散度(度): 圆形标准差
            spread = round(math.degrees(math.sqrt(-2 * math.log(max(cross_R, 1e-6)))), 0)
            avg_conc = sum(o['concentration'] for o in output) / len(output)
            if cross_R > 0.85 and avg_conc > 0.4:
                diag = f'各波段主瓣高度一致 (~{overall_az:.0f}° {compass16(overall_az)}), 方向集中 → 定向天线固定指向'
            elif cross_R > 0.85:
                diag = f'各波段方位一致 (~{overall_az:.0f}° {compass16(overall_az)}) 但能量分散 → 可能为有方向偏好的全向/受地形遮挡'
            elif avg_conc < 0.2:
                diag = '各波段能量普遍均匀分布 → 全向天线特征'
            else:
                diag = f'主瓣方位随波段漂移 (离散 ±{spread:.0f}°) → 多天线/不同波段不同天线, 或方向图随频率变化'

        result = {
            'callsign': call, 'role': role,
            'bands': output, 'diagnosis': diag, 'azimuth_spread': spread,
            'note': '主瓣方位=报文按方位的圆形平均(实测) · 集中度R∈[0,1],越高越定向 · 方位为硬数据,与仰角模型无关',
        }
        ANTENNA_CACHE.set(cache_key, result)
        resp = jsonify(result); resp.headers['X-Cache'] = 'MISS'; return resp
    finally:
        cursor.close()
        conn.close()


# ==================== AI 推理 API ====================

# Shared LM client (replaces inline call_lm_api + duplicate error handling)
from lm_client import call_lm, check_status, DEFAULT_MODEL as AI_DEFAULT_MODEL


@app.route('/api/antenna/weak_spots')
def antenna_weak_spots():
    """天线弱点分析 — 每波段×每方向的 ΔSNR vs 同网格邻居，找到4个核心攻坚方向"""
    year = request.args.get('year', '2025')
    call = request.args.get('callsign', CALLSIGN).upper()

    table, partitions = get_raw_table_and_partitions(year)
    from_c = table

    cache_key = f"ant_weak:{year}:{call}"
    cached = ANTENNA_CACHE.get(cache_key)
    if cached is not None: resp = jsonify(cached); resp.headers['X-Cache'] = 'HIT'; return resp

    conn = get_db_connection()
    if not conn: return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Get grid prefix
        cursor.execute(f"SELECT DISTINCT sender_locator FROM {from_c} WHERE sender_callsign = %s AND sender_locator != '' LIMIT 1", (call,))
        row = cursor.fetchone()
        if not row: return jsonify({"error": f"未找到 {call}"}), 404
        grid_prefix = row['sender_locator'][:4]

        # Per (band, azimuth_sector) bins for my callsign and peers
        my_data = {}   # (band, sector) -> {snr_sum, count}
        peer_data = {} # (band, sector) -> {snr_sum, count}
        sectors = [(a, a+30) for a in range(0, 360, 30)]  # 12 sectors of 30°

        parts = partitions or [None]
        for part in parts:
            from_p = f"{table} PARTITION({part})" if part else table

            # My TX data
            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr,
                       {band_utils.CASE_BAND_SQL} as band
                FROM {from_p}
                WHERE sender_callsign = %s AND sender_locator != '' AND receiver_locator != ''
                  AND snr IS NOT NULL AND frequency IS NOT NULL LIMIT 60000
            """, (call,))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['sender_locator']); rl = grid_to_latlon(r['receiver_locator'])
                if not sl[0] or not rl[0]: continue
                bearing = compute_bearing(sl[0], sl[1], rl[0], rl[1])
                sector = int(bearing // 30) * 30
                band = r['band']
                key = (band, sector)
                if key not in my_data: my_data[key] = {'snr_sum': 0, 'count': 0}
                my_data[key]['snr_sum'] += r['snr']
                my_data[key]['count'] += 1

            # Peer TX data
            cursor.execute(f"""
                SELECT sender_locator, receiver_locator, snr,
                       {band_utils.CASE_BAND_SQL} as band
                FROM {from_p}
                WHERE sender_locator LIKE %s AND sender_callsign != %s
                  AND sender_locator != '' AND receiver_locator != ''
                  AND snr IS NOT NULL AND frequency IS NOT NULL LIMIT 60000
            """, (grid_prefix+'%', call))
            for r in cursor.fetchall():
                sl = grid_to_latlon(r['sender_locator']); rl = grid_to_latlon(r['receiver_locator'])
                if not sl[0] or not rl[0]: continue
                bearing = compute_bearing(sl[0], sl[1], rl[0], rl[1])
                sector = int(bearing // 30) * 30
                band = r['band']
                key = (band, sector)
                if key not in peer_data: peer_data[key] = {'snr_sum': 0, 'count': 0}
                peer_data[key]['snr_sum'] += r['snr']
                peer_data[key]['count'] += 1

        # Compute ΔSNR for each (band, sector)
        results = []
        # Correctly map 0=N, 30=NNE, 60=ENE, 90=E, 120=ESE, 150=SSE, 180=S, 210=SSW, 240=WSW, 270=W, 300=WNW, 330=NNW
        # Or simpler 8 directions mapping: index = int(((sector + 22.5) % 360) // 45)
        d8 = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        for (band, sector), m in my_data.items():
            if m['count'] < 50: continue  # 提高样本阈值，过滤掉零星波段
            p = peer_data.get((band, sector), {'snr_sum': 0, 'count': 0})
            if p['count'] < 50: continue
            my_snr = round(m['snr_sum'] / m['count'], 1)
            peer_snr = round(p['snr_sum'] / p['count'], 1)
            delta = round(my_snr - peer_snr, 1)
            dir_index = int(((sector + 22.5) % 360) // 45)
            direction = f'{sector}° ({d8[dir_index]})'
            results.append({
                'band': band, 'sector': sector, 'direction': direction,
                'my_snr': my_snr, 'peer_snr': peer_snr, 'delta': delta,
                'my_count': m['count'], 'peer_count': p['count']
            })

        # Sort by delta (worst first)
        results.sort(key=lambda x: x['delta'])
        
        # 找出最弱的 (波段 + 方向) 组合，而不是按方向平均所有波段
        losses = [r for r in results if r['delta'] < -2.0]  # at least 2dB worse
        top_losses = losses[:8]

        # Top 4 weakest specific combination (band + direction)
        top4_combos = top_losses[:4]

        # Generate recommendations
        recommendations = []
        for item in top4_combos:
            direction = item['direction']
            band = item['band']
            delta = item['delta']
            
            rec = {
                'direction': direction,
                'avg_delta': delta,  # Use specific delta instead of avg
                'bands': [band],
                'worst_band': band,
                'worst_delta': delta,
                'action': ''
            }
            # Specific recommendations based on combination
            if delta <= -4.0:
                rec['action'] = f'🔴 {band}在{direction}落后{abs(delta)}dB — 核心弱点！检查天线在该方向的辐射图凹陷(null)、周边金属遮挡，或考虑为{band}增加单波段天线/调整架设高度。'
            elif delta <= -2.5:
                rec['action'] = f'🟡 {band}在{direction}落后{abs(delta)}dB — 显著弱点，检查共模电流或振子朝向。'
            else:
                rec['action'] = f'🟢 {band}在{direction}轻微落后{abs(delta)}dB — 在正常波动范围内。'

            recommendations.append(rec)

        # Build overall summary
        avg_delta_all = round(sum(r['delta'] for r in results) / max(len(results), 1), 1)
        significant_losses = len([r for r in results if r['delta'] <= -3.0])
        total_compared = len(results)

        summary = (
            f'📡 {call} 天线综合诊断：与{grid_prefix}网格邻居对比，'
            f'{total_compared}个(波段×方向)组合中，{significant_losses}个存在显著弱点(Δ≤-3dB)。'
            f'总体平均ΔSNR={avg_delta_all:+.1f}dB。'
        ) + (
            f'⚡ 核心痛点：{", ".join(r["band"] + "向" + r["direction"] for r in top4_combos)}。'
            f'详见下方推荐。'
        ) if top4_combos else '✅ 无显著弱点，天线在各方向及波段表现与邻居持平或更优。'

        result = {
            'callsign': call, 'grid': grid_prefix, 'summary': summary,
            'avg_delta': avg_delta_all,
            'total_compared': total_compared, 'significant_losses': significant_losses,
            'top_losses': top_losses,
            'top4_directions': recommendations, # Reusing the field name for frontend compatibility
            'all_results': sorted(results, key=lambda x: x['delta'])[:30]  # top 30 worst
        }

        ANTENNA_CACHE.set(cache_key, result)
        resp = jsonify(result); resp.headers['X-Cache'] = 'MISS'; return resp
    finally:
        cursor.close()
        conn.close()


@app.route('/api/ai/analyze', methods=['POST'])
def ai_analyze():
    """
    AI 智能分析 API

    请求体:
    {
        "type": "propagation" | "dxcc" | "custom",
        "days": 7,
        "prompt": "自定义提示词（当 type=custom 时使用）"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400
    
    analysis_type = data.get('type', 'propagation')
    days = data.get('days', 7)
    custom_prompt = data.get('prompt', '')
    
    # 获取数据库数据
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        if analysis_type == 'propagation':
            # 获取传播数据
            cursor.execute(f"""
                SELECT COUNT(*) as total,
                       COUNT(DISTINCT callsign) as unique_calls,
                       COUNT(DISTINCT country) as unique_countries,
                       AVG(distance) as avg_distance
                FROM qso_log
                WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
            """)
            qso = cursor.fetchone()
            
            cursor.execute(f"""
                SELECT band, COUNT(*) as count
                FROM qso_log
                WHERE qso_time >= DATE_SUB(NOW(), INTERVAL {days} DAY)
                GROUP BY band
                ORDER BY count DESC
                LIMIT 8
            """)
            bands = cursor.fetchall()
            
            bands_str = "\n".join([f"- {b.get('band', 'N/A')}: {b.get('count', 0)} 次" for b in bands])
            
            prompt = f"""作为业余无线电传播专家，请分析以下数据：

## 最近 {days} 天 QSO 统计
- 总通联: {qso.get('total', 0)} 次
- 独特呼号: {qso.get('unique_calls', 0)}
- 通联国家: {qso.get('unique_countries', 0)}
- 平均距离: {round(qso.get('avg_distance', 0), 0) if qso.get('avg_distance') else 0} km

## 波段分布
{bands_str}

请提供：
1. 当前传播条件评估（优秀/良好/一般/较差）
2. 最佳操作波段建议
3. 操作建议

请用中文简洁回复。"""

        elif analysis_type == 'dxcc':
            # 获取 DXCC 数据
            cursor.execute("""
                SELECT country, COUNT(*) as count
                FROM qso_log
                GROUP BY country
                ORDER BY count DESC
                LIMIT 20
            """)
            countries = cursor.fetchall()
            
            countries_str = "\n".join([f"- {c.get('country', 'N/A')}: {c.get('count', 0)} 次" for c in countries[:15]])
            
            prompt = f"""作为DXCC专家，请分析：

## 已通联国家
{countries_str}

请给出：
1. DXCC进度评估
2. 建议攻克的国家
3. 基于当前传播条件的可行性

用中文回复。"""

        elif analysis_type == 'custom':
            if not custom_prompt:
                return jsonify({"error": "自定义分析需要提供 prompt 参数"}), 400
            prompt = custom_prompt
            
        else:
            return jsonify({"error": f"未知的分析类型: {analysis_type}"}), 400
        
        # 调用 AI 推理
        result = call_lm(prompt)
        
        return jsonify({
            "type": analysis_type,
            "ai_result": result,
            "prompt_length": len(prompt),
            "timestamp": datetime.datetime.now().isoformat()
        })
        
    finally:
        cursor.close()
        conn.close()


@app.route('/api/ai/status', methods=['GET'])
def ai_status():
    """检查 AI 推理服务状态"""
    return jsonify(check_status())


# ==================== 主入口 ====================

if __name__ == '__main__':
    # 监听所有接口（包括 IPv4 和 IPv6）
    app.run(debug=True, host='::', port=5000)
