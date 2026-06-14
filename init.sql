-- PSK Reporter 数据库初始化脚本 (StarRocks 版本)
-- StarRocks 兼容 MySQL 协议，但语法有一些差异

-- 创建数据库
CREATE DATABASE IF NOT EXISTS pskreporter;

USE pskreporter;

-- 发送记录表（本台发射被他人接收）
-- 使用 DUPLICATE KEY 模型，适合数据分析场景
CREATE TABLE IF NOT EXISTS sender_records (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    sender_callsign VARCHAR(20) NOT NULL COMMENT '发送方呼号',
    receiver_callsign VARCHAR(20) NOT NULL COMMENT '接收方呼号',
    sender_locator VARCHAR(10) DEFAULT NULL COMMENT '发送方网格定位',
    receiver_locator VARCHAR(10) DEFAULT NULL COMMENT '接收方网格定位',
    frequency INT DEFAULT NULL COMMENT '频率 (Hz)',
    snr INT DEFAULT NULL COMMENT '信噪比 (dB)',
    mode VARCHAR(20) DEFAULT NULL COMMENT '通信模式',
    qso_time DATETIME NOT NULL COMMENT '通信时间',
    distance DECIMAL(10,1) DEFAULT NULL COMMENT '距离 (km)',
    bearing DECIMAL(5,1) DEFAULT NULL COMMENT '方位角',
    country VARCHAR(50) DEFAULT NULL COMMENT '国家',
    dxcc VARCHAR(10) DEFAULT NULL COMMENT 'DXCC 编号',
    fetch_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '数据获取时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=OLAP
DUPLICATE KEY(id)
PARTITION BY RANGE(qso_time) (
    PARTITION p202601 VALUES LESS THAN ('2026-02-01'),
    PARTITION p202602 VALUES LESS THAN ('2026-03-01'),
    PARTITION p202603 VALUES LESS THAN ('2026-04-01'),
    PARTITION p202604 VALUES LESS THAN ('2026-05-01'),
    PARTITION p202605 VALUES LESS THAN ('2026-06-01'),
    PARTITION p202606 VALUES LESS THAN ('2026-07-01'),
    PARTITION p202607 VALUES LESS THAN ('2026-08-01'),
    PARTITION p202608 VALUES LESS THAN ('2026-09-01'),
    PARTITION p202609 VALUES LESS THAN ('2026-10-01'),
    PARTITION p202610 VALUES LESS THAN ('2026-11-01'),
    PARTITION p202611 VALUES LESS THAN ('2026-12-01'),
    PARTITION p202612 VALUES LESS THAN ('2027-01-01'),
    PARTITION p2027 VALUES LESS THAN ('2028-01-01')
)
DISTRIBUTED BY HASH(sender_callsign) BUCKETS 10
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-12",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "dynamic_partition.buckets" = "10",
    "compression" = "LZ4"
);

-- 创建索引
CREATE INDEX idx_sender_callsign ON sender_records(sender_callsign);
CREATE INDEX idx_receiver_callsign ON sender_records(receiver_callsign);
CREATE INDEX idx_mode ON sender_records(mode);
CREATE INDEX idx_frequency ON sender_records(frequency);

