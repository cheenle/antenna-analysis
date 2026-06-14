-- =====================================================
-- 空间天气数据表设计
-- 用于与 PSK Reporter 无线电数据进行横向分析
-- 支持太阳活动、地磁活动、太阳风、电离层数据
-- =====================================================

-- 创建空间天气数据库（可与pskreporter共用，或单独使用）
-- CREATE DATABASE IF NOT EXISTS spaceweather;
-- USE spaceweather;

-- =====================================================
-- 1. 太阳活动数据表
-- 太阳黑子数、F10.7射电通量等
-- =====================================================

CREATE TABLE IF NOT EXISTS solar_activity (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    observation_date DATE NOT NULL COMMENT '观测日期',
    observation_time DATETIME DEFAULT NULL COMMENT '观测时间（可选，用于小时数据）',
    
    -- 太阳黑子数据 (SIDC - Sunspot Index and Long-term Solar Observations)
    sunspot_number DECIMAL(8,2) DEFAULT NULL COMMENT '国际太阳黑子数 (ISN)',
    sunspot_number_std DECIMAL(8,2) DEFAULT NULL COMMENT '太阳黑子数标准差',
    sunspot_area DECIMAL(10,2) DEFAULT NULL COMMENT '太阳黑子面积（太阳半球百万分之一）',
    
    -- F10.7 太阳射电通量 (NOAA/Canada)
    f107_flux DECIMAL(8,2) DEFAULT NULL COMMENT 'F10.7 射电通量 (sfu) - 10.7cm波长',
    f107_flux_adjusted DECIMAL(8,2) DEFAULT NULL COMMENT '调整后的F10.7通量（1AU距离）',
    
    -- 太阳耀斑数据
    xray_flux DECIMAL(12,6) DEFAULT NULL COMMENT 'X射线通量 (W/m²)',
    flare_class VARCHAR(5) DEFAULT NULL COMMENT '耀斑等级 (A/B/C/M/X)',
    
    -- 日冕物质抛射 (CME)
    cme_count INT DEFAULT 0 COMMENT '当日CME次数',
    cme_speed DECIMAL(10,2) DEFAULT NULL COMMENT 'CME速度 (km/s)',
    
    -- 数据来源
    data_source VARCHAR(50) DEFAULT 'SIDC' COMMENT '数据来源 (SIDC/NOAA/NASA)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_date (observation_date, observation_time),
    KEY idx_date (observation_date)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_date) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-36",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "compression" = "LZ4"
)
COMMENT '太阳活动数据表 - 包含太阳黑子、F10.7通量、耀斑等';

-- =====================================================
-- 2. 太阳风数据表
-- ACE/DSCOVR卫星实时数据
-- =====================================================

CREATE TABLE IF NOT EXISTS solar_wind (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    measurement_time DATETIME NOT NULL COMMENT '测量时间（UTC）',
    
    -- 太阳风等离子体参数
    proton_density DECIMAL(8,3) DEFAULT NULL COMMENT '质子密度 (n/cm³)',
    proton_temperature DECIMAL(10,2) DEFAULT NULL COMMENT '质子温度 (K)',
    proton_speed DECIMAL(10,2) DEFAULT NULL COMMENT '太阳风速度 (km/s)',
    
    -- 磁场参数
    bt DECIMAL(8,2) DEFAULT NULL COMMENT '总磁场强度 (nT)',
    bz DECIMAL(8,2) DEFAULT NULL COMMENT 'Bz分量 (nT) - 影响地磁暴的关键参数',
    by DECIMAL(8,2) DEFAULT NULL COMMENT 'By分量 (nT)',
    bx DECIMAL(8,2) DEFAULT NULL COMMENT 'Bx分量 (nT)',
    
    -- 阿尔芬马赫数
    alfven_mach DECIMAL(8,3) DEFAULT NULL COMMENT '阿尔芬马赫数',
    
    -- 动压
    dynamic_pressure DECIMAL(10,4) DEFAULT NULL COMMENT '太阳风动压 (nPa)',
    
    -- 数据来源
    satellite VARCHAR(20) DEFAULT 'DSCOVR' COMMENT '数据来源卫星 (ACE/DSCOVR)',
    data_quality VARCHAR(10) DEFAULT 'good' COMMENT '数据质量 (good/marginal/bad)',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_time (measurement_time),
    KEY idx_time (measurement_time)
) ENGINE=OLAP
DUPLICATE KEY(id)
PARTRIBUTED BY HASH(measurement_time) BUCKETS 8
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "DAY",
    "dynamic_partition.start" = "-90",
    "dynamic_partition.end" = "7",
    "dynamic_partition.prefix" = "p",
    "compression" = "LZ4"
)
COMMENT '太阳风实时数据 - ACE/DSCOVR卫星数据';

