#!/usr/bin/env python3
"""
WSJT-X / JTDX 日志导入工具
从 wsjtx_log.adi 文件导入真实通联记录到 StarRocks 数据库
支持增量同步，定期检查文件更新
"""

import argparse
import datetime
import json
import os
import re
import sys
from typing import List, Dict, Any, Optional

# DXCC lookup module (shared with web_app.py)
try:
    from dxcc_lookup import lookup_callsign
except ImportError:
    lookup_callsign = lambda c: None
# StarRocks 数据库支持 (兼容 MySQL 协议)
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


class ADIFParser:
    """ADIF 格式解析器"""
    
    def parse(self, data: str) -> List[Dict[str, Any]]:
        """
        解析 ADIF 格式数据
        
        Args:
            data: ADIF 格式的字符串
        
        Returns:
            解析后的记录列表
        """
        records = []
        
        # 跳过头部（<eoh> 或 <EOH> 之前的内容）
        eoh_match = re.search(r'<eoh>', data, re.IGNORECASE)
        if eoh_match:
            data = data[eoh_match.end():]
        
        # 按 <eor> 分割记录
        raw_records = re.split(r'<eor>', data, flags=re.IGNORECASE)
        
        for raw_record in raw_records:
            if not raw_record.strip():
                continue
            
            record = {}
            
            # 匹配所有字段: <FIELDNAME:LENGTH>VALUE 或 <FIELDNAME:LENGTH:TYPE>VALUE
            pattern = r'<([a-zA-Z_0-9]+):(\d+)(?::([a-zA-Z]))?>([^<]*)'
            matches = re.findall(pattern, raw_record)
            
            for field_name, length, type_hint, value in matches:
                field_name = field_name.upper()
                try:
                    length = int(length)
                    # 截取正确长度
                    value = value[:length]
                except ValueError:
                    pass
                
                record[field_name] = value.strip()
            
            if record:
                records.append(record)
        
        return records