-- 接收记录表（本台接收到他人信号）
CREATE TABLE IF NOT EXISTS receiver_records (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    sender_callsign VARCHAR(20) NOT NULL COMMENT '发送方呼号',
    receiver_callsign VARCHAR(20) NOT NULL COMMENT '接收方呼号',
    sender_locator VARCHAR(10) DEFAULT NULL COMMENT '发送方网格定位',
    receiver_locator VARCHAR(10) DEFAULT NULL COMMENT '接收方网格定位',
    frequency INT DEFAULT NULL COMMENT '频率 (Hz)',
    snr INT DEFAULT NULL COMMENT '信噪比 (dB)',
    mode VARCHAR(20) DEFAULT NULL COMMENT '通信模式',
    qso_time DATETIME NOT NULL COMMENT '通信时间',
    distance DECIMAL(10,1) DEFAULT NULL COMMENT '距离 (km)',
    bearing DECIMAL(5,1) DEFAULT NULL COMMENT '方位角',
    country VARCHAR(50) DEFAULT NULL COMMENT '国家',
    dxcc VARCHAR(10) DEFAULT NULL COMMENT 'DXCC 编号',
    fetch_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '数据获取时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=OLAP
DUPLICATE KEY(id)
PARTITION BY RANGE(qso_time) (
    PARTITION p202601 VALUES LESS THAN ('2026-02-01'),
    PARTITION p202602 VALUES LESS THAN ('2026-03-01'),
    PARTITION p202603 VALUES LESS THAN ('2026-04-01'),
    PARTITION p202604 VALUES LESS THAN ('2026-05-01'),
    PARTITION p202605 VALUES LESS THAN ('2026-06-01'),
    PARTITION p202606 VALUES LESS THAN ('2026-07-01'),
    PARTITION p202607 VALUES LESS THAN ('2026-08-01'),
    PARTITION p202608 VALUES LESS THAN ('2026-09-01'),
    PARTITION p202609 VALUES LESS THAN ('2026-10-01'),
    PARTITION p202610 VALUES LESS THAN ('2026-11-01'),
    PARTITION p202611 VALUES LESS THAN ('2026-12-01'),
    PARTITION p202612 VALUES LESS THAN ('2027-01-01'),
    PARTITION p2027 VALUES LESS THAN ('2028-01-01')
)
DISTRIBUTED BY HASH(receiver_callsign) BUCKETS 10
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-12",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "dynamic_partition.buckets" = "10",
    "compression" = "LZ4"
);

-- 创建索引
CREATE INDEX idx_sender_callsign ON receiver_records(sender_callsign);
CREATE INDEX idx_receiver_callsign ON receiver_records(receiver_callsign);
CREATE INDEX idx_mode ON receiver_records(mode);
CREATE INDEX idx_frequency ON receiver_records(frequency);

-- 数据获取日志表
CREATE TABLE IF NOT EXISTS fetch_log (
    id INT AUTO_INCREMENT COMMENT '主键',
    callsign VARCHAR(20) NOT NULL COMMENT '呼号',
    fetch_time DATETIME NOT NULL COMMENT '获取时间',
    sender_count INT DEFAULT 0 COMMENT '发送记录数',
    receiver_count INT DEFAULT 0 COMMENT '接收记录数',
    source VARCHAR(20) DEFAULT 'ADIF' COMMENT '数据来源',
    adif_file VARCHAR(255) DEFAULT NULL COMMENT 'ADIF 文件路径',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(callsign) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "compression" = "LZ4"
);

-- ============================================================
-- 物化视图（StarRocks 4.0 异步物化视图，自动刷新）
-- 覆盖 12 个业余波段（160m-2m），band 定义与 band_utils.py 一致
-- 星号标注的维度为 callsign，支持按呼号查询自动改写
-- ============================================================

-- ── 传播统计（发送方向）- 每小时 ──────────────────────────
CREATE MATERIALIZED VIEW propagation_sender_hourly_mv
DISTRIBUTED BY HASH(hour) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('hour', qso_time) as hour,
    sender_callsign,
    mode,
    CASE
        WHEN frequency BETWEEN 1800000 AND 2000000 THEN '160m'
        WHEN frequency BETWEEN 3500000 AND 4000000 THEN '80m'
        WHEN frequency BETWEEN 5330000 AND 5405000 THEN '60m'
        WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m'
        WHEN frequency BETWEEN 10100000 AND 10150000 THEN '30m'
        WHEN frequency BETWEEN 14000000 AND 14350000 THEN '20m'
        WHEN frequency BETWEEN 18068000 AND 18168000 THEN '17m'
        WHEN frequency BETWEEN 21000000 AND 21450000 THEN '15m'
        WHEN frequency BETWEEN 24890000 AND 24990000 THEN '12m'
        WHEN frequency BETWEEN 28000000 AND 29700000 THEN '10m'
        WHEN frequency BETWEEN 50000000 AND 54000000 THEN '6m'
        WHEN frequency BETWEEN 144000000 AND 148000000 THEN '2m'
        ELSE 'Other'
    END as band,
    country,
    COUNT(*) as record_count,
    AVG(snr) as avg_snr,
    MAX(snr) as max_snr,
    MIN(snr) as min_snr,
    COUNT(DISTINCT receiver_callsign) as unique_stations
FROM sender_records
GROUP BY hour, sender_callsign, mode, band, country;