-- =====================================================
-- 3. 地磁指数数据表
-- Kp、Ap、Dst、AE等地磁活动指数
-- =====================================================

CREATE TABLE IF NOT EXISTS geomagnetic_indices (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    measurement_time DATETIME NOT NULL COMMENT '测量时间（UTC）',
    measurement_date DATE NOT NULL COMMENT '测量日期',
    
    -- Kp指数 (GFZ Potsdam) - 3小时指数，范围0-9
    kp_value DECIMAL(3,1) DEFAULT NULL COMMENT 'Kp指数 (0-9)',
    kp_sum DECIMAL(5,1) DEFAULT NULL COMMENT '每日Kp总和',
    ap_value INT DEFAULT NULL COMMENT 'Ap指数 (0-400)',
    ap_daily INT DEFAULT NULL COMMENT '每日Ap均值',
    
    -- Dst指数 (WDC Kyoto) - 磁暴强度指标
    dst_value INT DEFAULT NULL COMMENT 'Dst指数 (nT) - 负值表示磁暴',
    
    -- AE指数 - 极光区电集流
    ae_value INT DEFAULT NULL COMMENT 'AE指数 (nT)',
    au_value INT DEFAULT NULL COMMENT 'AU指数 (nT)',
    al_value INT DEFAULT NULL COMMENT 'AL指数 (nT)',
    ao_value INT DEFAULT NULL COMMENT 'AO指数 (nT)',
    
    -- 磁暴等级
    storm_level VARCHAR(20) DEFAULT NULL COMMENT '磁暴等级 (G0-G5)',
    storm_description VARCHAR(50) DEFAULT NULL COMMENT '磁暴描述',
    
    -- 数据来源
    kp_source VARCHAR(30) DEFAULT 'GFZ' COMMENT 'Kp数据来源 (GFZ/NOAA)',
    dst_source VARCHAR(30) DEFAULT 'WDC' COMMENT 'Dst数据来源 (WDC/NOAA)',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_time (measurement_time),
    KEY idx_time (measurement_time),
    KEY idx_date (measurement_date)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(measurement_time) BUCKETS 8
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-36",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "compression" = "LZ4"
)
COMMENT '地磁活动指数 - Kp、Dst、AE等';

-- =====================================================
-- 4. 电离层数据表
-- 临界频率、MUF、TEC等
-- =====================================================

