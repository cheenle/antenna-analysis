-- ============================================
-- PSK Reporter 数据库优化脚本
-- 针对 500万+ 记录的性能优化
-- ============================================

-- 1. 复合索引优化（按需执行，可能需要较长时间）

-- 时间+频率复合索引（波段筛选最常用）
-- CREATE INDEX idx_qso_time_frequency ON all_records(qso_time, frequency);

-- 时间+发送方呼号复合索引（统计和搜索用）
-- CREATE INDEX idx_qso_sender ON all_records(qso_time, sender_callsign);

-- 时间+接收方呼号复合索引
-- CREATE INDEX idx_qso_receiver ON all_records(qso_time, receiver_callsign);

-- 发送方国家索引（大洲分析用）
-- CREATE INDEX idx_sender_country ON all_records(sender_country);


-- 2. 创建小时级汇总表（大幅提升统计查询性能）
CREATE TABLE IF NOT EXISTS hourly_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stat_hour DATETIME NOT NULL COMMENT '统计小时',
    band VARCHAR(10) NOT NULL COMMENT '波段',
    mode VARCHAR(20) DEFAULT NULL COMMENT '模式',
    sender_country VARCHAR(50) DEFAULT NULL COMMENT '发送方国家',
    record_count INT DEFAULT 0 COMMENT '记录数',
    unique_senders INT DEFAULT 0 COMMENT '唯一发送方数',
    unique_receivers INT DEFAULT 0 COMMENT '唯一接收方数',
    avg_snr DECIMAL(5,1) DEFAULT NULL COMMENT '平均SNR',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_hour_band_mode_country (stat_hour, band, mode, sender_country),
    INDEX idx_stat_hour (stat_hour),
    INDEX idx_band (band)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='小时级统计汇总表';


-- 3. 创建每日活跃呼号汇总表
CREATE TABLE IF NOT EXISTS daily_active_callsigns (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stat_date DATE NOT NULL COMMENT '统计日期',
    callsign VARCHAR(20) NOT NULL COMMENT '呼号',
    is_sender TINYINT DEFAULT 0 COMMENT '是否作为发送方',
    is_receiver TINYINT DEFAULT 0 COMMENT '是否作为接收方',
    sender_count INT DEFAULT 0 COMMENT '发送次数',
    receiver_count INT DEFAULT 0 COMMENT '接收次数',
    country VARCHAR(50) DEFAULT NULL COMMENT '国家',
    first_seen DATETIME DEFAULT NULL COMMENT '首次出现时间',
    last_seen DATETIME DEFAULT NULL COMMENT '最后出现时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_callsign (stat_date, callsign),
    INDEX idx_stat_date (stat_date),
    INDEX idx_callsign (callsign),
    INDEX idx_country (country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日活跃呼号汇总表';


-- 4. 创建波段传播统计表
CREATE TABLE IF NOT EXISTS band_propagation_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stat_hour DATETIME NOT NULL COMMENT '统计小时',
    band VARCHAR(10) NOT NULL COMMENT '波段',
    total_records INT DEFAULT 0 COMMENT '总记录数',
    unique_stations INT DEFAULT 0 COMMENT '唯一电台数',
    avg_snr DECIMAL(5,1) DEFAULT NULL COMMENT '平均SNR',
    top_country VARCHAR(50) DEFAULT NULL COMMENT '最活跃国家',
    top_country_count INT DEFAULT 0 COMMENT '最活跃国家记录数',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_hour_band (stat_hour, band),
    INDEX idx_stat_hour (stat_hour)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='波段传播统计表';


-- 5. 存储过程：刷新小时级统计
DELIMITER //
CREATE PROCEDURE refresh_hourly_stats(IN hours_back INT)
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE stat_hour_val DATETIME;
    DECLARE hour_cursor CURSOR FOR 
        SELECT DISTINCT DATE_FORMAT(qso_time, '%Y-%m-%d %H:00:00') as h
        FROM all_records 
        WHERE qso_time >= DATE_SUB(NOW(), INTERVAL hours_back HOUR);
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;
    
    OPEN hour_cursor;
    
    read_loop: LOOP
        FETCH hour_cursor INTO stat_hour_val;
        IF done THEN
            LEAVE read_loop;
        END IF;
        
        -- 插入或更新小时统计
        INSERT INTO hourly_stats (stat_hour, band, mode, sender_country, record_count, unique_senders, unique_receivers, avg_snr)
        SELECT 
            stat_hour_val,
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
            mode,
            sender_country,
            COUNT(*) as record_count,
            COUNT(DISTINCT sender_callsign) as unique_senders,
            COUNT(DISTINCT receiver_callsign) as unique_receivers,
            ROUND(AVG(snr), 1) as avg_snr
        FROM all_records
        WHERE qso_time >= stat_hour_val AND qso_time < DATE_ADD(stat_hour_val, INTERVAL 1 HOUR)
        GROUP BY band, mode, sender_country
        ON DUPLICATE KEY UPDATE
            record_count = VALUES(record_count),
            unique_senders = VALUES(unique_senders),
            unique_receivers = VALUES(unique_receivers),
            avg_snr = VALUES(avg_snr),
            updated_at = CURRENT_TIMESTAMP;
    END LOOP;
    
    CLOSE hour_cursor;
END //
DELIMITER ;


-- 6. 存储过程：快速获取统计数据（使用汇总表）
DELIMITER //
CREATE PROCEDURE get_band_stats_fast(IN hours_param INT, IN band_param VARCHAR(10), IN callsign_param VARCHAR(20))
BEGIN
    IF band_param = '' AND callsign_param = '' THEN
        -- 无过滤，从汇总表获取
        SELECT 
            band,
            SUM(record_count) as count,
            SUM(unique_senders) as unique_senders,
            SUM(unique_receivers) as unique_receivers,
            ROUND(AVG(avg_snr), 1) as avg_snr
        FROM hourly_stats
        WHERE stat_hour >= DATE_SUB(NOW(), INTERVAL hours_param HOUR)
        GROUP BY band
        ORDER BY count DESC;
    ELSE
        -- 有过滤，查原表（但时间范围已缩小）
        SELECT 
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
            COUNT(*) as count,
            COUNT(DISTINCT sender_callsign) as unique_senders,
            COUNT(DISTINCT receiver_callsign) as unique_receivers,
            ROUND(AVG(snr), 1) as avg_snr
        FROM all_records
        WHERE qso_time >= DATE_SUB(NOW(), INTERVAL hours_param HOUR)
        GROUP BY band
        ORDER BY count DESC;
    END IF;
END //
DELIMITER ;


-- 7. 事件调度器：每小时自动刷新统计
SET GLOBAL event_scheduler = ON;

CREATE EVENT IF NOT EXISTS refresh_hourly_stats_event
ON SCHEDULE EVERY 1 HOUR
STARTS CURRENT_TIMESTAMP
DO CALL refresh_hourly_stats(24);


-- 8. 优化表（重建索引，回收空间）
-- OPTIMIZE TABLE all_records;
-- 注意：OPTIMIZE TABLE 会锁表，建议在低峰期执行