-- ── 传播统计（接收方向）- 每小时 ──────────────────────────
CREATE MATERIALIZED VIEW propagation_receiver_hourly_mv
DISTRIBUTED BY HASH(hour) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('hour', qso_time) as hour,
    receiver_callsign,
    mode,
    CASE
        WHEN frequency BETWEEN 1800000 AND 2000000 THEN '160m'
        WHEN frequency BETWEEN 3500000 AND 4000000 THEN '80m'
        WHEN frequency BETWEEN 5330000 AND 5405000 THEN '60m'
        WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m'
        WHEN frequency BETWEEN 10100000 AND 10150000 THEN '30m'
        WHEN frequency BETWEEN 14000000 AND 14350000 THEN '20m'
        WHEN frequency BETWEEN 18068000 AND 18168000 THEN '17m'
        WHEN frequency BETWEEN 21000000 AND 21450000 THEN '15m'
        WHEN frequency BETWEEN 24890000 AND 24990000 THEN '12m'
        WHEN frequency BETWEEN 28000000 AND 29700000 THEN '10m'
        WHEN frequency BETWEEN 50000000 AND 54000000 THEN '6m'
        WHEN frequency BETWEEN 144000000 AND 148000000 THEN '2m'
        ELSE 'Other'
    END as band,
    country,
    COUNT(*) as record_count,
    AVG(snr) as avg_snr,
    MAX(snr) as max_snr,
    MIN(snr) as min_snr,
    COUNT(DISTINCT sender_callsign) as unique_stations
FROM receiver_records
GROUP BY hour, receiver_callsign, mode, band, country;

-- ── 传播统计（发送方向）- 每日 ──────────────────────────
CREATE MATERIALIZED VIEW propagation_sender_daily_mv
DISTRIBUTED BY HASH(day) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('day', qso_time) as day,
    sender_callsign,
    mode,
    CASE
        WHEN frequency BETWEEN 1800000 AND 2000000 THEN '160m'
        WHEN frequency BETWEEN 3500000 AND 4000000 THEN '80m'
        WHEN frequency BETWEEN 5330000 AND 5405000 THEN '60m'
        WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m'
        WHEN frequency BETWEEN 10100000 AND 10150000 THEN '30m'
        WHEN frequency BETWEEN 14000000 AND 14350000 THEN '20m'
        WHEN frequency BETWEEN 18068000 AND 18168000 THEN '17m'
        WHEN frequency BETWEEN 21000000 AND 21450000 THEN '15m'
        WHEN frequency BETWEEN 24890000 AND 24990000 THEN '12m'
        WHEN frequency BETWEEN 28000000 AND 29700000 THEN '10m'
        WHEN frequency BETWEEN 50000000 AND 54000000 THEN '6m'
        WHEN frequency BETWEEN 144000000 AND 148000000 THEN '2m'
        ELSE 'Other'
    END as band,
    country,
    COUNT(*) as record_count,
    AVG(snr) as avg_snr,
    MAX(snr) as max_snr,
    MIN(snr) as min_snr,
    COUNT(DISTINCT receiver_callsign) as unique_stations
FROM sender_records
GROUP BY day, sender_callsign, mode, band, country;

-- ── 传播统计（接收方向）- 每日 ──────────────────────────
CREATE MATERIALIZED VIEW propagation_receiver_daily_mv
DISTRIBUTED BY HASH(day) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('day', qso_time) as day,
    receiver_callsign,
    mode,
    CASE
        WHEN frequency BETWEEN 1800000 AND 2000000 THEN '160m'
        WHEN frequency BETWEEN 3500000 AND 4000000 THEN '80m'
        WHEN frequency BETWEEN 5330000 AND 5405000 THEN '60m'
        WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m'
        WHEN frequency BETWEEN 10100000 AND 10150000 THEN '30m'
        WHEN frequency BETWEEN 14000000 AND 14350000 THEN '20m'
        WHEN frequency BETWEEN 18068000 AND 18168000 THEN '17m'
        WHEN frequency BETWEEN 21000000 AND 21450000 THEN '15m'
        WHEN frequency BETWEEN 24890000 AND 24990000 THEN '12m'
        WHEN frequency BETWEEN 28000000 AND 29700000 THEN '10m'
        WHEN frequency BETWEEN 50000000 AND 54000000 THEN '6m'
        WHEN frequency BETWEEN 144000000 AND 148000000 THEN '2m'
        ELSE 'Other'
    END as band,
    country,
    COUNT(*) as record_count,
    AVG(snr) as avg_snr,
    MAX(snr) as max_snr,
    MIN(snr) as min_snr,
    COUNT(DISTINCT sender_callsign) as unique_stations
