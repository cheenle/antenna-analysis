-- =====================================================
-- 扩展跨领域数据表设计
-- 与QSO日志时间对齐的多元数据
-- =====================================================

-- 1. 气象数据表（温度、气压、湿度影响传播）
CREATE TABLE IF NOT EXISTS weather_data (
    id BIGINT AUTO_INCREMENT,
    observation_time DATETIME NOT NULL COMMENT '观测时间',
    station_id VARCHAR(20) DEFAULT 'BEIJING' COMMENT '气象站代码',
    temperature DECIMAL(5,2) DEFAULT NULL COMMENT '温度(°C)',
    pressure DECIMAL(8,2) DEFAULT NULL COMMENT '气压(hPa)',
    humidity INT DEFAULT NULL COMMENT '湿度(%)',
    wind_speed DECIMAL(5,2) DEFAULT NULL COMMENT '风速(km/h)',
    wind_direction INT DEFAULT NULL COMMENT '风向(度)',
    precipitation DECIMAL(5,2) DEFAULT NULL COMMENT '降水量(mm)',
    visibility DECIMAL(6,2) DEFAULT NULL COMMENT '能见度(km)',
    cloud_cover INT DEFAULT NULL COMMENT '云量(%)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 2. 月球位置数据表（影响EME通信和潮汐）
CREATE TABLE IF NOT EXISTS moon_position (
    id BIGINT AUTO_INCREMENT,
    observation_time DATETIME NOT NULL COMMENT '观测时间',
    moon_phase DECIMAL(5,2) DEFAULT NULL COMMENT '月相(0-1, 0=新月, 0.5=满月)',
    moon_elevation DECIMAL(6,2) DEFAULT NULL COMMENT '月仰角(度)',
    moon_azimuth DECIMAL(6,2) DEFAULT NULL COMMENT '月方位角(度)',
    moon_distance DECIMAL(10,2) DEFAULT NULL COMMENT '月地距离(km)',
    illumination DECIMAL(5,2) DEFAULT NULL COMMENT '照亮比例(%)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 3. 雷电活动数据表（射电噪声来源）
CREATE TABLE IF NOT EXISTS lightning_data (
    id BIGINT AUTO_INCREMENT,
    strike_time DATETIME NOT NULL COMMENT '雷击时间',
    latitude DECIMAL(8,4) DEFAULT NULL COMMENT '纬度',
    longitude DECIMAL(8,4) DEFAULT NULL COMMENT '经度',
    intensity DECIMAL(8,2) DEFAULT NULL COMMENT '强度(kA)',
    distance_from_station DECIMAL(8,2) DEFAULT NULL COMMENT '距离本站(km)',
    stroke_type VARCHAR(10) DEFAULT NULL COMMENT '类型(CG/IC)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(strike_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 4. 流星雨数据表（流星散射通信）
CREATE TABLE IF NOT EXISTS meteor_shower (
    id BIGINT AUTO_INCREMENT,
    shower_name VARCHAR(50) NOT NULL COMMENT '流星雨名称',
    peak_date DATE NOT NULL COMMENT '峰值日期',
    start_date DATE DEFAULT NULL COMMENT '开始日期',
    end_date DATE DEFAULT NULL COMMENT '结束日期',
    zhr INT DEFAULT NULL COMMENT '天顶每小时出现率',
    radiant_ra DECIMAL(6,2) DEFAULT NULL COMMENT '辐射点赤经',
    radiant_dec DECIMAL(6,2) DEFAULT NULL COMMENT '辐射点赤纬',
    velocity DECIMAL(6,2) DEFAULT NULL COMMENT '速度(km/s)',
    moon_phase_at_peak DECIMAL(4,2) DEFAULT NULL COMMENT '峰值时月相',
    activity_level VARCHAR(20) DEFAULT NULL COMMENT '活跃等级',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(peak_date) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 5. 地震数据表（电离层前兆）
CREATE TABLE IF NOT EXISTS seismic_data (
    id BIGINT AUTO_INCREMENT,
    event_time DATETIME NOT NULL COMMENT '地震时间',
    latitude DECIMAL(8,4) DEFAULT NULL COMMENT '震中纬度',
    longitude DECIMAL(8,4) DEFAULT NULL COMMENT '震中经度',
    depth DECIMAL(6,2) DEFAULT NULL COMMENT '深度(km)',
    magnitude DECIMAL(3,1) DEFAULT NULL COMMENT '震级',
    location VARCHAR(200) DEFAULT NULL COMMENT '位置描述',
    distance_from_station DECIMAL(8,2) DEFAULT NULL COMMENT '距离本站(km)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 6. 航空交通数据表（飞机散射）
CREATE TABLE IF NOT EXISTS air_traffic (
    id BIGINT AUTO_INCREMENT,
    observation_time DATETIME NOT NULL COMMENT '观测时间',
    flight_count INT DEFAULT NULL COMMENT '航班数量',
    avg_altitude DECIMAL(8,2) DEFAULT NULL COMMENT '平均高度(ft)',
    high_altitude_flights INT DEFAULT NULL COMMENT '高空航班数(>30k ft)',
    correlation_path VARCHAR(50) DEFAULT NULL COMMENT '相关传播路径',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 7. 人为干扰/大型活动表（节假日通联模式）
CREATE TABLE IF NOT EXISTS human_activity (
    id BIGINT AUTO_INCREMENT,
    event_date DATE NOT NULL COMMENT '事件日期',
    event_type VARCHAR(50) NOT NULL COMMENT '事件类型',
    event_name VARCHAR(200) DEFAULT NULL COMMENT '事件名称',
    country_code VARCHAR(10) DEFAULT NULL COMMENT '国家代码',
    activity_level INT DEFAULT NULL COMMENT '活跃程度(1-10)',
    expected_qso_increase DECIMAL(5,2) DEFAULT NULL COMMENT '预期QSO增长(%)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_date) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 8. 大气环流指数表（NAO/AO等影响传播）
CREATE TABLE IF NOT EXISTS atmospheric_indices (
    id BIGINT AUTO_INCREMENT,
    index_date DATE NOT NULL COMMENT '指数日期',
    index_type VARCHAR(20) NOT NULL COMMENT '指数类型(NAO/AO/PNA)',
    index_value DECIMAL(6,2) DEFAULT NULL COMMENT '指数值',
    phase VARCHAR(20) DEFAULT NULL COMMENT '相位(正/负/中性)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(index_date) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 9. 宇宙射线数据表（可能影响电离层）
CREATE TABLE IF NOT EXISTS cosmic_rays (
    id BIGINT AUTO_INCREMENT,
    measurement_time DATETIME NOT NULL COMMENT '测量时间',
    neutron_count INT DEFAULT NULL COMMENT '中子计数',
    station_name VARCHAR(50) DEFAULT NULL COMMENT '监测站名称',
    pressure_corrected BOOLEAN DEFAULT FALSE COMMENT '是否气压修正',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(measurement_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 10. 木星射电爆发数据表（自然射电源）
CREATE TABLE IF NOT EXISTS jupiter_radio (
    id BIGINT AUTO_INCREMENT,
    event_time DATETIME NOT NULL COMMENT '事件时间',
    frequency_mhz DECIMAL(6,2) DEFAULT NULL COMMENT '频率(MHz)',
    intensity_db DECIMAL(6,2) DEFAULT NULL COMMENT '强度(dB)',
    io_phase VARCHAR(20) DEFAULT NULL COMMENT '木卫一相位',
    cml DECIMAL(6,2) DEFAULT NULL COMMENT '中央经度',
    duration_seconds INT DEFAULT NULL COMMENT '持续时间(秒)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 创建跨领域关联分析视图示例
CREATE VIEW IF NOT EXISTS qso_cross_domain_analysis AS
SELECT 
    q.qso_time,
    q.band,
    q.callsign,
    q.distance,
    q.rst_rcvd,
    q.mode,
    sa.f107_flux,
    sa.sunspot_number,
    gi.kp_value,
    gi.storm_level,
    sw.bz as solar_wind_bz,
    sw.bt as solar_wind_bt,
    mp.moon_phase,
    mp.moon_elevation,
    wd.temperature,
    wd.pressure,
    wd.humidity,
    CASE 
        WHEN ms.shower_name IS NOT NULL THEN 1 
        ELSE 0 
    END as during_meteor_shower,
    ms.shower_name as active_shower
FROM qso_log q
LEFT JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
LEFT JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
LEFT JOIN solar_wind sw ON DATE_FORMAT(q.qso_time, '%Y-%m-%d %H:00:00') = DATE_FORMAT(sw.measurement_time, '%Y-%m-%d %H:00:00')
LEFT JOIN moon_position mp ON DATE_FORMAT(q.qso_time, '%Y-%m-%d %H:00:00') = DATE_FORMAT(mp.observation_time, '%Y-%m-%d %H:00:00')
LEFT JOIN weather_data wd ON DATE(q.qso_time) = DATE(wd.observation_time)
LEFT JOIN meteor_shower ms ON DATE(q.qso_time) BETWEEN ms.start_date AND ms.end_date;
