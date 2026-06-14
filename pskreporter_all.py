#!/usr/bin/env python3
"""
PSKReporter 全量数据获取器 - 定期拉取所有呼号的传播数据
每 5 分钟获取一次全量数据，保存为 ADIF 格式到 logs/ALL 目录，同时写入数据库

数据采集原则（遵循 PSK Reporter API 规范）：
1. 查询频率节制：最小间隔 5 分钟，推荐更长
2. 负载分散：添加随机抖动，避免整点同步
3. 身份标识：User-Agent 包含联系方式
4. 避免重复：使用去重机制

使用方法:
  python3 pskreporter_all.py           # 单次运行
  python3 pskreporter_all.py --daemon  # 守护进程模式（已弃用，建议用 cron）
  python3 pskreporter_all.py --import  # 导入存量 ADIF 文件到数据库
"""

import argparse
import csv
import datetime
import glob
import io
import json
import os
import random
import re
import signal
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

# PSK Reporter API 限制常量
PSKREPORTER_MIN_INTERVAL = 300  # PSK Reporter 要求最小查询间隔 5 分钟

# StarRocks/MySQL 支持 (StarRocks 兼容 MySQL 协议)
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# HTTP 客户端用于 Stream Load
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# 全局运行标志
running = True


class DatabaseManager:
    """
    数据库管理器 (StarRocks)
    
    使用 Stream Load API 进行批量数据导入，是原子操作，只产生一个版本。
    这从根本上解决了 "too many versions" 问题。
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = {
            "host": config.get("host", "ham.vlsc.net"),
            "mysql_port": config.get("port", 9030),  # MySQL 协议端口
            "http_port": config.get("http_port", 8030),  # StarRocks HTTP 端口
            "user": config.get("user", "root"),
            "password": config.get("password", ""),
            "database": config.get("name", "pskreporter"),
            "charset": "utf8mb4"
        }
        self.connection = None
        self.http_client = None
        
        # 初始化 HTTP 客户端用于 Stream Load
        if HTTPX_AVAILABLE:
            self.http_client = httpx.Client(timeout=60.0, follow_redirects=True)
    
    def connect(self) -> bool:
        """连接数据库"""
        if not MYSQL_AVAILABLE:
            print("警告: mysql-connector-python 未安装，无法使用 MySQL 协议")
            return False
        
        try:
            self.connection = mysql.connector.connect(
                host=self.config["host"],
                port=self.config["mysql_port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"],
                charset=self.config["charset"]
            )
            return True
        except MySQLError as e:
            print(f"数据库连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
        if self.http_client:
            self.http_client.close()
    
    def insert_records(self, records: List[Dict[str, Any]]) -> int:
        """
        插入记录到 all_records 表
        优先使用 Stream Load（原子操作，只产生一个版本）
        写入前会过滤已存在的记录（基于 sender_callsign, receiver_callsign, frequency, mode, qso_time）
        
        Args:
            records: 记录列表
        
        Returns:
            插入的记录数
        """
        if not records:
            return 0
        
        # 去重：过滤已存在的记录
        records = self._filter_existing(records)
        if not records:
            return 0
        
        # 优先使用 Stream Load
        if self.http_client:
            return self._stream_load(records)
        
        # 降级到 MySQL 协议批量插入
        if self.connection and self.connection.is_connected():
            return self._insert_via_mysql(records)
        
        return 0
    
    def _filter_existing(self, records: List[Dict[str, Any]], batch_size: int = 500) -> List[Dict[str, Any]]:
        """
        过滤已存在的记录
        
        使用更高效的方式：按时间范围查询，然后在内存中过滤
        
        Args:
            records: 记录列表
            batch_size: 每批查询的记录数（减小以避免条件复杂度限制）
        
        Returns:
            不存在的记录列表
        """
        if not self.connection or not self.connection.is_connected():
            return records
        
        if not records:
            return []
        
        # 获取时间范围
        timestamps = []
        for rec in records:
            try:
                ts = rec.get("flowStartSeconds", 0)
                if ts > 0:
                    timestamps.append(datetime.datetime.fromtimestamp(ts))
            except (ValueError, TypeError):
                pass
        
        if not timestamps:
            return records
        
        min_time = min(timestamps)
        max_time = max(timestamps)
        
        cursor = self.connection.cursor()
        existing_keys = set()
        
        # 按时间范围查询已存在的记录
        try:
            sql = """
            SELECT sender_callsign, receiver_callsign, frequency, mode, qso_time 
            FROM all_records 
            WHERE qso_time >= %s AND qso_time <= %s
            """
            cursor.execute(sql, (min_time, max_time))
            
            for row in cursor.fetchall():
                existing_keys.add((row[0], row[1], row[2], row[3], row[4]))
            
            print(f"  时间范围 [{min_time} ~ {max_time}] 已存在 {len(existing_keys)} 条")
            
        except MySQLError as e:
            print(f"  查询已存在记录失败: {e}")
            # 查询失败时，返回空列表，不插入任何记录（安全起见）
            cursor.close()
            return []
        
        cursor.close()
        
        # 过滤已存在的记录
        new_records = []
        for rec in records:
            try:
                qso_time = datetime.datetime.fromtimestamp(rec.get("flowStartSeconds", 0))
            except (ValueError, TypeError):
                continue
            
            key = (
                rec.get("senderCallsign", ""),
                rec.get("receiverCallsign", ""),
                rec.get("frequency", 0) or 0,
                rec.get("mode", ""),
                qso_time
            )
            
            if key not in existing_keys:
                new_records.append(rec)
        
        filtered_count = len(records) - len(new_records)
        if filtered_count > 0:
            print(f"  过滤重复记录: {filtered_count} 条")
        
        return new_records
    
    def _stream_load(self, records: List[Dict[str, Any]]) -> int:
        """
        使用 StarRocks Stream Load API 批量导入数据
        
        Stream Load 是原子操作，整个批次只产生一个版本，
        从根本上解决 "too many versions" 问题。
        """
        if not records:
            return 0
        
        now = datetime.datetime.now()
        # 生成唯一 ID：使用秒级时间戳 * 1000000 + 序号，确保不超出 BIGINT 范围
        # BIGINT 最大值: 9223372036854775807
        # 当前时间戳 (2026年) 约 1770000000，* 10000000000 = 17700000000000000000 (超出范围)
        # 使用更安全的 ID 生成策略：秒级时间戳 * 1000000 + 序号
        base_ts = int(now.timestamp())
        
        # 准备 CSV 数据
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')
        
        valid_count = 0
        for i, rec in enumerate(records):
            try:
                qso_time = datetime.datetime.fromtimestamp(rec.get("flowStartSeconds", 0))
            except (ValueError, TypeError):
                continue
            
            try:
                snr_val = int(rec.get("sNR", 0)) if rec.get("sNR") else 0
            except ValueError:
                snr_val = 0
            
            # 生成唯一 ID: 秒级时间戳 * 1000000 + 序号 + 随机数
            # 最大值约 1770000000 * 1000000 + 1000000 + 9999 ≈ 1.77e15，在 BIGINT 范围内
            record_id = base_ts * 1000000 + i * 10 + random.randint(0, 9)
            
            # CSV 行: 按表字段顺序
            writer.writerow([
                record_id,
                rec.get("senderCallsign", "") or "",
                rec.get("receiverCallsign", "") or "",
                rec.get("frequency", 0) or 0,
                qso_time.strftime("%Y-%m-%d %H:%M:%S"),
                rec.get("senderLocator", "") or "",
                rec.get("receiverLocator", "") or "",
                snr_val,
                rec.get("mode", "") or "",
                rec.get("senderDXCC", "") or "",
                rec.get("senderDXCCCode", "") or "",
                now.strftime("%Y-%m-%d %H:%M:%S")
            ])
            valid_count += 1
        
        if valid_count == 0:
            return 0
        
        csv_data = output.getvalue().encode('utf-8')
        
        # Stream Load URL
        url = f"http://{self.config['host']}:{self.config['http_port']}/api/{self.config['database']}/all_records/_stream_load"
        
        # Stream Load headers
        headers = {
            "Content-Type": "application/octet-stream",
            "Expect": "100-continue",
            "format": "CSV",
            "column_separator": ",",
            "columns": "id,sender_callsign,receiver_callsign,frequency,qso_time,sender_locator,receiver_locator,snr,mode,sender_country,sender_dxcc,fetch_time",
            "strict_mode": "false",
            "max_filter_ratio": "0.1",  # 允许 10% 的错误行
        }
        
        # 认证 (StarRocks 使用 Basic Auth)
        auth = None
        if self.config["user"]:
            auth = httpx.BasicAuth(self.config["user"], self.config["password"])
        
        try:
            # 手动处理重定向：StarRocks FE 会重定向到 BE，需要重新发送认证
            with httpx.Client(timeout=60.0, follow_redirects=False) as client:
                response = client.put(url, content=csv_data, headers=headers, auth=auth)
                
                # 处理 307 重定向
                if response.status_code == 307:
                    be_url = response.headers.get("location")
                    if be_url:
                        # 直接发送到 BE，带上认证
                        response = client.put(be_url, content=csv_data, headers=headers, auth=auth)
                
                if response.status_code != 200:
                    print(f"  Stream Load HTTP 错误: {response.status_code}")
                    if self.connection and self.connection.is_connected():
                        print("  降级到 MySQL 协议...")
                        return self._insert_via_mysql(records)
                    return 0
                
                try:
                    result = response.json()
                except Exception:
                    print(f"  Stream Load 非 JSON 响应")
                    if self.connection and self.connection.is_connected():
                        print("  降级到 MySQL 协议...")
                        return self._insert_via_mysql(records)
                    return 0
            
            if result.get("Status") == "Success":
                loaded = int(result.get("NumberLoadedRows", 0))
                return loaded
            elif result.get("Status") == "Publish Timeout":
                # 数据已导入，但发布超时，通常也是成功的
                loaded = int(result.get("NumberLoadedRows", 0))
                print(f"  Stream Load 发布超时，已加载 {loaded} 条")
                return loaded
            else:
                print(f"  Stream Load 失败: {result.get('Message', 'Unknown error')}")
                # 降级到 MySQL 协议
                if self.connection and self.connection.is_connected():
                    print("  降级到 MySQL 协议...")
                    return self._insert_via_mysql(records)
                return 0
                
        except httpx.ConnectError as e:
            print(f"  Stream Load 连接失败: {e}")
            print(f"  请检查 config.json 中的 http_port 配置（StarRocks 默认 8030）")
            if self.connection and self.connection.is_connected():
                print("  降级到 MySQL 协议...")
                return self._insert_via_mysql(records)
            return 0
        except Exception as e:
            print(f"  Stream Load 异常: {e}")
            # 降级到 MySQL 协议
            if self.connection and self.connection.is_connected():
                print("  降级到 MySQL 协议...")
                return self._insert_via_mysql(records)
            return 0
    
    def _insert_via_mysql(self, records: List[Dict[str, Any]], batch_size: int = 5000) -> int:
        """
        通过 MySQL 协议批量插入（降级方案）
        
        使用大批量和合并提交来减少版本数
        """
        if not self.connection or not self.connection.is_connected():
            return 0
        
        if not records:
            return 0
        
        inserted = 0
        cursor = self.connection.cursor()
        
        sql = """
        INSERT INTO all_records 
        (id, sender_callsign, receiver_callsign, frequency, qso_time, 
         sender_locator, receiver_locator, snr, mode, sender_country, sender_dxcc, fetch_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        now = datetime.datetime.now()
        base_ts = int(now.timestamp())
        
        # 准备批量数据
        batch_values = []
        for i, rec in enumerate(records):
            try:
                qso_time = datetime.datetime.fromtimestamp(rec.get("flowStartSeconds", 0))
            except (ValueError, TypeError):
                continue
            
            try:
                snr_val = int(rec.get("sNR", 0)) if rec.get("sNR") else None
            except ValueError:
                snr_val = None
            
            # 生成唯一 ID：与 Stream Load 保持一致
            record_id = base_ts * 1000000 + i * 10 + random.randint(0, 9)
            
            batch_values.append((
                record_id,
                rec.get("senderCallsign", ""),
                rec.get("receiverCallsign", ""),
                rec.get("frequency", 0) or 0,
                qso_time,
                rec.get("senderLocator", "") or None,
                rec.get("receiverLocator", "") or None,
                snr_val,
                rec.get("mode", "") or None,
                rec.get("senderDXCC", "") or None,
                rec.get("senderDXCCCode", "") or None,
                now
            ))
        
        # 分批插入，每批一次提交
        for i in range(0, len(batch_values), batch_size):
            batch = batch_values[i:i + batch_size]
            try:
                cursor.executemany(sql, batch)
                self.connection.commit()  # 整批提交一次，产生一个版本
                inserted += len(batch)
            except MySQLError as e:
                print(f"  批量插入错误: {e}")
                self.connection.rollback()
        
        cursor.close()
        return inserted
    
    def insert_records_batch(self, records: List[Dict[str, Any]], batch_size: int = 5000) -> int:
        """
        批量插入记录（兼容旧接口）
        
        Args:
            records: 记录列表
            batch_size: 每批插入的记录数（Stream Load 时忽略此参数）
        
        Returns:
            插入的记录数
        """
        return self.insert_records(records)
    
    def get_count(self) -> int:
        """获取记录总数"""
        if not self.connection or not self.connection.is_connected():
            return 0
        
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM all_records")
        count = cursor.fetchone()[0]
        cursor.close()
        return count


class PSKReporterAllFetcher:
    """
    PSKReporter 全量数据获取器
    
    遵循 PSK Reporter API 规范：
    - 查询间隔 >= 5 分钟
    - 添加随机抖动避免整点同步
    - User-Agent 包含联系方式
    - 支持 lastseqno 增量查询
    """
    
    BASE_URL = "https://retrieve.pskreporter.info/query"
    LASTSEQNO_FILE = "logs/.lastseqno"  # 存储 lastseqno 的文件
    
    # 类级别的最后查询时间（用于频率控制）
    _last_query_time = 0
    
    def __init__(self, log_dir: str = "logs", db_config: Optional[Dict[str, Any]] = None,
                 callsign: str = "", appcontact: str = ""):
        self.log_dir = log_dir
        self.callsign = callsign.upper()
        self.appcontact = appcontact
        self.db_manager = None
        self.last_sequence_number = 0  # 上次获取的最后序列号
        self._ensure_log_dir()
        self._load_lastseqno()
        
        # 初始化数据库连接
        if db_config and MYSQL_AVAILABLE:
            self.db_manager = DatabaseManager(db_config)
            if self.db_manager.connect():
                print("数据库连接成功")
            else:
                self.db_manager = None
    
    def _load_lastseqno(self) -> None:
        """从文件加载上次保存的 lastseqno"""
        filepath = os.path.join(self.log_dir, ".lastseqno")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    self.last_sequence_number = int(f.read().strip())
            except:
                self.last_sequence_number = 0
    
    def _save_lastseqno(self) -> None:
        """保存 lastseqno 到文件"""
        filepath = os.path.join(self.log_dir, ".lastseqno")
        try:
            with open(filepath, "w") as f:
                f.write(str(self.last_sequence_number))
        except Exception as e:
            print(f"  保存 lastseqno 失败: {e}")
    
    def __del__(self):
        if self.db_manager:
            self.db_manager.disconnect()
    
    def _get_user_agent(self) -> str:
        """
        生成规范化的 User-Agent
        
        格式: PSKReporterAllFetcher/VERSION (CALLSIGN; contact@email)
        """
        version = "1.1"
        if self.appcontact:
            return f"PSKReporterAllFetcher/{version} ({self.callsign}; {self.appcontact})"
        elif self.callsign:
            return f"PSKReporterAllFetcher/{version} ({self.callsign})"
        return f"PSKReporterAllFetcher/{version}"
    
    def _enforce_rate_limit(self, min_interval: int = PSKREPORTER_MIN_INTERVAL) -> None:
        """
        强制执行查询频率限制
        
        PSK Reporter API 要求：查询间隔不少于 5 分钟
        
        Args:
            min_interval: 最小间隔秒数（默认 300 秒 = 5 分钟）
        """
        now = time.time()
        elapsed = now - PSKReporterAllFetcher._last_query_time
        
        if elapsed < min_interval:
            # 添加随机抖动（0-60秒），避免整点同步
            jitter = random.randint(0, 60)
            sleep_time = min_interval - elapsed + jitter
            print(f"  频率限制：等待 {int(sleep_time)} 秒后继续...")
            time.sleep(sleep_time)
        
        PSKReporterAllFetcher._last_query_time = time.time()
    
    def _ensure_log_dir(self) -> None:
        """确保日志目录存在"""
        all_dir = os.path.join(self.log_dir, "ALL")
        if not os.path.exists(all_dir):
            os.makedirs(all_dir)
    
    def fetch_all(self, hours: float = 24/60, use_incremental: bool = True) -> tuple:
        """
        获取全量数据（不限制呼号）
        
        Args:
            hours: 查询过去多少小时（可以是小数，如 2/60 表示2分钟）
            use_incremental: 是否使用增量查询（基于 lastseqno）
        
        Returns:
            (记录列表, lastSequenceNumber)
        """
        # 强制频率限制
        self._enforce_rate_limit()
        
        # 计算秒数
        seconds = int(hours * 3600)
        # 限制最大24小时
        seconds = min(seconds, 86400)
        
        params = {
            "flowStartSeconds": -seconds,
            "rronly": 1,  # 只要接收报告
        }
        
        # 添加联系方式（PSK Reporter API 强烈推荐）
        if self.appcontact:
            params["appcontact"] = self.appcontact
        
        # 增量查询：使用 lastseqno 获取新数据
        if use_incremental and self.last_sequence_number > 0:
            params["lastseqno"] = self.last_sequence_number
            print(f"  增量查询: lastseqno={self.last_sequence_number}")
        
        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{query_string}"
        
        try:
            req = urllib.request.Request(url)
            # 使用规范化的 User-Agent（包含联系方式）
            req.add_header("User-Agent", self._get_user_agent())
            
            with urllib.request.urlopen(req, timeout=60) as response:
                xml_data = response.read().decode("utf-8")
                records, last_seq = self._parse_reception_reports(xml_data)
                
                # 更新 lastseqno
                if last_seq > self.last_sequence_number:
                    self.last_sequence_number = last_seq
                    self._save_lastseqno()
                
                return records, last_seq
        
        except urllib.error.URLError as e:
            print(f"  网络错误: {e}")
            return [], 0
        except Exception as e:
            print(f"  获取数据时发生错误: {e}")
            return [], 0
    
    def _parse_reception_reports(self, xml_data: str) -> tuple:
        """
        解析 XML 数据
        
        Returns:
            (记录列表, lastSequenceNumber)
        """
        records = []
        last_seq = 0
        
        try:
            root = ET.fromstring(xml_data)
            
            # 获取 lastSequenceNumber
            last_seq_elem = root.find(".//lastSequenceNumber")
            if last_seq_elem is not None:
                last_seq = int(last_seq_elem.get("value", 0) or 0)
            
            for report in root.findall(".//receptionReport"):
                record = {
                    "senderCallsign": report.get("senderCallsign", ""),
                    "receiverCallsign": report.get("receiverCallsign", ""),
                    "senderLocator": report.get("senderLocator", ""),
                    "receiverLocator": report.get("receiverLocator", ""),
                    "frequency": int(report.get("frequency", 0) or 0),
                    "sNR": report.get("sNR", ""),
                    "mode": report.get("mode", ""),
                    "flowStartSeconds": int(report.get("flowStartSeconds", 0) or 0),
                    "senderDXCC": report.get("senderDXCC", ""),
                    "senderDXCCCode": report.get("senderDXCCCode", ""),
                }
                records.append(record)
        
        except ET.ParseError as e:
            print(f"  XML 解析错误: {e}")
        
        return records, last_seq
    
    def _generate_adif_field(self, name: str, value: Any) -> str:
        """生成 ADIF 格式字段"""
        if value is None or value == "":
            return ""
        value_str = str(value)
        return f"<{name.upper()}:{len(value_str)}>{value_str}"
    
    def save_adif(self, records: List[Dict[str, Any]]) -> str:
        """
        保存记录为 ADIF 格式
        
        Args:
            records: 记录列表
        
        Returns:
            保存的文件路径
        """
        now = datetime.datetime.now()
        all_dir = os.path.join(self.log_dir, "ALL")
        
        # 文件名: YYYY-MM-DD_HHMMSS.adi
        filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}.adi"
        filepath = os.path.join(all_dir, filename)
        
        # 生成 ADIF 内容
        lines = []
        
        # ADIF 头部
        lines.append("# PSKReporter 全量数据导出")
        lines.append(f"# 获取时间: {now.isoformat()}")
        lines.append(f"# 记录数量: {len(records)}")
        lines.append("")
        lines.append("<ADIF_VER:5>3.1.0")
        lines.append("<PROGRAMID:19>PSKReporterAllFetcher")
        lines.append("<PROGRAMVERSION:3>1.0")
        lines.append("<EOH>")
        lines.append("")
        
        # 记录
        for rec in records:
            fields = []
            
            # 日期时间
            if rec.get("flowStartSeconds"):
                try:
                    ts = datetime.datetime.fromtimestamp(rec["flowStartSeconds"])
                    fields.append(self._generate_adif_field("QSO_DATE", ts.strftime("%Y%m%d")))
                    fields.append(self._generate_adif_field("TIME_ON", ts.strftime("%H%M%S")))
                except:
                    pass
            
            # 呼号和定位
            fields.append(self._generate_adif_field("CALL", rec.get("senderCallsign", "")))
            fields.append(self._generate_adif_field("OPERATOR", rec.get("receiverCallsign", "")))
            fields.append(self._generate_adif_field("GRIDSQUARE", rec.get("senderLocator", "")))
            fields.append(self._generate_adif_field("MY_GRIDSQUARE", rec.get("receiverLocator", "")))
            
            # 频率 (Hz -> MHz)
            if rec.get("frequency"):
                freq_mhz = rec["frequency"] / 1000000
                fields.append(self._generate_adif_field("FREQ", f"{freq_mhz:.6f}"))
            
            # 模式和 SNR
            fields.append(self._generate_adif_field("MODE", rec.get("mode", "")))
            fields.append(self._generate_adif_field("APP_PSKREP_SNR", rec.get("sNR", "")))
            
            # DXCC 信息
            if rec.get("senderDXCC"):
                fields.append(self._generate_adif_field("COUNTRY", rec.get("senderDXCC", "")))
            if rec.get("senderDXCCCode"):
                fields.append(self._generate_adif_field("APP_PSKREP_DXCC", rec.get("senderDXCCCode", "")))
            
            # 过滤空字段
            fields = [f for f in fields if f]
            if fields:
                lines.append("".join(fields) + "<EOR>")
        
        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        # 写入数据库
        db_inserted = 0
        if self.db_manager:
            db_inserted = self.db_manager.insert_records(records)
        
        return filepath, db_inserted
    
    def print_summary(self, records: List[Dict[str, Any]]) -> None:
        """打印摘要"""
        print(f"\n{'='*70}")
        print(f"获取时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"记录数量: {len(records)}")
        print(f"{'='*70}")
        
        if records:
            # 按模式统计
            modes = {}
            for r in records:
                mode = r.get("mode", "UNKNOWN")
                modes[mode] = modes.get(mode, 0) + 1
            
            print(f"\n按模式统计:")
            for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
                print(f"  {mode}: {count} 条")
            
            # 按频段统计
            bands = {}
            for r in records:
                freq = r.get("frequency", 0)
                if freq > 0:
                    band = self._freq_to_band(freq)
                    bands[band] = bands.get(band, 0) + 1
            
            print(f"\n按频段统计:")
            for band, count in sorted(bands.items(), key=lambda x: -x[1])[:10]:
                print(f"  {band}: {count} 条")
            
            # 最新记录
            print(f"\n最新 10 条记录:")
            print("-" * 70)
            print(f"{'发送方':<12} {'接收方':<12} {'频率':<12} {'模式':<6} {'SNR':>4}")
            print("-" * 70)
            for rec in sorted(records, key=lambda x: x.get("flowStartSeconds", 0), reverse=True)[:10]:
                freq_khz = rec["frequency"] / 1000
                print(f"{rec['senderCallsign']:<12} {rec['receiverCallsign']:<12} "
                      f"{freq_khz:>8.2f} kHz {rec['mode']:<6} {rec['sNR']:>4}")
    
    def _freq_to_band(self, freq_hz: int) -> str:
        """频率转频段"""
        freq_mhz = freq_hz / 1000000
        if freq_mhz < 2: return "160m"
        elif freq_mhz < 4: return "80m"
        elif freq_mhz < 5: return "60m"
        elif freq_mhz < 8: return "40m"
        elif freq_mhz < 11: return "30m"
        elif freq_mhz < 15: return "20m"
        elif freq_mhz < 19: return "17m"
        elif freq_mhz < 22: return "15m"
        elif freq_mhz < 26: return "12m"
        elif freq_mhz < 30: return "10m"
        elif freq_mhz < 55: return "6m"
        elif freq_mhz < 150: return "2m"
        else: return f"{int(freq_mhz)}MHz"
    
    def parse_adif_file(self, filepath: str) -> List[Dict[str, Any]]:
        """
        解析 ADIF 文件
        
        Args:
            filepath: ADIF 文件路径
        
        Returns:
            记录列表
        """
        records = []
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            print(f"读取文件失败: {e}")
            return []
        
        # 跳过头部
        eoh_match = re.search(r'<eoh>', content, re.IGNORECASE)
        if eoh_match:
            content = content[eoh_match.end():]
        
        # 按 <eor> 分割记录
        raw_records = re.split(r'<eor>', content, flags=re.IGNORECASE)
        
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
                    value = value[:length]
                except ValueError:
                    pass
                
                record[field_name] = value
            
            if record:
                # 转换为标准格式
                converted = self._convert_adif_record(record)
                if converted:
                    records.append(converted)
        
        return records
    
    def _convert_adif_record(self, rec: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """将 ADIF 记录转换为标准格式"""
        # 解析日期时间
        qso_date = rec.get("QSO_DATE", "")
        time_on = rec.get("TIME_ON", "")
        
        timestamp = None
        if qso_date and time_on:
            try:
                dt_str = f"{qso_date} {time_on.zfill(6)}"
                timestamp = datetime.datetime.strptime(dt_str, "%Y%m%d %H%M%S")
            except ValueError:
                pass
        
        if not timestamp:
            return None
        
        # 解析频率
        freq = rec.get("FREQ", "0")
        try:
            freq_hz = int(float(freq) * 1000000)
        except ValueError:
            freq_hz = 0
        
        # 解析 SNR
        snr = rec.get("APP_PSKREP_SNR", "")
        
        return {
            "senderCallsign": rec.get("CALL", ""),
            "receiverCallsign": rec.get("OPERATOR", ""),
            "senderLocator": rec.get("GRIDSQUARE", ""),
            "receiverLocator": rec.get("MY_GRIDSQUARE", ""),
            "frequency": freq_hz,
            "sNR": snr,
            "mode": rec.get("MODE", ""),
            "flowStartSeconds": int(timestamp.timestamp()) if timestamp else 0,
            "senderDXCC": rec.get("COUNTRY", ""),
            "senderDXCCCode": rec.get("APP_PSKREP_DXCC", ""),
        }
    
    def import_adif_files(self, pattern: str = "logs/ALL/*.adi", delay: float = 0.5) -> tuple:
        """
        导入 ADIF 文件到数据库
        
        Args:
            pattern: 文件匹配模式
            delay: 每个文件导入后的延迟秒数（避免 StarRocks 版本限制）
        
        Returns:
            (总记录数, 插入记录数)
        """
        if not self.db_manager:
            print("数据库未连接")
            return (0, 0)
        
        files = sorted(glob.glob(pattern))
        if not files:
            print(f"未找到匹配的文件: {pattern}")
            return (0, 0)
        
        print(f"找到 {len(files)} 个 ADIF 文件")
        
        total_records = 0
        total_inserted = 0
        
        for i, filepath in enumerate(files):
            records = self.parse_adif_file(filepath)
            if records:
                # 使用批量插入
                inserted = self.db_manager.insert_records_batch(records, batch_size=500)
                total_records += len(records)
                total_inserted += inserted
                print(f"  [{i+1}/{len(files)}] {os.path.basename(filepath)}: {len(records)} 条, 新增 {inserted} 条")
                
                # 添加延迟避免 StarRocks 版本限制
                if delay > 0 and i < len(files) - 1:
                    time.sleep(delay)
        
        print(f"\n导入完成: 总计 {total_records} 条, 成功插入 {total_inserted} 条")
        return (total_records, total_inserted)


def signal_handler(signum, frame):
    """信号处理器"""
    global running
    print("\n收到停止信号，正在退出...")
    running = False


def main():
    global running
    
    # 查找配置文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    # 加载配置
    db_config = None
    appcontact = ""
    callsign = ""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                db_config = config.get("database")
                appcontact = config.get("appcontact", "")
                callsign = config.get("callsign", "")
        except:
            pass
    
    parser = argparse.ArgumentParser(
        description="PSKReporter 全量数据获取器 - 定期拉取所有呼号的传播数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s              单次运行
  %(prog)s --daemon     守护进程模式（建议改用 cron）
  %(prog)s --hours 12   获取过去12小时的数据
  %(prog)s --import     导入存量 ADIF 文件到数据库
  %(prog)s --import "logs/BG1SB/*.adi"  导入指定目录的 ADIF 文件

数据采集原则（遵循 PSK Reporter API 规范）：
  - 查询间隔 >= 5 分钟（API 要求）
  - 添加随机抖动，避免整点同步
  - 建议在 config.json 中配置 appcontact 参数
        """
    )
    
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="守护进程模式，持续运行（建议改用 cron）"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="守护进程模式下的间隔秒数（默认300秒=5分钟）"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=0,
        help="查询过去多少小时的数据（默认0，由 --minutes 参数决定）"
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=1,
        help="查询过去多少分钟的数据（默认1分钟，PSK Reporter API 只返回最近约1分钟数据）"
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="日志保存目录（默认: logs）"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="静默模式，只输出错误信息"
    )
    parser.add_argument(
        "--import",
        dest="import_pattern",
        nargs="?",
        const="logs/ALL/*.adi",
        default=None,
        help="导入存量 ADIF 文件到数据库（默认: logs/ALL/*.adi）"
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="不写入数据库"
    )
    parser.add_argument(
        "--appcontact",
        default=appcontact,
        help="联系方式（PSK Reporter API 推荐填写）"
    )
    parser.add_argument(
        "--callsign",
        default=callsign,
        help="呼号（用于 User-Agent 标识）"
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="使用增量查询模式（基于 lastseqno，只获取新数据）"
    )
    parser.add_argument(
        "--reset-seq",
        action="store_true",
        help="重置 lastseqno，从头开始获取"
    )
    
    args = parser.parse_args()
    
    # 初始化获取器（带 appcontact 参数）
    fetcher = PSKReporterAllFetcher(
        log_dir=args.log_dir,
        db_config=None if args.no_db else db_config,
        callsign=args.callsign,
        appcontact=args.appcontact
    )
    
    # 重置 lastseqno
    if args.reset_seq:
        fetcher.last_sequence_number = 0
        fetcher._save_lastseqno()
        print("已重置 lastseqno")
    
    # 导入模式
    if args.import_pattern:
        print(f"导入 ADIF 文件: {args.import_pattern}")
        total, inserted = fetcher.import_adif_files(args.import_pattern)
        print(f"\n导入完成: 共 {total} 条记录, 新增 {inserted} 条")
        
        if fetcher.db_manager:
            count = fetcher.db_manager.get_count()
            print(f"数据库总记录数: {count}")
        return
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 输出配置信息
    if args.appcontact:
        print(f"联系方式: {args.appcontact}")
    
    if args.daemon:
        # 守护进程模式
        print(f"启动守护进程模式，间隔 {args.interval} 秒")
        print(f"日志保存到: {os.path.join(args.log_dir, 'ALL')}")
        if args.incremental:
            print(f"增量查询模式: lastseqno={fetcher.last_sequence_number}")
        print("按 Ctrl+C 停止\n")
        
        fetch_count = 0
        
        while running:
            fetch_count += 1
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if not args.quiet:
                print(f"[{now_str}] 第 {fetch_count} 次获取...")
            
            # 获取数据（增量或全量）
            records, last_seq = fetcher.fetch_all(
                hours=hours,
                use_incremental=args.incremental
            )
            
            if records:
                # 保存 ADIF
                filepath, db_inserted = fetcher.save_adif(records)
                
                if not args.quiet:
                    print(f"  获取 {len(records)} 条记录 (lastseqno={last_seq})")
                    print(f"  保存到: {filepath}")
                    if db_inserted > 0:
                        print(f"  写入数据库: {db_inserted} 条")
                    fetcher.print_summary(records)
            else:
                if not args.quiet:
                    print("  未获取到数据")
            
            # 等待下一次
            # 添加随机偏移（±5秒）避免与其他客户端同步
            jitter = random.randint(-5, 5)
            sleep_time = args.interval + jitter
            
            if not args.quiet:
                next_time = datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
                print(f"\n下次运行: {next_time.strftime('%H:%M:%S')} (等待 {sleep_time} 秒)\n")
            
            # 分段睡眠以响应信号
            for _ in range(sleep_time):
                if not running:
                    break
                time.sleep(1)
        
        print("守护进程已停止")
    
    else:
        # 单次运行
        # 计算时间范围：优先使用 minutes 参数
        if args.minutes > 0:
            hours_frac = args.minutes / 60.0
        else:
            hours_frac = min(args.hours, 24)
        
        records, last_seq = fetcher.fetch_all(
            hours=hours_frac,
            use_incremental=args.incremental
        )
        
        if records:
            filepath, db_inserted = fetcher.save_adif(records)
            print(f"保存到: {filepath}")
            print(f"lastseqno: {last_seq}")
            if db_inserted > 0:
                print(f"写入数据库: {db_inserted} 条")
            
            if not args.quiet:
                fetcher.print_summary(records)
        else:
            print("未获取到数据")


if __name__ == "__main__":
    main()