FROM receiver_records
GROUP BY day, receiver_callsign, mode, band, country;

-- ── 传播 SNR 日统计（发送方向，含标准差）──────────────────
CREATE MATERIALIZED VIEW propagation_snr_daily_mv
DISTRIBUTED BY HASH(day) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('day', qso_time) as day,
    mode,
    CASE
        WHEN frequency BETWEEN 1800000 AND 2000000 THEN '160m'
        WHEN frequency BETWEEN 3500000 AND 4000000 THEN '80m'
        WHEN frequency BETWEEN 5330000 AND 5405000 THEN '60m'
        WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m'
        WHEN frequency BETWEEN 10100000 AND 10150000 THEN '30m'
        WHEN frequency BETWEEN 14000000 AND 14350000 THEN '20m'
        WHEN frequency BETWEEN 18068000 AND 18168000 THEN '17m'
        WHEN frequency BETWEEN 21000000 AND 21450000 THEN '15m'
        WHEN frequency BETWEEN 24890000 AND 24990000 THEN '12m'
        WHEN frequency BETWEEN 28000000 AND 29700000 THEN '10m'
        WHEN frequency BETWEEN 50000000 AND 54000000 THEN '6m'
        WHEN frequency BETWEEN 144000000 AND 148000000 THEN '2m'
        ELSE 'Other'
    END as band,
    country,
    COUNT(*) as record_count,
    AVG(snr) as avg_snr,
    MAX(snr) as max_snr,
    MIN(snr) as min_snr,
    STDDEV(snr) as snr_stddev,
    COUNT(DISTINCT receiver_callsign) as unique_rx_stations
FROM sender_records
GROUP BY day, mode, band, country;

