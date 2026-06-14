#!/usr/bin/env python3
"""
PSKReporter Fetcher - 获取并保存指定呼号的接收记录
每天获取与指定呼号相关的记录，按日期保存到本地日志文件

支持配置文件 config.json

数据采集原则（遵循 PSK Reporter API 规范）：
1. 查询频率节制：最小间隔 5 分钟，推荐 10-15 分钟
2. 负载分散：添加随机抖动，避免整点同步
3. 身份标识：User-Agent 包含联系方式
4. 避免重复：使用去重机制，不重复请求相同数据
"""

import argparse
import datetime
import json
import os
import random
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Any


# 默认配置
DEFAULT_CONFIG = {
    "callsign": "BG1SB",
    "log_dir": "logs",
    "hours": 24,
    "modes": [],  # 空列表表示所有模式
    "include_sender_records": True,   # 查询 BG1SB 发射被他人接收的记录
    "include_receiver_records": True,  # 查询 BG1SB 接收他人的记录
    "appcontact": "",  # PSK Reporter API 联系方式（推荐填写）
    "min_query_interval": 300,  # 最小查询间隔（秒），PSK Reporter 要求至少 5 分钟
}

# PSK Reporter API 限制常量
PSKREPORTER_MIN_INTERVAL = 300  # PSK Reporter 要求最小查询间隔 5 分钟
PSKREPORTER_MAX_HOURS = 24  # PSK Reporter API 最大时间范围 24 小时