CREATE TABLE IF NOT EXISTS ionosphere_data (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    observation_time DATETIME NOT NULL COMMENT '观测时间（UTC）',
    
    -- 观测站信息
    station_id VARCHAR(20) DEFAULT NULL COMMENT '电离层观测站代码',
    station_name VARCHAR(50) DEFAULT NULL COMMENT '观测站名称',
    station_lat DECIMAL(8,4) DEFAULT NULL COMMENT '观测站纬度',
    station_lon DECIMAL(8,4) DEFAULT NULL COMMENT '观测站经度',
    
    -- F层参数
    fof2 DECIMAL(8,3) DEFAULT NULL COMMENT 'F2层临界频率 (MHz)',
    hmF2 DECIMAL(10,2) DEFAULT NULL COMMENT 'F2层峰值高度 (km)',
    fof1 DECIMAL(8,3) DEFAULT NULL COMMENT 'F1层临界频率 (MHz)',
    
    -- E层参数
    foe DECIMAL(8,3) DEFAULT NULL COMMENT 'E层临界频率 (MHz)',
    
    -- 最高可用频率 (MUF)
    muf3000 DECIMAL(8,3) DEFAULT NULL COMMENT '3000km距离MUF (MHz)',
    
    -- 总电子含量 (TEC) - 来自GNSS
    tec DECIMAL(10,2) DEFAULT NULL COMMENT '总电子含量 (TECU)',
    
    -- 扩展F层描述
    spread_f VARCHAR(20) DEFAULT NULL COMMENT '扩展F层类型',
    
    -- 数据来源
    data_source VARCHAR(50) DEFAULT 'IRI' COMMENT '数据来源 (Digisonde/IRI/GNSS)',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_time_station (observation_time, station_id),
    KEY idx_time (observation_time),
    KEY idx_station (station_id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_time) BUCKETS 8
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-36",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "compression" = "LZ4"
)
COMMENT '电离层参数数据 - 临界频率、MUF、TEC等';

-- =====================================================
-- 5. 日出日落时间数据表
-- 用于分析昼夜变化对传播的影响
-- =====================================================

CREATE TABLE IF NOT EXISTS sunrise_sunset (
    id BIGINT AUTO_INCREMENT COMMENT '主键',
    location_date DATE NOT NULL COMMENT '日期',
    
    -- 本台位置 (BG1SB - 北京)
    station_callsign VARCHAR(20) NOT NULL DEFAULT 'BG1SB' COMMENT '呼号',
    station_lat DECIMAL(8,4) DEFAULT 39.9042 COMMENT '纬度',
    station_lon DECIMAL(8,4) DEFAULT 116.4074 COMMENT '经度',
    
    -- 日出日落时间
    sunrise_time DATETIME DEFAULT NULL COMMENT '日出时间 (UTC)',
    sunset_time DATETIME DEFAULT NULL COMMENT '日落时间 (UTC)',
    solar_noon DATETIME DEFAULT NULL COMMENT '正午时间 (UTC)',
    
    -- 白昼时长
    daylight_hours DECIMAL(5,2) DEFAULT NULL COMMENT '白昼时长（小时）',
    
    -- 太阳位置
    sun_max_elevation DECIMAL(6,2) DEFAULT NULL COMMENT '太阳最大高度角（度）',
    
    -- 晨昏蒙影
    civil_twilight_begin DATETIME DEFAULT NULL COMMENT '民用晨昏蒙影开始',
    civil_twilight_end DATETIME DEFAULT NULL COMMENT '民用晨昏蒙影结束',
    nautical_twilight_begin DATETIME DEFAULT NULL COMMENT '航海晨昏蒙影开始',
    nautical_twilight_end DATETIME DEFAULT NULL COMMENT '航海晨昏蒙影结束',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_date_callsign (location_date, station_callsign),
    KEY idx_date (location_date)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(location_date) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_dynamic_partition" = "true",
    "dynamic_partition.time_unit" = "MONTH",
    "dynamic_partition.start" = "-36",
    "dynamic_partition.end" = "3",
    "dynamic_partition.prefix" = "p",
    "compression" = "LZ4"
)
COMMENT '日出日落时间表 - 用于分析昼夜传播变化';

-- =====================================================
-- 6. 综合空间天气摘要表
-- 每日汇总，便于快速查询
-- =====================================================