-- 通联日志表（从 WSJT-X/JTDX 导入的真实通联记录）
CREATE TABLE IF NOT EXISTS qso_log (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    callsign VARCHAR(20) NOT NULL COMMENT '对方呼号',
    station_callsign VARCHAR(20) NOT NULL COMMENT '本台呼号',
    grid_locator VARCHAR(10) DEFAULT NULL COMMENT '对方网格定位',
    my_grid_locator VARCHAR(10) DEFAULT NULL COMMENT '本台网格定位',
    mode VARCHAR(20) DEFAULT NULL COMMENT '通信模式',
    rst_sent VARCHAR(10) DEFAULT NULL COMMENT '发送信号报告',
    rst_rcvd VARCHAR(10) DEFAULT NULL COMMENT '接收信号报告',
    qso_date DATE NOT NULL COMMENT '通联日期',
    qso_time DATETIME NOT NULL COMMENT '通联时间',
    band VARCHAR(10) DEFAULT NULL COMMENT '波段',
    frequency DECIMAL(12,6) DEFAULT NULL COMMENT '频率 (MHz)',
    tx_pwr INT DEFAULT NULL COMMENT '发射功率 (W)',
    comment VARCHAR(500) DEFAULT NULL COMMENT '备注',
    source_file VARCHAR(255) DEFAULT NULL COMMENT '来源文件',
    distance DECIMAL(10,1) DEFAULT NULL COMMENT '距离 (km)',
    bearing DECIMAL(5,1) DEFAULT NULL COMMENT '方位角',
    country VARCHAR(50) DEFAULT NULL COMMENT '对方国家',
    dxcc VARCHAR(10) DEFAULT NULL COMMENT 'DXCC 编号',
    confirmed TINYINT DEFAULT 0 COMMENT '是否确认 (0=否, 1=是)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=OLAP
DUPLICATE KEY(id)
PARTITION BY RANGE(qso_time) (
    PARTITION p202301 VALUES LESS THAN ('2023-02-01'),
    PARTITION p202302 VALUES LESS THAN ('2023-03-01'),
    PARTITION p202303 VALUES LESS THAN ('2023-04-01'),
    PARTITION p202304 VALUES LESS THAN ('2023-05-01'),
    PARTITION p202305 VALUES LESS THAN ('2023-06-01'),
    PARTITION p202306 VALUES LESS THAN ('2023-07-01'),
    PARTITION p202307 VALUES LESS THAN ('2023-08-01'),
    PARTITION p202308 VALUES LESS THAN ('2023-09-01'),
    PARTITION p202309 VALUES LESS THAN ('2023-10-01'),
    PARTITION p202310 VALUES LESS THAN ('2023-11-01'),
    PARTITION p202311 VALUES LESS THAN ('2023-12-01'),
    PARTITION p202312 VALUES LESS THAN ('2024-01-01'),
    PARTITION p202401 VALUES LESS THAN ('2024-02-01'),
    PARTITION p202402 VALUES LESS THAN ('2024-03-01'),
    PARTITION p202403 VALUES LESS THAN ('2024-04-01'),
    PARTITION p202404 VALUES LESS THAN ('2024-05-01'),
    PARTITION p202405 VALUES LESS THAN ('2024-06-01'),
    PARTITION p202406 VALUES LESS THAN ('2024-07-01'),
    PARTITION p202407 VALUES LESS THAN ('2024-08-01'),
    PARTITION p202408 VALUES LESS THAN ('2024-09-01'),
    PARTITION p202409 VALUES LESS THAN ('2024-10-01'),
    PARTITION p202410 VALUES LESS THAN ('2024-11-01'),
    PARTITION p202411 VALUES LESS THAN ('2024-12-01'),
    PARTITION p202412 VALUES LESS THAN ('2025-01-01'),
    PARTITION p202501 VALUES LESS THAN ('2025-02-01'),
    PARTITION p202502 VALUES LESS THAN ('2025-03-01'),
    PARTITION p202503 VALUES LESS THAN ('2025-04-01'),
    PARTITION p202504 VALUES LESS THAN ('2025-05-01'),
    PARTITION p202505 VALUES LESS THAN ('2025-06-01'),
    PARTITION p202506 VALUES LESS THAN ('2025-07-01'),
    PARTITION p202507 VALUES LESS THAN ('2025-08-01'),
    PARTITION p202508 VALUES LESS THAN ('2025-09-01'),
    PARTITION p202509 VALUES LESS THAN ('2025-10-01'),
    PARTITION p202510 VALUES LESS THAN ('2025-11-01'),
    PARTITION p202511 VALUES LESS THAN ('2025-12-01'),
    PARTITION p202512 VALUES LESS THAN ('2026-01-01'),
    PARTITION p202601 VALUES LESS THAN ('2026-02-01'),
    PARTITION p202602 VALUES LESS THAN ('2026-03-01'),
    PARTITION p202603 VALUES LESS THAN ('2026-04-01'),
    PARTITION p202604 VALUES LESS THAN ('2026-05-01'),
    PARTITION p202605 VALUES LESS THAN ('2026-06-01'),
    PARTITION p202606 VALUES LESS THAN ('2026-07-01'),
    PARTITION p202607 VALUES LESS THAN ('2026-08-01'),
    PARTITION p202608 VALUES LESS THAN ('2026-09-01'),
    PARTITION p202609 VALUES LESS THAN ('2026-10-01'),
    PARTITION p202610 VALUES LESS THAN ('2026-11-01'),
    PARTITION p202611 VALUES LESS THAN ('2026-12-01'),
    PARTITION p202612 VALUES LESS THAN ('2027-01-01'),
    PARTITION p2027 VALUES LESS THAN ('2028-01-01')
)
DISTRIBUTED BY HASH(callsign) BUCKETS 10
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-36",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "dynamic_partition.buckets" = "10",
    "compression" = "LZ4"
);

-- 创建索引
CREATE INDEX idx_callsign ON qso_log(callsign);
CREATE INDEX idx_station_callsign ON qso_log(station_callsign);
CREATE INDEX idx_mode ON qso_log(mode);
CREATE INDEX idx_band ON qso_log(band);
CREATE INDEX idx_qso_date ON qso_log(qso_date);