class PSKReporterFetcher:
    """
    PSKReporter 数据获取器
    
    遵循 PSK Reporter API 规范：
    - 查询间隔 >= 5 分钟
    - 添加随机抖动避免整点同步
    - User-Agent 包含联系方式
    """
    
    BASE_URL = "https://retrieve.pskreporter.info/query"
    
    # 类级别的最后查询时间（用于频率控制）
    _last_query_time = 0
    
    def __init__(self, log_dir: str = "logs", callsign: str = "", appcontact: str = ""):
        """
        初始化获取器
        
        Args:
            log_dir: 日志保存目录
            callsign: 呼号（用于 User-Agent 标识）
            appcontact: 联系方式（PSK Reporter API 推荐）
        """
        self.log_dir = log_dir
        self.callsign = callsign.upper()
        self.appcontact = appcontact
        self._ensure_log_dir()
    
    def _ensure_log_dir(self) -> None:
        """确保日志目录存在"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
    
    def _get_user_agent(self) -> str:
        """
        生成规范化的 User-Agent
        
        格式: PSKReporterFetcher/VERSION (CALLSIGN; contact@email)
        PSK Reporter 官方建议 User-Agent 包含联系方式
        """
        version = "2.1"
        if self.appcontact:
            return f"PSKReporterFetcher/{version} ({self.callsign}; {self.appcontact})"
        elif self.callsign:
            return f"PSKReporterFetcher/{version} ({self.callsign})"
        return f"PSKReporterFetcher/{version}"
    
    def _enforce_rate_limit(self, min_interval: int = PSKREPORTER_MIN_INTERVAL) -> None:
        """
        强制执行查询频率限制
        
        PSK Reporter API 要求：查询间隔不少于 5 分钟
        
        Args:
            min_interval: 最小间隔秒数（默认 300 秒 = 5 分钟）
        """
        now = time.time()
        elapsed = now - PSKReporterFetcher._last_query_time
        
        if elapsed < min_interval:
            # 添加随机抖动（0-60秒），避免整点同步
            jitter = random.randint(0, 60)
            sleep_time = min_interval - elapsed + jitter
            print(f"  频率限制：等待 {int(sleep_time)} 秒后继续...")
            time.sleep(sleep_time)
        
        PSKReporterFetcher._last_query_time = time.time()
    
    def fetch_sender_records(self, 
                              callsign: str,
                              hours: int = 24,
                              mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取作为发送方被接收的记录（查询 senderCallsign）
        即：BG1SB 发射信号，被其他人接收到
        
        Args:
            callsign: 发送方呼号
            hours: 查询过去多少小时的数据（最大24小时）
            mode: 可选的模式过滤
        
        Returns:
            接收记录列表
        """
        # 强制频率限制
        self._enforce_rate_limit()
        
        params = {
            "senderCallsign": callsign.upper(),
            "flowStartSeconds": -hours * 3600,
            "rronly": 1,
        }
        
        if mode:
            params["mode"] = mode
        
        # 添加联系方式（PSK Reporter API 强烈推荐）
        if self.appcontact:
            params["appcontact"] = self.appcontact
        
        return self._fetch(params)
    
    def fetch_receiver_records(self,
                                callsign: str,
                                hours: int = 24,
                                mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取作为接收方接收他人的记录（查询 receiverCallsign）
        即：BG1SB 接收到其他人发射的信号
        
        Args:
            callsign: 接收方呼号
            hours: 查询过去多少小时的数据（最大24小时）
            mode: 可选的模式过滤
        
        Returns:
            接收记录列表
        """
        # 强制频率限制
        self._enforce_rate_limit()
        
        params = {
            "receiverCallsign": callsign.upper(),
            "flowStartSeconds": -hours * 3600,
            "rronly": 1,
        }
        
        if mode:
            params["mode"] = mode
        
        # 添加联系方式（PSK Reporter API 强烈推荐）
        if self.appcontact:
            params["appcontact"] = self.appcontact
        
        return self._fetch(params)
    
    def _fetch(self, params: dict) -> List[Dict[str, Any]]:
        """
        执行查询并返回解析后的记录
        
        Args:
            params: 查询参数
        
        Returns:
            记录列表
        """
        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{query_string}"
        
        try:
            req = urllib.request.Request(url)
            # 使用规范化的 User-Agent（包含联系方式）
            req.add_header("User-Agent", self._get_user_agent())
            
            with urllib.request.urlopen(req, timeout=30) as response:
                xml_data = response.read().decode("utf-8")
                return self._parse_reception_reports(xml_data)
        
        except urllib.error.URLError as e:
            print(f"  网络错误: {e}")
            return []
        except Exception as e:
            print(f"  获取数据时发生错误: {e}")
            return []
    
    def _parse_reception_reports(self, xml_data: str) -> List[Dict[str, Any]]:
        """
        解析 PSKReporter 返回的 XML 数据中的 receptionReport
        
        按照 PSKReporter IPFIX 属性定义解析所有字段
        
        Args:
            xml_data: XML 格式的响应数据
        
        Returns:
            解析后的记录列表
        """
        records = []
        
        try:
            root = ET.fromstring(xml_data)
            
            for report in root.findall(".//receptionReport"):
                record = {
                    # 30351.1 - 发送方呼号
                    "senderCallsign": report.get("senderCallsign", ""),
                    
                    # 30351.2 - 接收方呼号
                    "receiverCallsign": report.get("receiverCallsign", ""),
                    
                    # 30351.3 - 发送方定位符
                    "senderLocator": report.get("senderLocator", ""),
                    
                    # 30351.4 - 接收方定位符
                    "receiverLocator": report.get("receiverLocator", ""),
                    
                    # 30351.5 - 频率 (Hz)
                    "frequency": int(report.get("frequency", 0) or 0),
                    
                    # 30351.6 - 信噪比 (dB)
                    "sNR": report.get("sNR", ""),
                    
                    # 30351.10 - 通信模式 (ADIF MODE/SUBMODE)
                    "mode": report.get("mode", ""),
                    
                    # 150 - 传输时间 (Unix 时间戳)
                    "flowStartSeconds": int(report.get("flowStartSeconds", 0) or 0),
                }
                
                # 可选字段（如果存在则添加）
                # 30351.7 - 互调失真
                if report.get("iMD"):
                    record["iMD"] = report.get("iMD")
                
                # 30351.8 - 解码软件
                if report.get("decoderSoftware"):
                    record["decoderSoftware"] = report.get("decoderSoftware")
                
                # 30351.9 - 天线信息
                if report.get("antennaInformation"):
                    record["antennaInformation"] = report.get("antennaInformation")
                
                # 30351.11 - 信息来源
                if report.get("informationSource"):
                    record["informationSource"] = int(report.get("informationSource"))
                
                # 30351.12 - 持久标识符
                if report.get("persistentIdentifier"):
                    record["persistentIdentifier"] = report.get("persistentIdentifier")
                
                # 30351.13 - 电台信息
                if report.get("rigInformation"):
                    record["rigInformation"] = report.get("rigInformation")
                
                # 30351.14 - 原始消息数据
                if report.get("messageBits"):
                    record["messageBits"] = report.get("messageBits")
                
                # 30351.15 - 时间偏移 (毫秒)
                if report.get("deltaT"):
                    record["deltaT"] = report.get("deltaT")
                
                records.append(record)
        
        except ET.ParseError as e:
            print(f"  XML 解析错误: {e}")
        
        return records
    
    def save_log(self, 
                 callsign: str, 
                 sender_records: List[Dict[str, Any]],
                 receiver_records: List[Dict[str, Any]],
                 date: Optional[datetime.date] = None) -> str:
        """
        保存日志到文件
        
        Args:
            callsign: 呼号
            sender_records: 发送方记录列表（BG1SB发射被他人接收）
            receiver_records: 接收方记录列表（BG1SB接收到他人的信号）
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
        
        # 文件名使用日期
        filename = f"{date.strftime('%Y-%m-%d')}.json"
        filepath = os.path.join(callsign_dir, filename)
        
        # 读取现有数据或创建新数据
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    output = json.load(f)
            except (json.JSONDecodeError, KeyError):
                output = {}
        else:
            output = {}
        
        # 更新元数据
        output["callsign"] = callsign.upper()
        output["date"] = date.isoformat()
        output["fetch_time"] = datetime.datetime.now().isoformat()
        
        # 保存发送方记录
        # sender_records: BG1SB 发射信号，被他人接收
        # 字段含义: senderCallsign=BG1SB, receiverCallsign=接收方
        if "sender_records" not in output:
            output["sender_records"] = []
        
        existing_sender_keys = {
            (r.get("senderCallsign"), r.get("receiverCallsign"), 
             r.get("frequency"), r.get("flowStartSeconds"))
            for r in output["sender_records"]
        }
        
        for record in sender_records:
            key = (record.get("senderCallsign"), record.get("receiverCallsign"),
                   record.get("frequency"), record.get("flowStartSeconds"))
            if key not in existing_sender_keys:
                output["sender_records"].append(record)
                existing_sender_keys.add(key)
        
        # 保存接收方记录
        # receiver_records: 他人发射信号，被 BG1SB 接收
        # 字段含义: senderCallsign=发送方, receiverCallsign=BG1SB
        if "receiver_records" not in output:
            output["receiver_records"] = []
        
        existing_receiver_keys = {
            (r.get("senderCallsign"), r.get("receiverCallsign"), 
             r.get("frequency"), r.get("flowStartSeconds"))
            for r in output["receiver_records"]
        }
        
        for record in receiver_records:
            key = (record.get("senderCallsign"), record.get("receiverCallsign"),
                   record.get("frequency"), record.get("flowStartSeconds"))
            if key not in existing_receiver_keys:
                output["receiver_records"].append(record)
                existing_receiver_keys.add(key)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def print_summary(self, 
                      sender_records: List[Dict[str, Any]], 
                      receiver_records: List[Dict[str, Any]]) -> None:
        """打印记录摘要"""
        print(f"\n{'='*70}")
        print(f"获取时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        
        # 发送方记录（BG1SB 发射，被他人接收）
        if sender_records:
            print(f"\n【BG1SB 发射被他人接收】({len(sender_records)} 条记录):")
            print("-" * 70)
            print(f"{'接收方':<12} {'接收方定位':<12} {'频率':<14} {'模式':<6} {'SNR':>5} {'时间'}")
            print("-" * 70)
            for record in sorted(sender_records, key=lambda x: x.get("flowStartSeconds", 0), reverse=True)[:20]:
                freq_khz = record["frequency"] / 1000
                timestamp = datetime.datetime.fromtimestamp(record["flowStartSeconds"]).strftime('%H:%M:%S')
                print(f"{record['receiverCallsign']:<12} {record['receiverLocator']:<12} "
                      f"{freq_khz:>10.2f} kHz {record['mode']:<6} {record['sNR']:>5} {timestamp}")
            if len(sender_records) > 20:
                print(f"  ... 还有 {len(sender_records) - 20} 条记录")
        else:
            print("\n【BG1SB 发射被他人接收】: 无记录")
        
        # 接收方记录（BG1SB 接收他人的信号）
        if receiver_records:
            print(f"\n【BG1SB 接收到的信号】({len(receiver_records)} 条记录):")
            print("-" * 70)
            print(f"{'发送方':<12} {'发送方定位':<12} {'频率':<14} {'模式':<6} {'SNR':>5} {'时间'}")
            print("-" * 70)
            for record in sorted(receiver_records, key=lambda x: x.get("flowStartSeconds", 0), reverse=True)[:20]:
                freq_khz = record["frequency"] / 1000
                timestamp = datetime.datetime.fromtimestamp(record["flowStartSeconds"]).strftime('%H:%M:%S')
                print(f"{record['senderCallsign']:<12} {record['senderLocator']:<12} "
                      f"{freq_khz:>10.2f} kHz {record['mode']:<6} {record['sNR']:>5} {timestamp}")
            if len(receiver_records) > 20:
                print(f"  ... 还有 {len(receiver_records) - 20} 条记录")
        else:
            print("\n【BG1SB 接收到的信号】: 无记录")
        
        print(f"\n{'='*70}\n")


def load_config(config_path: str) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        配置字典
    """
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                config.update(user_config)
            print(f"已加载配置文件: {config_path}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"配置文件读取错误，使用默认配置: {e}")
    else:
        print(f"配置文件不存在，使用默认配置")
    
    return config


def main():
    """主函数"""
    # 查找配置文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    # 加载配置
    config = load_config(config_path)
    
    # 命令行参数（覆盖配置文件）
    parser = argparse.ArgumentParser(
        description="PSKReporter 接收记录获取器 - 按日期保存指定呼号的记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 使用 config.json 配置运行
  %(prog)s --callsign BG1SB          # 指定呼号
  %(prog)s --hours 12                # 获取过去12小时的记录
  %(prog)s --mode FT8                # 只获取 FT8 模式的记录
  %(prog)s --sender-only             # 只获取发送方记录
  %(prog)s --receiver-only           # 只获取接收方记录

数据采集原则（遵循 PSK Reporter API 规范）：
  - 查询间隔 >= 5 分钟（API 要求）
  - 添加随机抖动，避免整点同步
  - 建议在 config.json 中配置 appcontact 参数

配置文件 (config.json):
  {
    "callsign": "BG1SB",
    "log_dir": "logs",
    "hours": 24,
    "modes": ["FT8", "FT4"],
    "include_sender_records": true,
    "include_receiver_records": true,
    "appcontact": "your-email@example.com"
  }
        """
    )
    
    parser.add_argument(
        "--callsign",
        help=f"要查询的呼号（默认: {config['callsign']}）"
    )
    parser.add_argument(
        "--hours",
        type=int,
        help=f"查询过去多少小时的数据（默认: {config['hours']}，最大24）"
    )
    parser.add_argument(
        "--mode",
        help="过滤特定模式（如 FT8, PSK31, FT4 等）"
    )
    parser.add_argument(
        "--log-dir",
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
        "--config",
        default=config_path,
        help=f"配置文件路径（默认: {config_path}）"
    )
    parser.add_argument(
        "--appcontact",
        help="联系方式（PSK Reporter API 推荐填写，用于问题通知）"
    )
    parser.add_argument(
        "--no-rate-limit",
        action="store_true",
        help="禁用频率限制检查（不推荐，可能导致 API 封禁）"
    )
    
    args = parser.parse_args()
    
    # 合并配置（命令行参数优先）
    callsign = args.callsign or config["callsign"]
    hours = min(args.hours or config["hours"], PSKREPORTER_MAX_HOURS)
    log_dir = args.log_dir or config["log_dir"]
    modes = args.mode.split(",") if args.mode else config.get("modes", [])
    appcontact = args.appcontact or config.get("appcontact", "")
    
    # 确定要获取的记录类型
    include_sender = config.get("include_sender_records", True)
    include_receiver = config.get("include_receiver_records", True)
    
    if args.sender_only:
        include_sender = True
        include_receiver = False
    elif args.receiver_only:
        include_sender = False
        include_receiver = True
    
    # 初始化获取器
    fetcher = PSKReporterFetcher(
        log_dir=log_dir,
        callsign=callsign,
        appcontact=appcontact
    )
    
    print(f"\n正在获取 {callsign.upper()} 的记录...")
    print(f"时间范围: 过去 {hours} 小时")
    print(f"日志目录: {log_dir}")
    if appcontact:
        print(f"联系方式: {appcontact}")
    
    sender_records = []
    receiver_records = []
    
    # 获取发送方记录（BG1SB 发射被他人接收）
    if include_sender:
        print(f"\n[1/2] 查询 {callsign.upper()} 发射被他人接收的记录...")
        if modes:
            for mode in modes:
                print(f"  模式: {mode}")
                records = fetcher.fetch_sender_records(callsign, hours=hours, mode=mode.strip())
                sender_records.extend(records)
        else:
            records = fetcher.fetch_sender_records(callsign, hours=hours)
            sender_records.extend(records)
        print(f"  获取到 {len(sender_records)} 条记录")
    
    # 获取接收方记录（BG1SB 接收他人的信号）
    if include_receiver:
        print(f"\n[2/2] 查询 {callsign.upper()} 接收到的信号...")
        if modes:
            for mode in modes:
                print(f"  模式: {mode}")
                records = fetcher.fetch_receiver_records(callsign, hours=hours, mode=mode.strip())
                receiver_records.extend(records)
        else:
            records = fetcher.fetch_receiver_records(callsign, hours=hours)
            receiver_records.extend(records)
        print(f"  获取到 {len(receiver_records)} 条记录")
    
    # 打印摘要
    if not args.quiet:
        fetcher.print_summary(sender_records, receiver_records)
    
    # 保存日志
    if sender_records or receiver_records:
        filepath = fetcher.save_log(callsign, sender_records, receiver_records)
        print(f"日志已保存到: {filepath}")
    
    print(f"\n总计: {len(sender_records)} 条发送记录, {len(receiver_records)} 条接收记录")


if __name__ == "__main__":
    main()