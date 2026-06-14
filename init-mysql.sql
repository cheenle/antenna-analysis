-- PSK Reporter 数据库初始化脚本 (MySQL 版本)

CREATE DATABASE IF NOT EXISTS pskreporter DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE pskreporter;

-- 发送记录表（本台发射被他人接收）
CREATE TABLE IF NOT EXISTS sender_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sender_callsign (sender_callsign),
    INDEX idx_receiver_callsign (receiver_callsign),
    INDEX idx_qso_time (qso_time),
    INDEX idx_mode (mode),
    INDEX idx_frequency (frequency),
    UNIQUE KEY uk_record (sender_callsign, receiver_callsign, frequency, qso_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发送记录表';

-- 接收记录表（本台接收到他人信号）
CREATE TABLE IF NOT EXISTS receiver_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sender_callsign (sender_callsign),
    INDEX idx_receiver_callsign (receiver_callsign),
    INDEX idx_qso_time (qso_time),
    INDEX idx_mode (mode),
    INDEX idx_frequency (frequency),
    UNIQUE KEY uk_record (sender_callsign, receiver_callsign, frequency, qso_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='接收记录表';

-- 数据获取日志表
CREATE TABLE IF NOT EXISTS fetch_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    callsign VARCHAR(20) NOT NULL,
    fetch_time DATETIME NOT NULL,
    sender_count INT DEFAULT 0,
    receiver_count INT DEFAULT 0,
    source VARCHAR(20) DEFAULT 'ADIF',
    adif_file VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据获取日志';

-- 通联日志表（从 WSJT-X/JTDX 导入的真实通联记录）
CREATE TABLE IF NOT EXISTS qso_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_callsign (callsign),
    INDEX idx_station_callsign (station_callsign),
    INDEX idx_qso_date (qso_date),
    INDEX idx_band (band),
    INDEX idx_mode (mode),
    INDEX idx_country (country),
    UNIQUE KEY uk_qso (callsign, station_callsign, qso_time, frequency)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通联日志表';

-- 同步日志表（记录每次同步的状态）
CREATE TABLE IF NOT EXISTS sync_log (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    source_type VARCHAR(20) NOT NULL COMMENT '来源类型 (wsjtx/jtdx)',
    source_file VARCHAR(255) NOT NULL COMMENT '来源文件路径',
    last_modified BIGINT DEFAULT 0 COMMENT '文件最后修改时间戳',
    records_imported INT DEFAULT 0 COMMENT '本次导入记录数',
    records_new INT DEFAULT 0 COMMENT '新增记录数',
    sync_time DATETIME NOT NULL COMMENT '同步时间',
    status VARCHAR(20) DEFAULT 'success' COMMENT '状态 (success/failed)',
    error_msg VARCHAR(500) DEFAULT NULL COMMENT '错误信息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='同步日志表';