class QSOImporter:
    """通联日志导入器"""
    
    # 默认的 WSJT-X / JTDX 日志文件路径
    DEFAULT_LOG_PATHS = [
        os.path.expanduser("~/Library/Application Support/WSJT-X/wsjtx_log.adi"),
        os.path.expanduser("~/Library/Application Support/JTDX/wsjtx_log.adi"),
        os.path.expanduser("~/.local/share/WSJT-X/wsjtx_log.adi"),
        os.path.expanduser("~/.local/share/JTDX/wsjtx_log.adi"),
        os.path.expanduser("~/Documents/WSJT-X/wsjtx_log.adi"),
        os.path.expanduser("~/Documents/JTDX/wsjtx_log.adi"),
    ]
    
    # DXCC 前缀映射已迁移到 dxcc_lookup 模块
    # 包含 290+ DXCC 实体的完整前缀匹配
    
    def __init__(self, db_config: Optional[Dict[str, Any]] = None):
        """初始化导入器"""
        self.parser = ADIFParser()
        self.db_config = db_config or {}
        self.connection = None
    
    def connect(self) -> bool:
        """连接数据库"""
        if not MYSQL_AVAILABLE:
            print("错误: mysql-connector-python 未安装")
            return False
        
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            return True
        except MySQLError as e:
            print(f"数据库连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
    
    def get_dxcc(self, callsign: str) -> str:
        """
        根据呼号前缀获取 DXCC 国家
        
        委托给 dxcc_lookup 模块，该模块包含完整的 ARRL DXCC 实体映射。
        
        Args:
            callsign: 业余无线电呼号
        
        Returns:
            DXCC 实体名称，或 None
        """
        if not callsign:
            return None
        
        result = lookup_callsign(callsign)
        return result["name"] if result else None
    
    def grid_to_latlon(self, grid: str) -> Optional[tuple]:
        """将 Maidenhead 网格定位转换为经纬度"""
        if not grid or len(grid) < 4:
            return None
        
        grid = grid.upper()
        
        try:
            lon1 = ord(grid[0]) - ord('A')
            lat1 = ord(grid[1]) - ord('A')
            lon2 = int(grid[2])
            lat2 = int(grid[3])
            
            lon3 = 0
            lat3 = 0
            if len(grid) >= 6:
                lon3 = ord(grid[4].lower()) - ord('a')
                lat3 = ord(grid[5].lower()) - ord('a')
            
            lon = -180 + (lon1 * 20) + (lon2 * 2) + (lon3 * (2/24)) + (1/24)
            lat = -90 + (lat1 * 10) + (lat2 * 1) + (lat3 * (1/24)) + (1/48)
            
            return (round(lat, 4), round(lon, 4))
        except (ValueError, IndexError):
            return None
    
    def calculate_distance_bearing(self, lat1: float, lon1: float, lat2: float, lon2: float) -> tuple:
        """计算两点间的距离和方位角"""
        import math
        
        # 转换为弧度
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        lon1_rad = math.radians(lon1)
        lon2_rad = math.radians(lon2)
        
        # 地球半径 (km)
        R = 6371
        
        # 计算距离 (Haversine 公式)
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        # 计算方位角
        x = math.sin(dlon) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
        bearing = math.degrees(math.atan2(x, y))
        bearing = (bearing + 360) % 360
        
        return (round(distance, 1), round(bearing, 1))
    
    def find_log_files(self) -> List[str]:
        """查找所有可用的日志文件"""
        found = []
        for path in self.DEFAULT_LOG_PATHS:
            if os.path.exists(path):
                found.append(path)
        return found
    
    def get_file_mtime(self, filepath: str) -> int:
        """获取文件最后修改时间戳"""
        try:
            return int(os.path.getmtime(filepath))
        except:
            return 0
    
    def get_last_sync(self, source_file: str) -> Optional[Dict]:
        """获取上次同步记录"""
        if not self.connection:
            return None
        
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT * FROM sync_log 
                WHERE source_file = %s 
                ORDER BY sync_time DESC 
                LIMIT 1
            """, (source_file,))
            return cursor.fetchone()
        finally:
            cursor.close()
    
    def record_exists(self, callsign: str, station_callsign: str, qso_time: datetime.datetime, frequency_mhz: float) -> bool:
        """检查记录是否已存在"""
        if not self.connection:
            return False
        
        cursor = self.connection.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM qso_log 
                WHERE callsign = %s 
                AND station_callsign = %s 
                AND qso_time = %s
                AND frequency = %s
            """, (callsign, station_callsign, qso_time, frequency_mhz))
            count = cursor.fetchone()[0]
            return count > 0
        finally:
            cursor.close()
    
    def import_file(self, filepath: str, force: bool = False) -> Dict:
        """
        导入单个日志文件
        
        Args:
            filepath: 日志文件路径
            force: 是否强制重新导入（忽略增量同步）
        
        Returns:
            导入结果统计
        """
        result = {
            "file": filepath,
            "success": False,
            "total_records": 0,
            "imported": 0,
            "skipped": 0,
            "new_records": 0,
            "error": None
        }
        
        if not os.path.exists(filepath):
            result["error"] = f"文件不存在: {filepath}"
            return result
        
        # 读取文件
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                data = f.read()
        except Exception as e:
            result["error"] = f"读取文件失败: {e}"
            return result
        
        # 解析 ADIF
        records = self.parser.parse(data)
        result["total_records"] = len(records)
        
        if not records:
            result["error"] = "未找到有效记录"
            return result
        
        # 检查增量同步
        file_mtime = self.get_file_mtime(filepath)
        if not force:
            last_sync = self.get_last_sync(filepath)
            if last_sync and last_sync.get('last_modified', 0) >= file_mtime:
                result["success"] = True
                result["skipped"] = len(records)
                result["error"] = "文件未修改，跳过同步"
                return result
        
        # 连接数据库
        if not self.connection:
            if not self.connect():
                result["error"] = "数据库连接失败"
                return result
        
        cursor = self.connection.cursor()
        imported = 0
        new_records = 0
        batch_values = []
        total = len(records)
        
        # 预加载已存在的记录ID到缓存（避免逐条查询）
        existing_ids = set()
        if not force:
            try:
                cursor.execute("SELECT id FROM qso_log")
                for row in cursor.fetchall():
                    existing_ids.add(row[0])
                print(f"  已缓存 {len(existing_ids)} 条现有记录ID")
            except Exception as e:
                print(f"  警告: 缓存加载失败，将跳过重复检查: {e}")
        
        print(f"  处理 {total} 条记录...")
        
        try:
            for rec in records:
                # 解析日期时间
                qso_date = rec.get("QSO_DATE", "")
                time_on = rec.get("TIME_ON", "")
                
                if not qso_date:
                    continue
                
                try:
                    if time_on:
                        dt_str = f"{qso_date} {time_on.zfill(6)}"
                        qso_time = datetime.datetime.strptime(dt_str, "%Y%m%d %H%M%S")
                    else:
                        qso_time = datetime.datetime.strptime(qso_date, "%Y%m%d")
                except ValueError:
                    continue
                
                # 解析频率
                freq = rec.get("FREQ", "0")
                try:
                    freq_mhz = float(freq)
                except ValueError:
                    freq_mhz = 0.0
                
                # 获取呼号
                callsign = rec.get("CALL", "").upper()
                station_callsign = rec.get("STATION_CALLSIGN", "BG1SB").upper()
                
                if not callsign:
                    continue
                
                # 生成唯一主键ID (基于唯一键字段的确定性hash，确保去重)
                # 使用 callsign + station_callsign + qso_time + frequency 生成唯一ID
                import hashlib
                unique_key = f"{callsign}|{station_callsign}|{qso_time.isoformat()}|{freq_mhz}"
                hash_val = hashlib.md5(unique_key.encode()).hexdigest()
                record_id = int(hash_val[:14], 16)  # 取前14位转整数，足够大且唯一
                
                # 检查是否已存在（使用缓存）
                if not force and record_id in existing_ids:
                    continue
                
                # 计算距离和方位角
                distance = None
                bearing = None
                
                my_grid = rec.get("MY_GRIDSQUARE", "")
                other_grid = rec.get("GRIDSQUARE", "")
                
                if my_grid and other_grid:
                    my_loc = self.grid_to_latlon(my_grid)
                    other_loc = self.grid_to_latlon(other_grid)
                    if my_loc and other_loc:
                        distance, bearing = self.calculate_distance_bearing(
                            my_loc[0], my_loc[1], other_loc[0], other_loc[1]
                        )
                
                # 获取国家
                country = self.get_dxcc(callsign)

                # 插入记录 - 使用 INSERT 处理
                insert_sql = """
                INSERT INTO qso_log (
                    id, callsign, station_callsign, qso_time, frequency,
                    grid_locator, my_grid_locator, mode, rst_sent, rst_rcvd, qso_date, band,
                    tx_pwr, comment, source_file, distance, bearing, country
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """

                values = (
                    record_id,
                    callsign,
                    station_callsign,
                    qso_time,
                    freq_mhz,
                    rec.get("GRIDSQUARE", "") or None,
                    rec.get("MY_GRIDSQUARE", "") or None,
                    rec.get("MODE", "") or None,
                    rec.get("RST_SENT", "") or None,
                    rec.get("RST_RCVD", "") or None,
                    qso_time.date(),
                    rec.get("BAND", "") or None,
                    int(rec.get("TX_PWR", 0)) if rec.get("TX_PWR") else None,
                    rec.get("COMMENT", "") or None,
                    filepath,
                    distance,
                    bearing,
                    country
                )

                # 添加到批量插入列表
                batch_values.append(values)
                imported += 1
                
                # 每 500 条批量插入一次
                if len(batch_values) >= 500:
                    self._batch_insert(cursor, batch_values)
                    new_records += len(batch_values)
                    batch_values = []
                    print(f"    已导入: {imported}/{total} ({imported/total*100:.1f}%)", end='\r', flush=True)
            
            # 插入剩余记录
            if batch_values:
                self._batch_insert(cursor, batch_values)
                new_records += len(batch_values)
            
            print(f"    已导入: {imported}/{total} (100.0%)  - 完成")
            
            # 记录同步日志 (使用秒级时间戳作为 ID，避免 int 溢出)
            now = datetime.datetime.now()
            log_id = int(now.timestamp())  # 只使用秒级时间戳，约 1.7B < 2.1B (int max)

            sync_sql = """
            INSERT INTO sync_log (id, source_type, source_file, last_modified, records_imported, records_new, sync_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            source_type = "jtdx" if "JTDX" in filepath else "wsjtx"
            try:
                cursor.execute(sync_sql, (
                    log_id,
                    source_type,
                    filepath,
                    file_mtime,
                    imported,
                    new_records,
                    now,
                    "success"
                ))
            except MySQLError as e:
                print(f"  同步日志记录失败: {e}")
            
            self.connection.commit()
            result["success"] = True
            result["imported"] = imported
            result["new_records"] = new_records
            
        except MySQLError as e:
            result["error"] = f"数据库错误: {e}"
            self.connection.rollback()
        finally:
            cursor.close()
        
        return result
    
    def _batch_insert(self, cursor, batch_values):
        """批量插入记录"""
        if not batch_values:
            return
        
        insert_sql = """
        INSERT INTO qso_log (
            id, callsign, station_callsign, qso_time, frequency,
            grid_locator, my_grid_locator, mode, rst_sent, rst_rcvd, qso_date, band,
            tx_pwr, comment, source_file, distance, bearing, country
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        try:
            cursor.executemany(insert_sql, batch_values)
        except MySQLError as e:
            err_str = str(e)
            if "Duplicate" in err_str:
                # 有重复记录，尝试逐条插入
                for values in batch_values:
                    try:
                        cursor.execute(insert_sql, values)
                    except MySQLError as e2:
                        if "Duplicate" not in str(e2):
                            print(f"  插入记录失败: {e2}")
            else:
                print(f"  批量插入失败: {e}")
    
    def import_all(self, force: bool = False) -> List[Dict]:
        """导入所有找到的日志文件"""
        files = self.find_log_files()
        results = []
        
        for filepath in files:
            print(f"\n处理文件: {filepath}")
            result = self.import_file(filepath, force=force)
            results.append(result)
            
            if result["success"]:
                print(f"  总记录: {result['total_records']}")
                print(f"  新导入: {result['imported']}")
                if result.get("skipped"):
                    print(f"  跳过: {result['skipped']}")
            else:
                print(f"  错误: {result.get('error', '未知错误')}")
        
        return results


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    default_config = {
        "callsign": "BG1SB",
        "database": {
            "host": "ham.vlsc.net",
            "port": 9030,  # StarRocks 默认端口
            "user": "root",
            "password": "",
            "database": "pskreporter",
            "charset": "utf8mb4"
        },
        "wsjtx_log_paths": []
    }
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                # 合并配置
                if "database" in user_config:
                    default_config["database"].update(user_config["database"])
                if "wsjtx_log_paths" in user_config:
                    default_config["wsjtx_log_paths"] = user_config["wsjtx_log_paths"]
                if "callsign" in user_config:
                    default_config["callsign"] = user_config["callsign"]
        except (json.JSONDecodeError, IOError) as e:
            print(f"配置文件读取错误，使用默认配置: {e}")
    
    return default_config


def main():
    """主函数"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    config = load_config(config_path)
    
    parser = argparse.ArgumentParser(
        description="WSJT-X / JTDX 日志导入工具 - 同步真实通联记录到数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 自动查找并导入所有日志文件
  %(prog)s --force                   # 强制重新导入所有记录
  %(prog)s --file /path/to/log.adi   # 导入指定文件
  %(prog)s --list                    # 列出所有可用的日志文件
        """
    )
    
    parser.add_argument(
        "--file", "-f",
        help="指定要导入的日志文件路径"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新导入（忽略增量同步）"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用的日志文件"
    )
    parser.add_argument(
        "--db-host",
        default=config["database"]["host"],
        help=f"数据库主机（默认: {config['database']['host']}）"
    )
    parser.add_argument(
        "--db-port",
        type=int,
        default=config["database"]["port"],
        help=f"数据库端口（默认: {config['database']['port']}）"
    )
    parser.add_argument(
        "--db-user",
        default=config["database"]["user"],
        help=f"数据库用户名（默认: {config['database']['user']}）"
    )
    parser.add_argument(
        "--db-password",
        default=config["database"]["password"],
        help="数据库密码"
    )
    parser.add_argument(
        "--db-name",
        default=config["database"]["database"],
        help=f"数据库名（默认: {config['database']['database']}）"
    )
    
    args = parser.parse_args()
    
    # 数据库配置
    db_config = {
        "host": args.db_host,
        "port": args.db_port,
        "user": args.db_user,
        "password": args.db_password,
        "database": args.db_name,
        "charset": "utf8mb4"
    }
    
    # 创建导入器
    importer = QSOImporter(db_config=db_config)
    
    # 添加自定义日志路径
    if config.get("wsjtx_log_paths"):
        for path in config["wsjtx_log_paths"]:
            path = os.path.expanduser(path)
            if path not in importer.DEFAULT_LOG_PATHS:
                importer.DEFAULT_LOG_PATHS.insert(0, path)
    
    # 列出文件
    if args.list:
        print("可用的日志文件:")
        for filepath in importer.find_log_files():
            mtime = datetime.datetime.fromtimestamp(importer.get_file_mtime(filepath))
            print(f"  {filepath}")
            print(f"    最后修改: {mtime}")
        return
    
    # 连接数据库
    print(f"连接数据库 {args.db_host}:{args.db_port}...")
    if not importer.connect():
        print("数据库连接失败")
        sys.exit(1)
    print("数据库连接成功")
    
    try:
        # 导入
        if args.file:
            result = importer.import_file(args.file, force=args.force)
            print(f"\n导入结果:")
            print(f"  文件: {result['file']}")
            print(f"  总记录: {result['total_records']}")
            print(f"  新导入: {result['imported']}")
            if result.get("error"):
                print(f"  信息: {result['error']}")
        else:
            results = importer.import_all(force=args.force)
            
            total_imported = sum(r["imported"] for r in results)
            total_new = sum(r.get("new_records", 0) for r in results)
            
            print(f"\n" + "="*50)
            print(f"总计: 导入 {total_imported} 条记录 (新增 {total_new} 条)")
    finally:
        importer.disconnect()


if __name__ == "__main__":
    main()
