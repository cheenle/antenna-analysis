#!/usr/bin/env python3
"""
多进程并行导入 ADIF 文件到数据库
用法: python3 parallel_import.py [进程数]
"""

import os
import sys
import glob
import time
import random
import datetime
import re
import mysql.connector
from mysql.connector import Error as MySQLError
from multiprocessing import Pool, cpu_count, Manager

# 数据库配置
DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter",
    "charset": "utf8mb4"
}

def parse_adif_file(filepath):
    """解析 ADIF 文件"""
    records = []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        return [], f"读取文件失败: {e}"
    
    # 跳过头部到 <EOH>
    eoh_pos = content.upper().find('<EOH>')
    if eoh_pos >= 0:
        content = content[eoh_pos + 5:]
    
    # 解析记录 - 改进的解析逻辑
    # ADIF 格式: <FIELD:LENGTH>VALUE<FIELD:LENGTH>VALUE...<EOR>
    i = 0
    current_rec = {}
    
    while i < len(content):
        # 查找字段开始
        if content[i] == '<':
            # 查找字段结束 >
            end = content.find('>', i)
            if end == -1:
                break
            
            # 解析字段名和长度
            field_spec = content[i+1:end]
            if ':' in field_spec:
                parts = field_spec.split(':')
                field_name = parts[0].upper()
                try:
                    field_len = int(parts[1])
                except:
                    field_len = 0
            else:
                field_name = field_spec.upper()
                field_len = 0
            
            if field_name == 'EOR':
                # 记录结束，保存
                if current_rec:
                    qso_date = current_rec.get('QSO_DATE', '')
                    time_on = current_rec.get('TIME_ON', '')
                    if qso_date and time_on and len(qso_date) == 8:
                        try:
                            timestamp = datetime.datetime.strptime(
                                f"{qso_date} {time_on.zfill(6)}", "%Y%m%d %H%M%S"
                            )
                            current_rec['_timestamp'] = timestamp
                            records.append(current_rec.copy())
                        except:
                            pass
                current_rec = {}
                i = end + 1
            else:
                # 读取字段值
                i = end + 1
                if field_len > 0:
                    value = content[i:i+field_len]
                    current_rec[field_name] = value
                    i += field_len
        else:
            i += 1
    
    return records, None

def insert_batch(records, batch_size=5000):
    """批量插入记录 - 使用大批量减少 StarRocks 版本压力"""
    if not records:
        return 0, None
    
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        sql = """
        INSERT INTO all_records 
        (id, sender_callsign, receiver_callsign, frequency, qso_time, 
         sender_locator, receiver_locator, snr, mode, sender_country, sender_dxcc, fetch_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        now = datetime.datetime.now()
        base_id = int(now.timestamp() * 1000000)
        
        # 准备所有数据
        values = []
        for i, rec in enumerate(records):
            snr_val = None
            try:
                snr_str = rec.get('APP_PSKREP_SNR', '')
                if snr_str:
                    snr_val = int(snr_str)
            except:
                pass
            
            freq = 0
            try:
                freq = int(float(rec.get('FREQ', 0)) * 1000000)
            except:
                pass
            
            record_id = base_id * 10000 + i + random.randint(0, 9999)
            
            values.append((
                record_id,
                rec.get('CALL', '')[:20],
                rec.get('OPERATOR', '')[:20],
                freq,
                rec.get('_timestamp'),
                (rec.get('GRIDSQUARE') or '')[:10] or None,
                (rec.get('MY_GRIDSQUARE') or '')[:10] or None,
                snr_val,
                (rec.get('MODE') or '')[:20] or None,
                (rec.get('COUNTRY') or '')[:50] or None,
                (rec.get('APP_PSKREP_DXCC') or '')[:10] or None,
                now
            ))
        
        # 一次性插入所有数据（单批次大容量）
        try:
            cursor.executemany(sql, values)
            conn.commit()
            cursor.close()
            conn.close()
            return len(values), None
        except MySQLError as e:
            # 如果大批量失败，尝试中等批量
            cursor.close()
            conn.close()
            
            # 重新连接，用小一点的批次
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            total_inserted = 0
            
            smaller_batch = 2000
            for i in range(0, len(values), smaller_batch):
                batch = values[i:i + smaller_batch]
                try:
                    cursor.executemany(sql, batch)
                    conn.commit()
                    total_inserted += len(batch)
                    time.sleep(0.1)  # 添加小延迟
                except MySQLError as e2:
                    print(f"    批次插入失败: {e2}")
            
            cursor.close()
            conn.close()
            return total_inserted, None
        
    except Exception as e:
        return 0, str(e)

def process_file(args):
    """处理单个文件 (用于多进程)"""
    filepath, file_index, total_files = args
    
    records, parse_error = parse_adif_file(filepath)
    if parse_error:
        return (filepath, 0, 0, parse_error)
    
    if not records:
        return (filepath, 0, 0, "无有效记录")
    
    inserted, insert_error = insert_batch(records)
    
    return (filepath, len(records), inserted, insert_error)

def main():
    files = sorted(glob.glob("logs/ALL/*.adi"))
    print(f"找到 {len(files)} 个 ADIF 文件")
    print(f"使用单进程批量导入（避免 StarRocks 版本限制）...")
    print("-" * 60)
    
    # 先收集所有记录
    print("正在解析所有文件...")
    all_records = []
    parse_errors = []
    
    for i, filepath in enumerate(files):
        records, error = parse_adif_file(filepath)
        if records:
            all_records.extend(records)
        if error:
            parse_errors.append((os.path.basename(filepath), error))
        
        if (i + 1) % 500 == 0:
            print(f"  已解析 {i+1}/{len(files)} 文件, 累计 {len(all_records)} 条记录")
    
    print(f"解析完成: 共 {len(all_records)} 条记录")
    if parse_errors:
        print(f"解析错误: {len(parse_errors)} 个文件")
    
    print("-" * 60)
    print("开始批量插入数据库...")
    
    start_time = time.time()
    total_inserted, insert_error = insert_batch(all_records)
    elapsed = time.time() - start_time
    
    print("-" * 60)
    print(f"导入完成!")
    print(f"  总记录数: {len(all_records):,}")
    print(f"  成功插入: {total_inserted:,}")
    print(f"  耗时: {elapsed:.1f} 秒")
    print(f"  平均速度: {total_inserted/elapsed:.0f} 条/秒")
    
    if insert_error:
        print(f"\n插入错误: {insert_error}")

if __name__ == "__main__":
    main()