CREATE TABLE IF NOT EXISTS space_weather_daily (
    summary_date DATE NOT NULL COMMENT '日期',
    
    -- 太阳活动汇总
    daily_sunspot_avg DECIMAL(8,2) DEFAULT NULL COMMENT '日均太阳黑子数',
    daily_f107_avg DECIMAL(8,2) DEFAULT NULL COMMENT '日均F10.7通量',
    max_flare_class VARCHAR(5) DEFAULT NULL COMMENT '当日最大耀斑等级',
    cme_count INT DEFAULT 0 COMMENT '当日CME次数',
    
    -- 地磁活动汇总
    daily_kp_avg DECIMAL(3,1) DEFAULT NULL COMMENT '日均Kp指数',
    kp_max DECIMAL(3,1) DEFAULT NULL COMMENT '当日最大Kp',
    dst_min INT DEFAULT NULL COMMENT '当日最小Dst（最负值）',
    geomagnetic_storm_hours INT DEFAULT 0 COMMENT '地磁暴小时数',
    
    -- 太阳风汇总
    solar_wind_speed_avg DECIMAL(10,2) DEFAULT NULL COMMENT '平均太阳风速度',
    solar_wind_speed_max DECIMAL(10,2) DEFAULT NULL COMMENT '最大太阳风速度',
    bz_min DECIMAL(8,2) DEFAULT NULL COMMENT '最小Bz（南向）',
    
    -- 电离层汇总（可选）
    fof2_avg DECIMAL(8,3) DEFAULT NULL COMMENT '平均foF2',
    
    -- 传播条件评估
    propagation_quality VARCHAR(20) DEFAULT NULL COMMENT '传播条件评估',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
    
    PRIMARY KEY (summary_date)
) ENGINE=OLAP
DUPLICATE KEY(summary_date)
DISTRIBUTED BY HASH(summary_date) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "compression" = "LZ4"
)
COMMENT '空间天气每日摘要 - 快速查询用';

-- =====================================================
-- 创建物化视图 - 用于分析
-- =====================================================

-- 太阳风与地磁指数关联分析
CREATE MATERIALIZED VIEW IF NOT EXISTS solar_wind_geomag_mv
BUILD IMMEDIATE
REFRESH COMPLETE ON SCHEDULE EVERY 1 HOUR
AS
SELECT 
    DATE_TRUNC(measurement_time, 'hour') as hour,
    AVG(proton_speed) as avg_speed,
    AVG(bz) as avg_bz,
    MIN(bz) as min_bz,
    AVG(dynamic_pressure) as avg_pressure,
    MAX(kp_value) as max_kp,
    MIN(dst_value) as min_dst
FROM solar_wind sw
LEFT JOIN geomagnetic_indices gi 
    ON DATE_TRUNC(sw.measurement_time, 'hour') = DATE_TRUNC(gi.measurement_time, 'hour')
GROUP BY hour;

-- 太阳活动与传播条件关联
CREATE MATERIALIZED VIEW IF NOT EXISTS solar_propagation_mv
BUILD IMMEDIATE
REFRESH COMPLETE ON SCHEDULE EVERY 1 HOUR
AS
SELECT 
    sa.observation_date,
    sa.sunspot_number,
    sa.f107_flux,
    gi.kp_value,
    gi.dst_value,
    COUNT(DISTINCT sr.receiver_callsign) as unique_receivers,
    COUNT(DISTINCT rr.sender_callsign) as unique_senders,
    AVG(sr.snr) as avg_tx_snr,
    AVG(rr.snr) as avg_rx_snr
FROM solar_activity sa
LEFT JOIN geomagnetic_indices gi ON sa.observation_date = gi.measurement_date
LEFT JOIN sender_records sr ON DATE(sr.qso_time) = sa.observation_date
LEFT JOIN receiver_records rr ON DATE(rr.qso_time) = sa.observation_date
GROUP BY sa.observation_date, sa.sunspot_number, sa.f107_flux, gi.kp_value, gi.dst_value;

-- =====================================================
-- 常用查询索引
-- =====================================================

CREATE INDEX idx_solar_date ON solar_activity(observation_date);
CREATE INDEX idx_sw_time ON solar_wind(measurement_time);
CREATE INDEX idx_geo_time ON geomagnetic_indices(measurement_time);
CREATE INDEX idx_iono_time ON ionosphere_data(observation_time);
