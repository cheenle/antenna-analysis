#!/usr/bin/env python3
"""
psk_hdf5 预聚合汇总表 — 一次性脚本

将 psk_hdf5（55.6 亿行）按 (day, hour, band, mode, country) 预聚合，
生成汇总表 psk_hdf5_summary（预计几万~几十万行）。

之后 /api/all/* 端点查 2025 年数据时直接读汇总表，毫秒级返回。

用法:
    python3 create_psk_hdf5_summary.py          # 全量聚合
    python3 create_psk_hdf5_summary.py --dry-run # 预估行数不写入
    python3 create_psk_hdf5_summary.py --partition 202501  # 只处理一个分区
"""

import mysql.connector
from mysql.connector import Error as MySQLError
import time
import sys
import argparse

# ── 数据库配置 ──
DB_CONFIG = {
    "host": "ham.vlsc.net",
    "port": 9030,
    "user": "root",
    "password": "",
    "database": "pskreporter",
    "charset": "utf8mb4",
    "connect_timeout": 30,
    "connection_timeout": 30,
}

SRC_TABLE = "psk_hdf5"
SUMMARY_TABLE = "psk_hdf5_summary"

# ── 波段 CASE SQL（与 band_utils.py 保持一致）──
BAND_RANGES = [
    (1_800_000, 2_000_000, "160m"),
    (3_500_000, 4_000_000, "80m"),
    (5_330_000, 5_405_000, "60m"),
    (7_000_000, 7_300_000, "40m"),
    (10_100_000, 10_150_000, "30m"),
    (14_000_000, 14_350_000, "20m"),
    (18_068_000, 18_168_000, "17m"),
    (21_000_000, 21_450_000, "15m"),
    (24_890_000, 24_990_000, "12m"),
    (28_000_000, 29_700_000, "10m"),
    (50_000_000, 54_000_000, "6m"),
    (144_000_000, 148_000_000, "2m"),
]

CASE_BAND_SQL = (
    "CASE\n"
    + "\n".join(
        f"        WHEN frequency BETWEEN {low} AND {high} THEN '{name}'"
        for low, high, name in BAND_RANGES
    )
    + "\n        ELSE 'Other'\n    END"
)

# ── 建表 SQL ──
CREATE_SUMMARY_SQL = f"""
CREATE TABLE IF NOT EXISTS {SUMMARY_TABLE} (
    day DATE NOT NULL,
    hour TINYINT NOT NULL,
    band VARCHAR(20) NOT NULL,
    mode VARCHAR(20) NOT NULL,
    sender_country VARCHAR(50) NOT NULL,
    spot_count BIGINT
)
DUPLICATE KEY(day, hour, band, mode, sender_country)
PARTITION BY RANGE(day) (
    PARTITION p202501 VALUES [("2025-01-01"), ("2025-02-01")),
    PARTITION p202502 VALUES [("2025-02-01"), ("2025-03-01")),
    PARTITION p202503 VALUES [("2025-03-01"), ("2025-04-01")),
    PARTITION p202504 VALUES [("2025-04-01"), ("2025-05-01")),
    PARTITION p202505 VALUES [("2025-05-01"), ("2025-06-01"))
)
DISTRIBUTED BY HASH(day) BUCKETS 8
PROPERTIES (
    "replication_num" = "1",
    "compression" = "LZ4"
);
"""

# ── 分区列表（2025 年数据分区）──
PARTITIONS_2025 = ["p202501", "p202502", "p202503", "p202504", "p202505"]


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def create_summary_table(cursor):
    """创建汇总表"""
    print(f"[1/3] 创建汇总表 {SUMMARY_TABLE} ...")
    cursor.execute(f"DROP TABLE IF EXISTS {SUMMARY_TABLE}")
    cursor.execute(CREATE_SUMMARY_SQL)
    print(f"      表已创建")


def estimate_rows(cursor):
    """估算分区行数"""
    for p in PARTITIONS_2025:
        cursor.execute(f"SELECT COUNT(*) FROM {SRC_TABLE} PARTITION({p})")
        cnt = cursor.fetchone()[0]
        print(f"      分区 {p}: {cnt:,} 行")


def aggregate_partition(cursor, conn, partition_name):
    """聚合单个分区"""
    sql = f"""
    INSERT INTO {SUMMARY_TABLE} (day, hour, band, mode, sender_country, spot_count)
    SELECT
        DATE(qso_time) as day,
        HOUR(qso_time) as hour,
        {CASE_BAND_SQL} as band,
        COALESCE(NULLIF(mode, ''), 'Unknown') as mode,
        COALESCE(NULLIF(country, ''), 'Unknown') as sender_country,
        COUNT(*) as spot_count
    FROM {SRC_TABLE} PARTITION({partition_name})
    WHERE frequency IS NOT NULL
    GROUP BY day, hour, band, mode, sender_country;
    """
    start = time.time()
    cursor.execute(sql)
    conn.commit()
    elapsed = time.time() - start
    print(f"      分区 {partition_name}: {elapsed:.0f}s")


def show_results(cursor):
    """显示汇总结果"""
    cursor.execute(f"SELECT COUNT(*) FROM {SUMMARY_TABLE}")
    row_cnt = cursor.fetchone()[0]
    print(f"  汇总表总行数: {row_cnt:,}")

    cursor.execute(f"SELECT SUM(spot_count) FROM {SUMMARY_TABLE}")
    total_spots = cursor.fetchone()[0]
    print(f"  总 spot 数: {total_spots:,}")

    cursor.execute(f"""
        SELECT MIN(day) as first_day, MAX(day) as last_day
        FROM {SUMMARY_TABLE}
    """)
    row = cursor.fetchone()
    print(f"  日期范围: {row[0]} → {row[1]}")

    cursor.execute(f"""
        SELECT band, SUM(spot_count) as total
        FROM {SUMMARY_TABLE}
        GROUP BY band
        ORDER BY total DESC
        LIMIT 10
    """)
    print("  Top 10 波段:")
    for r in cursor.fetchall():
        print(f"    {r[0]:>6s}: {r[1]:>12,}")

    cursor.execute(f"""
        SELECT mode, SUM(spot_count) as total
        FROM {SUMMARY_TABLE}
        GROUP BY mode
        ORDER BY total DESC
        LIMIT 5
    """)
    print("  Top 5 模式:")
    for r in cursor.fetchall():
        print(f"    {r[0]:>8s}: {r[1]:>12,}")


def main():
    parser = argparse.ArgumentParser(description="psk_hdf5 预聚合")
    parser.add_argument("--dry-run", action="store_true", help="只估算，不写入")
    parser.add_argument("--partition", type=str, help="只处理单个分区，如 p202501")
    args = parser.parse_args()

    print(f"源表: {SRC_TABLE}")
    print(f"目标表: {SUMMARY_TABLE}")
    print()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        create_summary_table(cursor)
        conn.commit()
        print()

        print("[2/3] 估算各分区行数 ...")
        estimate_rows(cursor)
        print()

        if args.dry_run:
            print("[3/3] DRY RUN — 跳过聚合")
            return

        print("[3/3] 逐分区聚合 ...")
        partitions = [args.partition] if args.partition else PARTITIONS_2025
        total_start = time.time()
        for p in partitions:
            aggregate_partition(cursor, conn, p)
        total_elapsed = time.time() - total_start
        print(f"      总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
        print()

        print("=" * 40)
        print("聚合结果:")
        print("=" * 40)
        show_results(cursor)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