-- 同步日志表（记录每次同步的状态）
CREATE TABLE IF NOT EXISTS sync_log (
    id INT AUTO_INCREMENT COMMENT '主键',
    source_type VARCHAR(20) NOT NULL COMMENT '来源类型 (wsjtx/jtdx)',
    source_file VARCHAR(255) NOT NULL COMMENT '来源文件路径',
    last_modified BIGINT DEFAULT 0 COMMENT '文件最后修改时间戳',
    records_imported INT DEFAULT 0 COMMENT '本次导入记录数',
    records_new INT DEFAULT 0 COMMENT '新增记录数',
    sync_time DATETIME NOT NULL COMMENT '同步时间',
    status VARCHAR(20) DEFAULT 'success' COMMENT '状态 (success/failed)',
    error_msg VARCHAR(500) DEFAULT NULL COMMENT '错误信息',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(source_type) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "compression" = "LZ4"
);

-- ── QSO 通联统计 - 每日 ──────────────────────────────────
CREATE MATERIALIZED VIEW qso_daily_stats_mv
DISTRIBUTED BY HASH(qso_date) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    qso_date,
    band,
    mode,
    station_callsign,
    COUNT(*) as qso_count,
    COUNT(DISTINCT callsign) as unique_callsigns,
    COUNT(DISTINCT country) as unique_countries,
    AVG(CAST(rst_rcvd AS DOUBLE)) as avg_rst_rcvd
FROM qso_log
GROUP BY qso_date, band, mode, station_callsign;

-- ── QSO 通联统计 - 每月（趋势图）───────────────────────────
CREATE MATERIALIZED VIEW qso_monthly_stats_mv
DISTRIBUTED BY HASH(month_start) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    date_trunc('month', qso_date) as month_start,
    station_callsign,
    band,
    mode,
    country,
    COUNT(*) as qso_count,
    COUNT(DISTINCT callsign) as unique_callsigns,
    AVG(distance) as avg_distance,
    MAX(distance) as max_distance,
    AVG(CAST(rst_rcvd AS DOUBLE)) as avg_rst_rcvd
FROM qso_log
GROUP BY month_start, station_callsign, band, mode, country;

-- ── QSO 通联统计 - 按小时（UTC 传播模式分析）──────────────
CREATE MATERIALIZED VIEW qso_hourly_stats_mv
DISTRIBUTED BY HASH(hour) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    HOUR(qso_time) as hour,
    station_callsign,
    band,
    mode,
    COUNT(*) as qso_count,
    COUNT(DISTINCT callsign) as unique_callsigns,
    COUNT(DISTINCT country) as unique_countries,
    AVG(CAST(rst_rcvd AS DOUBLE)) as avg_rst_rcvd
FROM qso_log
GROUP BY hour, station_callsign, band, mode;

-- ── QSO DXCC 国家统计（DXCC 进度看板）─────────────────────
CREATE MATERIALIZED VIEW qso_country_stats_mv
DISTRIBUTED BY HASH(station_callsign) BUCKETS 8
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    station_callsign,
    country,
    band,
    mode,
    COUNT(*) as qso_count,
    COUNT(DISTINCT callsign) as unique_callsigns,
    MIN(qso_date) as first_qso,
    MAX(qso_date) as last_qso,
    AVG(distance) as avg_distance,
    MAX(distance) as max_distance
FROM qso_log
WHERE country IS NOT NULL
GROUP BY station_callsign, country, band, mode;

-- ── 跨域分析：太阳活动 vs 传播（AI/交叉分析用）────────────
CREATE MATERIALIZED VIEW cross_domain_daily_mv
DISTRIBUTED BY HASH(observation_date) BUCKETS 4
REFRESH ASYNC EVERY(INTERVAL 1 HOUR)
AS
SELECT
    sa.observation_date,
    sa.f107_flux,
    sa.sunspot_number,
    q.band,
    q.mode,
    COUNT(DISTINCT q.id) as qso_count,
    COUNT(DISTINCT q.callsign) as unique_callsigns,
    COUNT(DISTINCT q.country) as unique_countries,
    AVG(q.distance) as avg_distance,
    AVG(CAST(q.rst_rcvd AS DOUBLE)) as avg_rst_rcvd
FROM solar_activity sa
LEFT JOIN qso_log q ON sa.observation_date = DATE(q.qso_time)
GROUP BY sa.observation_date, sa.f107_flux, sa.sunspot_number, q.band, q.mode;