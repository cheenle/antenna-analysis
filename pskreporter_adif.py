#!/usr/bin/env python3
"""
PSKReporter ADIF Fetcher - 使用 ADIF 接口获取完整的历史数据
支持获取过去多天的完整传播记录

ADIF 接口返回的数据比实时查询接口更完整，适合用于历史数据存档

数据采集原则（遵循 PSK Reporter API 规范）：
1. 查询频率节制：最小间隔 5 分钟，推荐更长
2. 负载分散：添加随机抖动，避免整点同步
3. 身份标识：User-Agent 包含联系方式
4. 避免重复：使用去重机制
"""

import argparse
import datetime
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional

# DXCC lookup module (shared with web_app.py)
try:
    from dxcc_lookup import lookup_callsign
except ImportError:
    # Fallback: if running from another directory
    import imp
    lookup_callsign = lambda c: None

# PSK Reporter API 限制常量
PSKREPORTER_MIN_INTERVAL = 300  # PSK Reporter 要求最小查询间隔 5 分钟

# StarRocks 数据库支持 (兼容 MySQL 协议)
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


class DatabaseManager:
    """StarRocks 数据库管理器"""
    
    def __init__(self, host: str = "ham.vlsc.net", port: int = 9030,
                 user: str = "root", password: str = "",
                 database: str = "pskreporter"):
        """
        初始化数据库管理器
        
        Args:
            host: 数据库主机
            port: 数据库端口 (MySQL 默认 3306)
            user: 用户名
            password: 密码
            database: 数据库名
        """
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "charset": "utf8mb4"
        }
        self.connection = None
    
    def connect(self) -> bool:
        """连接数据库"""
        if not MYSQL_AVAILABLE:
            print("警告: mysql-connector-python 未安装，数据库功能不可用")
            print("请运行: pip install mysql-connector-python")
            return False
        
        try:
            self.connection = mysql.connector.connect(**self.config)
            return True
        except MySQLError as e:
            print(f"数据库连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开数据库连接"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
    
    def insert_records(self, records: List[Dict[str, Any]], callsign: str, adif_file: str = None) -> tuple:
        """
        插入记录到数据库
        
        Args:
            records: 记录列表
            callsign: 呼号
            adif_file: ADIF 文件路径
        
        Returns:
            (sender_inserted, receiver_inserted) 插入的记录数
        """
        if not self.connection or not self.connection.is_connected():
            return (0, 0)
        
        sender_records = [r for r in records if r.get("is_sender")]
        receiver_records = [r for r in records if r.get("is_receiver")]
        
        sender_inserted = 0
        receiver_inserted = 0
        
        cursor = self.connection.cursor()
        
        # StarRocks PRIMARY KEY 表要求 id 必须唯一
        # 使用微秒级时间戳 + 随机偏移确保唯一性
        import random
        base_id = int(time.time() * 1000000) + random.randint(0, 999999)  # 微秒时间戳 + 随机偏移
        id_counter = 0  # 递增计数器
        
        insert_sender_sql = """
        INSERT INTO sender_records 
        (id, sender_callsign, receiver_callsign, frequency, qso_time,
         sender_locator, receiver_locator, snr, mode, distance, bearing, country, dxcc, fetch_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        for record in sender_records:
            try:
                qso_time = datetime.datetime.fromtimestamp(record.get("flowStartSeconds", 0))
            except:
                continue
            
            try:
                snr_val = int(record.get("sNR", 0)) if record.get("sNR") else None
            except ValueError:
                snr_val = None
            
            try:
                distance_val = float(record.get("distance", 0)) if record.get("distance") else None
            except ValueError:
                distance_val = None
            
            try:
                bearing_val = float(record.get("bearing", 0)) if record.get("bearing") else None
            except ValueError:
                bearing_val = None
            
            id_counter += 1
            values = (
                base_id + id_counter,
                record.get("senderCallsign", ""),
                record.get("receiverCallsign", ""),
                record.get("frequency", 0) or 0,
                qso_time,
                record.get("senderLocator", "") or None,
                record.get("receiverLocator", "") or None,
                snr_val,
                record.get("mode", "") or None,
                distance_val,
                bearing_val,
                record.get("country", "") or None,
                record.get("dxcc", "") or None,
                datetime.datetime.now()
            )
            
            try:
                cursor.execute(insert_sender_sql, values)
                sender_inserted += 1
            except MySQLError as e:
                pass  # 忽略重复记录错误
        
        # 插入接收记录
        insert_receiver_sql = """
        INSERT INTO receiver_records 
        (id, sender_callsign, receiver_callsign, frequency, qso_time,
         sender_locator, receiver_locator, snr, mode, distance, bearing, country, dxcc, fetch_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        for record in receiver_records:
            try:
                qso_time = datetime.datetime.fromtimestamp(record.get("flowStartSeconds", 0))
            except:
                continue
            
            try:
                snr_val = int(record.get("sNR", 0)) if record.get("sNR") else None
            except ValueError:
                snr_val = None
            
            try:
                distance_val = float(record.get("distance", 0)) if record.get("distance") else None
            except ValueError:
                distance_val = None
            
            try:
                bearing_val = float(record.get("bearing", 0)) if record.get("bearing") else None
            except ValueError:
                bearing_val = None
            
            id_counter += 1
            values = (
                base_id + id_counter,
                record.get("senderCallsign", ""),
                record.get("receiverCallsign", ""),
                record.get("frequency", 0) or 0,
                qso_time,
                record.get("senderLocator", "") or None,
                record.get("receiverLocator", "") or None,
                snr_val,
                record.get("mode", "") or None,
                distance_val,
                bearing_val,
                record.get("country", "") or None,
                record.get("dxcc", "") or None,
                datetime.datetime.now()
            )
            
            try:
                cursor.execute(insert_receiver_sql, values)
                receiver_inserted += 1
            except MySQLError as e:
                pass  # 忽略重复记录错误
        
        # 记录获取日志
        # fetch_log 是 PRIMARY KEY 表，id 必须唯一
        # 使用毫秒级时间戳取模确保唯一性且在 INT 范围内
        import random
        log_id = (int(time.time() * 1000) + random.randint(0, 999)) % 2147483647
        insert_log_sql = """
        INSERT INTO fetch_log (id, callsign, fetch_time, sender_count, receiver_count, source, adif_file)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        now = datetime.datetime.now()
        
        # 截断过长的 callsign 以符合 VARCHAR(20) 限制
        db_callsign = callsign.upper()[:20]

        cursor.execute(insert_log_sql, (
            log_id,
            db_callsign,
            now,
            sender_inserted,
            receiver_inserted,
            "ADIF",
            adif_file
        ))
        
        self.connection.commit()
        cursor.close()
        
        return (sender_inserted, receiver_inserted)


class ADIFParser:
    """ADIF 格式解析器"""
    
    def __init__(self):
        self.records = []
    
    def parse(self, data: str) -> List[Dict[str, Any]]:
        """
        解析 ADIF 格式数据
        
        ADIF 格式示例:
        <FREQ:9>14.074808<MODE:3>FT8<OPERATOR:5>BG1SB<eor>
        
        Args:
            data: ADIF 格式的字符串
        
        Returns:
            解析后的记录列表
        """
        records = []
        
        # 跳过头部（<eoh> 之前的内容）
        eoh_match = re.search(r'<eoh>', data, re.IGNORECASE)
        if eoh_match:
            data = data[eoh_match.end():]
        
        # 按 <eor> 分割记录
        raw_records = re.split(r'<eor>', data, flags=re.IGNORECASE)
        
        for raw_record in raw_records:
            if not raw_record.strip():
                continue
            
            record = {}
            
            # 匹配所有字段: <FIELDNAME:LENGTH>VALUE
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
                
                record[field_name] = value
            
            if record:
                records.append(record)
        
        return records


class PSKReporterADIF:
    """
    PSKReporter ADIF 数据获取器
    
    遵循 PSK Reporter API 规范：
    - 查询间隔 >= 5 分钟
    - 添加随机抖动避免整点同步
    - User-Agent 包含联系方式
    """
    
    ADIF_URL = "https://pskreporter.info/cgi-bin/pskdata.pl"
    
    # 类级别的最后查询时间（用于频率控制）
    _last_query_time = 0
    
    def __init__(self, log_dir: str = "logs", db_config: Optional[Dict[str, Any]] = None,
                 callsign: str = "", appcontact: str = ""):
        """
        初始化获取器
        
        Args:
            log_dir: 日志保存目录
            db_config: 数据库配置（可选）
            callsign: 呼号（用于 User-Agent 标识）
            appcontact: 联系方式（PSK Reporter API 推荐）
        """
        self.log_dir = log_dir
        self.callsign = callsign.upper()
        self.appcontact = appcontact
        self.parser = ADIFParser()
        self.db_manager = None
        self._ensure_log_dir()
        
        # 初始化数据库连接
        if db_config:
            self.db_manager = DatabaseManager(**db_config)
    
    def _get_user_agent(self) -> str:
        """
        生成规范化的 User-Agent
        
        格式: PSKReporterADIF/VERSION (CALLSIGN; contact@email)
        """
        version = "1.1"
        if self.appcontact:
            return f"PSKReporterADIF/{version} ({self.callsign}; {self.appcontact})"
        elif self.callsign:
            return f"PSKReporterADIF/{version} ({self.callsign})"
        return f"PSKReporterADIF/{version}"
    
    def _enforce_rate_limit(self, min_interval: int = PSKREPORTER_MIN_INTERVAL) -> None:
        """
        强制执行查询频率限制
        
        PSK Reporter API 要求：查询间隔不少于 5 分钟
        
        Args:
            min_interval: 最小间隔秒数（默认 300 秒 = 5 分钟）
        """
        now = time.time()
        elapsed = now - PSKReporterADIF._last_query_time
        
        if elapsed < min_interval:
            # 添加随机抖动（0-60秒），避免整点同步
            jitter = random.randint(0, 60)
            sleep_time = min_interval - elapsed + jitter
            print(f"  频率限制：等待 {int(sleep_time)} 秒后继续...")
            time.sleep(sleep_time)
        
        PSKReporterADIF._last_query_time = time.time()
    
    def connect_db(self, host: str = "ham.vlsc.net", port: int = 9030,
                   user: str = "root", password: str = "",
                   database: str = "pskreporter") -> bool:
        """
        连接数据库
        
        Args:
            host: 数据库主机
            port: 数据库端口
            user: 用户名
            password: 密码
            database: 数据库名
        
        Returns:
            是否连接成功
        """
        self.db_manager = DatabaseManager(
            host=host, port=port, user=user, 
            password=password, database=database
        )
        return self.db_manager.connect()
    
    def disconnect_db(self):
        """断开数据库连接"""
        if self.db_manager:
            self.db_manager.disconnect()
    
    def save_to_db(self, records: List[Dict[str, Any]], callsign: str, adif_file: str = None) -> tuple:
        """
        保存记录到数据库
        
        Args:
            records: 记录列表
            callsign: 呼号
            adif_file: ADIF 文件路径
        
        Returns:
            (sender_inserted, receiver_inserted) 插入的记录数
        """
        if not self.db_manager:
            print("数据库未连接")
            return (0, 0)
        
        if not self.db_manager.connection or not self.db_manager.connection.is_connected():
            if not self.db_manager.connect():
                return (0, 0)
        
        return self.db_manager.insert_records(records, callsign, adif_file)
    
    def _ensure_log_dir(self) -> None:
        """确保日志目录存在"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
    
    def fetch(self, 
              callsign: str, 
              days: int = 1,
              sender_only: bool = False,
              receiver_only: bool = False) -> List[Dict[str, Any]]:
        """
        获取指定呼号的 ADIF 数据
        
        Args:
            callsign: 呼号
            days: 获取过去几天的数据
            sender_only: 只获取发送方记录
            receiver_only: 只获取接收方记录
        
        Returns:
            记录列表
        """
        # 强制频率限制
        self._enforce_rate_limit()
        
        # 清理呼号（只取第一个单词，去除可能的备注）
        clean_callsign = callsign.upper().split()[0]
        url = f"{self.ADIF_URL}?adif=1&days={days}&callsign={clean_callsign}"
        
        try:
            req = urllib.request.Request(url)
            # 使用规范化的 User-Agent（包含联系方式）
            req.add_header("User-Agent", self._get_user_agent())
            
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read().decode("utf-8", errors="replace")
                records = self.parser.parse(data)
                
                # 转换为统一格式并区分发送/接收记录
                processed_records = []
                
                for rec in records:
                    processed = self._convert_record(rec, callsign.upper())
                    if processed:
                        # 根据过滤条件
                        is_sender = processed.get("is_sender", False)
                        is_receiver = processed.get("is_receiver", False)
                        
                        if sender_only and not is_sender:
                            continue
                        if receiver_only and not is_receiver:
                            continue
                        
                        processed_records.append(processed)
                
                return processed_records
        
        except urllib.error.URLError as e:
            print(f"网络错误: {e}")
            return []
        except Exception as e:
            print(f"获取数据时发生错误: {e}")
            return []
    
    def _convert_record(self, rec: Dict[str, str], my_callsign: str) -> Optional[Dict[str, Any]]:
        """
        将 ADIF 记录转换为统一格式
        
        PSK Reporter ADIF 数据结构：
        - OPERATOR = 报告方（对方电台，发送信号被本台接收）
        - CALL = 被报告方（本台 BG1SB，接收方）
        - MY_GRIDSQUARE = 报告方定位（对方）
        - GRIDSQUARE = 被报告方定位（本台 ON80da）
        - COUNTRY = 被报告方国家（本台国家）
        
        Args:
            rec: ADIF 记录
            my_callsign: 本台呼号
        
        Returns:
            转换后的记录
        """
        operator = rec.get("OPERATOR", "").upper()  # 报告方（对方）
        call = rec.get("CALL", "").upper()  # 被报告方（本台）
        
        # 清理呼号（只取第一个单词，去除可能的备注）
        clean_my_callsign = my_callsign.upper().split()[0]
        
        # ADIF 数据中的 COUNTRY 是被报告方（本台）的国家，不是对方的国家
        # 需要根据对方呼号推断对方国家
        adif_country = rec.get("COUNTRY", "")
        adif_dxcc = rec.get("DXCC", "")
        
        # 判断记录类型
        # CALL = my_callsign 表示本台是接收方，这是接收记录
        is_receiver = (call == clean_my_callsign)
        # OPERATOR = my_callsign 表示本台是发送方，这是发送记录
        is_sender = (operator == clean_my_callsign)
        
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
        
        # 解析频率
        freq = rec.get("FREQ", "0")
        try:
            freq_hz = int(float(freq) * 1000000)
        except ValueError:
            freq_hz = 0
        
        # 解析 SNR
        snr = rec.get("APP_PSKREP_SNR", "")
        
        # 根据记录类型正确映射字段
        if is_receiver:
            # 接收记录：对方(OPERATOR)发送，本台(CALL)接收
            # MY_GRIDSQUARE = 对方定位，GRIDSQUARE = 本台定位
            record = {
                "senderCallsign": operator,
                "receiverCallsign": call,
                "senderLocator": rec.get("MY_GRIDSQUARE", ""),
                "receiverLocator": rec.get("GRIDSQUARE", ""),
                "frequency": freq_hz,
                "sNR": snr,
                "mode": rec.get("MODE", ""),
                "flowStartSeconds": int(timestamp.timestamp()) if timestamp else 0,
                "is_sender": False,
                "is_receiver": True,
                "distance": rec.get("DISTANCE", ""),
                "bearing": rec.get("APP_PSKREP_BRG", ""),
                "country": self._get_country_from_callsign(operator),
                "dxcc": adif_dxcc,
            }
        elif is_sender:
            # 发送记录：本台(OPERATOR)发送，对方(CALL)接收
            # MY_GRIDSQUARE = 本台定位，GRIDSQUARE = 对方定位
            record = {
                "senderCallsign": operator,
                "receiverCallsign": call,
                "senderLocator": rec.get("MY_GRIDSQUARE", ""),
                "receiverLocator": rec.get("GRIDSQUARE", ""),
                "frequency": freq_hz,
                "sNR": snr,
                "mode": rec.get("MODE", ""),
                "flowStartSeconds": int(timestamp.timestamp()) if timestamp else 0,
                "is_sender": True,
                "is_receiver": False,
                "distance": rec.get("DISTANCE", ""),
                "bearing": rec.get("APP_PSKREP_BRG", ""),
                "country": self._get_country_from_callsign(call),
                "dxcc": adif_dxcc,
            }
        else:
            # 未知类型，跳过
            return None
        
        return record
    
    def _get_country_from_callsign(self, callsign: str) -> str:
        """
        根据呼号前缀推断国家
        
        委托给 dxcc_lookup 模块，该模块包含完整的 ARRL DXCC 实体映射。
        
        Args:
            callsign: 业余无线电呼号
        
        Returns:
            DXCC 实体名称，或空字符串
        """
        if not callsign:
            return ""
        
        result = lookup_callsign(callsign)
        return result["name"] if result else ""
    
    def _generate_adif_field(self, name: str, value: Any) -> str:
        """
        生成 ADIF 格式的字段
        
        Args:
            name: 字段名
            value: 字段值
        
        Returns:
            ADIF 格式的字段字符串
        """
        if value is None:
            return ""
        value_str = str(value)
        return f"<{name.upper()}:{len(value_str)}>{value_str}"
    
    def _record_to_adif(self, record: Dict[str, Any], is_sender: bool) -> str:
        """
        将记录转换为 ADIF 格式
        
        Args:
            record: 记录字典
            is_sender: 是否为发送记录
        
        Returns:
            ADIF 格式的记录字符串
        """
        fields = []
        
        # 日期时间
        if record.get("flowStartSeconds"):
            try:
                ts = datetime.datetime.fromtimestamp(record["flowStartSeconds"])
                fields.append(self._generate_adif_field("QSO_DATE", ts.strftime("%Y%m%d")))
                fields.append(self._generate_adif_field("TIME_ON", ts.strftime("%H%M%S")))
            except:
                pass
        
        # 呼号
        if is_sender:
            # 本台发射被他人接收
            fields.append(self._generate_adif_field("OPERATOR", record.get("senderCallsign", "")))
            fields.append(self._generate_adif_field("CALL", record.get("receiverCallsign", "")))
            fields.append(self._generate_adif_field("MY_GRIDSQUARE", record.get("senderLocator", "")))
            fields.append(self._generate_adif_field("GRIDSQUARE", record.get("receiverLocator", "")))
        else:
            # 本台接收到他人信号
            fields.append(self._generate_adif_field("OPERATOR", record.get("receiverCallsign", "")))
            fields.append(self._generate_adif_field("CALL", record.get("senderCallsign", "")))
            fields.append(self._generate_adif_field("MY_GRIDSQUARE", record.get("receiverLocator", "")))
            fields.append(self._generate_adif_field("GRIDSQUARE", record.get("senderLocator", "")))
        
        # 频率 (Hz -> MHz)
        if record.get("frequency"):
            freq_mhz = record["frequency"] / 1000000
            fields.append(self._generate_adif_field("FREQ", f"{freq_mhz:.6f}"))
        
        # 模式
        fields.append(self._generate_adif_field("MODE", record.get("mode", "")))
        
        # SNR
        fields.append(self._generate_adif_field("APP_PSKREP_SNR", record.get("sNR", "")))
        
        # 其他字段
        if record.get("distance"):
            fields.append(self._generate_adif_field("DISTANCE", record["distance"]))
        if record.get("bearing"):
            fields.append(self._generate_adif_field("APP_PSKREP_BRG", record["bearing"]))
        if record.get("country"):
            fields.append(self._generate_adif_field("COUNTRY", record["country"]))
        if record.get("dxcc"):
            fields.append(self._generate_adif_field("DXCC", record["dxcc"]))
        
        # 记录类型标记
        fields.append(self._generate_adif_field("APP_PSKREP_TYPE", "SENDER" if is_sender else "RECEIVER"))
        
        return "".join(fields) + "<EOR>"
    
    def save_log(self,
                 callsign: str,
                 records: List[Dict[str, Any]],
                 date: Optional[datetime.date] = None) -> str:
        """
        保存日志到 ADIF 文件
        
        Args:
            callsign: 呼号
            records: 记录列表
            date: 日期（默认今天）
        
        Returns:
            保存的文件路径
        """
        if date is None:
            date = datetime.date.today()
        
        # 创建按呼号分类的子目录
        callsign_dir = os.path.join(self.log_dir, callsign.upper())
        if not os.path.exists(callsign_dir):
            os.makedirs(callsign_dir)
        
        # 文件名使用日期和时间戳
        now = datetime.datetime.now()
        filename = f"{date.strftime('%Y-%m-%d')}_{now.strftime('%H%M%S')}.adi"
        filepath = os.path.join(callsign_dir, filename)
        
        # 分离发送和接收记录
        sender_records = [r for r in records if r.get("is_sender")]
        receiver_records = [r for r in records if r.get("is_receiver")]
        
        # 生成 ADIF 文件内容
        adif_content = []
        
        # ADIF 头部
        adif_content.append("# PSKReporter ADIF Export")
        adif_content.append(f"# Callsign: {callsign.upper()}")
        adif_content.append(f"# Date: {date.isoformat()}")
        adif_content.append(f"# Fetch Time: {now.isoformat()}")
        adif_content.append(f"# Sender Records: {len(sender_records)}")
        adif_content.append(f"# Receiver Records: {len(receiver_records)}")
        adif_content.append("")
        adif_content.append("<ADIF_VER:5>3.1.0")
        adif_content.append("<PROGRAMID:15>PSKReporterADIF")
        adif_content.append("<PROGRAMVERSION:3>1.0")
        adif_content.append("<EOH>")
        adif_content.append("")
        
        # 发送记录
        if sender_records:
            adif_content.append("# Sender Records (Your transmissions received by others)")
            for record in sender_records:
                adif_content.append(self._record_to_adif(record, is_sender=True))
            adif_content.append("")
        
        # 接收记录
        if receiver_records:
            adif_content.append("# Receiver Records (Signals you received from others)")
            for record in receiver_records:
                adif_content.append(self._record_to_adif(record, is_sender=False))
        
        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(adif_content))
        
        return filepath
    
    def print_summary(self, records: List[Dict[str, Any]]) -> None:
        """打印记录摘要"""
        sender_records = [r for r in records if r.get("is_sender")]
        receiver_records = [r for r in records if r.get("is_receiver")]
        
        print(f"\n{'='*70}")
        print(f"获取时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"数据来源: ADIF 接口 (完整历史数据)")
        print(f"{'='*70}")
        
        # 发送方记录
        if sender_records:
            print(f"\n【发射被他人接收】({len(sender_records)} 条记录):")
            print("-" * 70)
            print(f"{'接收方':<12} {'接收方定位':<12} {'频率':<14} {'模式':<6} {'SNR':>5} {'时间'}")
            print("-" * 70)
            for record in sorted(sender_records, key=lambda x: x.get("flowStartSeconds", 0), reverse=True)[:20]:
                freq_khz = record["frequency"] / 1000
                try:
                    timestamp = datetime.datetime.fromtimestamp(record["flowStartSeconds"]).strftime('%m-%d %H:%M')
                except:
                    timestamp = "N/A"
                print(f"{record['receiverCallsign']:<12} {record['receiverLocator']:<12} "
                      f"{freq_khz:>10.2f} kHz {record['mode']:<6} {record['sNR']:>5} {timestamp}")
            if len(sender_records) > 20:
                print(f"  ... 还有 {len(sender_records) - 20} 条记录")
        else:
            print("\n【发射被他人接收】: 无记录")
        
        # 接收方记录
        if receiver_records:
            print(f"\n【接收到他人的信号】({len(receiver_records)} 条记录):")
            print("-" * 70)
            print(f"{'发送方':<12} {'发送方定位':<12} {'频率':<14} {'模式':<6} {'SNR':>5} {'时间'}")
            print("-" * 70)
            for record in sorted(receiver_records, key=lambda x: x.get("flowStartSeconds", 0), reverse=True)[:20]:
                freq_khz = record["frequency"] / 1000
                try:
                    timestamp = datetime.datetime.fromtimestamp(record["flowStartSeconds"]).strftime('%m-%d %H:%M')
                except:
                    timestamp = "N/A"
                print(f"{record['senderCallsign']:<12} {record['senderLocator']:<12} "
                      f"{freq_khz:>10.2f} kHz {record['mode']:<6} {record['sNR']:>5} {timestamp}")
            if len(receiver_records) > 20:
                print(f"  ... 还有 {len(receiver_records) - 20} 条记录")
        else:
            print("\n【接收到他人的信号】: 无记录")
        
        print(f"\n{'='*70}\n")


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    default_config = {
        "callsign": "BG1SB",
        "log_dir": "logs",
        "days": 1,
        "database": {
            "host": "ham.vlsc.net",
            "port": 9030,
            "user": "root",
            "password": "",
            "name": "pskreporter"
        }
    }
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except (json.JSONDecodeError, IOError) as e:
            print(f"配置文件读取错误，使用默认配置: {e}")
    
    return default_config


def main():
    """主函数"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    config = load_config(config_path)
    
    parser = argparse.ArgumentParser(
        description="PSKReporter ADIF 数据获取器 - 获取完整的历史传播记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 使用默认配置运行
  %(prog)s --callsign BG1SB          # 指定呼号
  %(prog)s --days 2                  # 获取过去 2 天的数据
  %(prog)s --sender-only             # 只获取发射被接收的记录
  %(prog)s --receiver-only           # 只获取接收到他人的记录
  %(prog)s --no-db                   # 不保存到数据库

数据采集原则（遵循 PSK Reporter API 规范）：
  - 查询间隔 >= 5 分钟（API 要求）
  - 添加随机抖动，避免整点同步
  - 建议在 config.json 中配置 appcontact 参数

注意:
  此脚本使用 ADIF 接口，可获取完整的历史数据（最多多天）。
  与实时查询接口相比，数据更完整，适合用于历史数据存档。
        """
    )
    
    parser.add_argument(
        "--callsign",
        default=config["callsign"],
        help=f"要查询的呼号（默认: {config['callsign']}）"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="获取过去几天的数据（默认: 1）"
    )
    parser.add_argument(
        "--log-dir",
        default=config["log_dir"],
        help=f"日志保存目录（默认: {config['log_dir']}）"
    )
    parser.add_argument(
        "--sender-only",
        action="store_true",
        help="只获取作为发送方被接收的记录"
    )
    parser.add_argument(
        "--receiver-only",
        action="store_true",
        help="只获取作为接收方接收他人的记录"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="静默模式，不打印摘要"
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="不保存到数据库（仅保存 ADIF 文件）"
    )
    parser.add_argument(
        "--appcontact",
        default=config.get("appcontact", ""),
        help="联系方式（PSK Reporter API 推荐填写）"
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
        help=f"数据库端口（默认: {config['database']['port']}，StarRocks）"
    )
    parser.add_argument(
        "--db-user",
        default=config["database"]["user"],
        help=f"数据库用户名（默认: {config['database']['user']}）"
    )
    parser.add_argument(
        "--db-password",
        default=config["database"]["password"],
        help="数据库密码（默认: 空）"
    )
    parser.add_argument(
        "--db-name",
        default=config["database"]["name"],
        help=f"数据库名（默认: {config['database']['name']}）"
    )
    
    args = parser.parse_args()
    
    # 初始化获取器（带 appcontact 参数）
    fetcher = PSKReporterADIF(
        log_dir=args.log_dir,
        callsign=args.callsign,
        appcontact=args.appcontact
    )
    
    # 连接数据库
    if not args.no_db:
        print(f"\n连接数据库 {args.db_host}:{args.db_port}...")
        if fetcher.connect_db(
            host=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
            database=args.db_name
        ):
            print("数据库连接成功")
        else:
            print("数据库连接失败，将只保存 ADIF 文件")
    
    print(f"\n正在获取 {args.callsign.upper()} 的 ADIF 数据...")
    print(f"时间范围: 过去 {args.days} 天")
    print(f"日志目录: {args.log_dir}")
    if args.appcontact:
        print(f"联系方式: {args.appcontact}")
    
    # 获取数据
    records = fetcher.fetch(
        args.callsign,
        days=args.days,
        sender_only=args.sender_only,
        receiver_only=args.receiver_only
    )
    
    print(f"获取到 {len(records)} 条记录")
    
    # 打印摘要
    if not args.quiet:
        fetcher.print_summary(records)
    
    # 保存 ADIF 文件
    filepath = None
    if records:
        filepath = fetcher.save_log(args.callsign, records)
        print(f"ADIF 文件已保存到: {filepath}")
    
    # 保存到数据库
    if records and not args.no_db and fetcher.db_manager:
        print("\n正在保存到数据库...")
        sender_inserted, receiver_inserted = fetcher.save_to_db(records, args.callsign, filepath)
        print(f"数据库插入: {sender_inserted} 条发送记录, {receiver_inserted} 条接收记录")
    
    # 断开数据库连接
    fetcher.disconnect_db()
    
    # 统计
    sender_count = len([r for r in records if r.get("is_sender")])
    receiver_count = len([r for r in records if r.get("is_receiver")])
    print(f"\n总计: {sender_count} 条发送记录, {receiver_count} 条接收记录")


if __name__ == "__main__":
    main()
