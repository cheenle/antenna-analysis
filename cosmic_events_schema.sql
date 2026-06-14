-- =====================================================
-- 宏观宇宙事件数据表
-- 记录宇宙尺度现象与地球电离层/射电传播的关联
-- =====================================================

-- 1. 超新星爆发事件
CREATE TABLE IF NOT EXISTS supernovae (
    id BIGINT AUTO_INCREMENT,
    event_name VARCHAR(50) NOT NULL COMMENT '超新星名称 (如 SN 1987A)',
    discovery_date DATE NOT NULL COMMENT '发现日期',
    galaxy_host VARCHAR(100) DEFAULT NULL COMMENT '所在星系',
    distance_mpc DECIMAL(10,4) DEFAULT NULL COMMENT '距离 (百万秒差距)',
    redshift DECIMAL(8,6) DEFAULT NULL COMMENT '红移',
    peak_magnitude DECIMAL(5,2) DEFAULT NULL COMMENT '峰值视星等',
    sn_type VARCHAR(10) DEFAULT NULL COMMENT '超新星类型 (Ia/Ib/Ic/II)',
    neutrino_detected BOOLEAN DEFAULT FALSE COMMENT '是否探测到中微子',
    xray_detected BOOLEAN DEFAULT FALSE COMMENT '是否探测到X射线',
    gamma_ray_fluence DECIMAL(10,6) DEFAULT NULL COMMENT '伽马射线流量 (erg/cm²)',
    cosmic_ray_increase_percent DECIMAL(6,2) DEFAULT NULL COMMENT '宇宙射线增长(%)',
    expected_arrival_earth DATE DEFAULT NULL COMMENT '宇宙射线到达地球预计日期',
    ionospheric_impact_observed BOOLEAN DEFAULT NULL COMMENT '是否观测到电离层影响',
    impact_description TEXT DEFAULT NULL COMMENT '影响描述',
    data_sources VARCHAR(500) DEFAULT NULL COMMENT '数据来源 (ASAS-SN/ATLAS等)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_sn_name (event_name)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(discovery_date) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 2. 伽马射线暴 (GRB) - 宇宙最强电磁辐射
CREATE TABLE IF NOT EXISTS gamma_ray_bursts (
    id BIGINT AUTO_INCREMENT,
    grb_name VARCHAR(30) NOT NULL COMMENT 'GRB编号 (如 GRB 221009A)',
    trigger_time DATETIME NOT NULL COMMENT '触发时间',
    duration_seconds DECIMAL(8,3) DEFAULT NULL COMMENT '持续时间 T90',
    fluence DECIMAL(12,6) DEFAULT NULL COMMENT '能流 (erg/cm²)',
    photon_energy_max DECIMAL(10,2) DEFAULT NULL COMMENT '最高光子能量 (GeV)',
    redshift DECIMAL(8,6) DEFAULT NULL COMMENT '红移',
    distance_mpc DECIMAL(12,4) DEFAULT NULL COMMENT '距离 (Mpc)',
    grb_type VARCHAR(10) DEFAULT NULL COMMENT '类型 (长暴/短暴)',
    afterglow_detected BOOLEAN DEFAULT FALSE COMMENT '是否探测到余辉',
    host_galaxy VARCHAR(100) DEFAULT NULL COMMENT '宿主星系',
    jet_angle_degrees DECIMAL(5,2) DEFAULT NULL COMMENT '喷流张角 (度)',
    isotropic_energy DECIMAL(15,4) DEFAULT NULL COMMENT '各向同性能量 (erg)',
    -- 地球影响
    ionospheric_perturbation_nT DECIMAL(8,2) DEFAULT NULL COMMENT '电离层扰动幅度 (nT)',
    vlf_phase_anomaly_observed BOOLEAN DEFAULT FALSE COMMENT '是否观测到VLF相位异常',
    vlf_amplitude_change_db DECIMAL(6,2) DEFAULT NULL COMMENT 'VLF幅度变化 (dB)',
    atmospheric_electric_field_change DECIMAL(8,2) DEFAULT NULL COMMENT '大气电场变化 (V/m)',
    d_region_ionization_increase VARCHAR(50) DEFAULT NULL COMMENT 'D层电离增强描述',
    -- 射电观测相关
    radio_afterglow_detected BOOLEAN DEFAULT FALSE COMMENT '射电余辉探测',
    radio_flux_density_mJy DECIMAL(8,2) DEFAULT NULL COMMENT '射电流量密度 (mJy)',
    radio_frequency_ghz DECIMAL(6,2) DEFAULT NULL COMMENT '射电频率 (GHz)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_grb_name (grb_name)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(trigger_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 3. 引力波事件 (LIGO/Virgo/KAGRA探测)
CREATE TABLE IF NOT EXISTS gravitational_waves (
    id BIGINT AUTO_INCREMENT,
    event_name VARCHAR(30) NOT NULL COMMENT '事件名称 (如 GW150914)',
    detection_time DATETIME NOT NULL COMMENT '探测时间 (UTC)',
    gw_type VARCHAR(20) DEFAULT NULL COMMENT '类型 (BBH/BNS/NSBH)',
    -- 并合天体参数
    mass_1_solar DECIMAL(8,2) DEFAULT NULL COMMENT '天体1质量 (太阳质量)',
    mass_2_solar DECIMAL(8,2) DEFAULT NULL COMMENT '天体2质量 (太阳质量)',
    final_mass_solar DECIMAL(8,2) DEFAULT NULL COMMENT '并合后质量 (太阳质量)',
    chirp_mass_solar DECIMAL(8,2) DEFAULT NULL COMMENT '啁啾质量 (太阳质量)',
    luminosity_distance_mpc DECIMAL(10,2) DEFAULT NULL COMMENT '光度距离 (Mpc)',
    redshift DECIMAL(8,6) DEFAULT NULL COMMENT '红移',
    sky_area_sq_deg DECIMAL(8,2) DEFAULT NULL COMMENT '定位天区面积 (平方度)',
    -- 探测详情
    detectors VARCHAR(100) DEFAULT NULL COMMENT '探测设备 (LIGO-H/LIGO-L/Virgo)',
    snr_combined DECIMAL(6,2) DEFAULT NULL COMMENT '信噪比',
    false_alarm_rate VARCHAR(50) DEFAULT NULL COMMENT '误报率',
    -- 电磁对应体
    em_counterpart_detected BOOLEAN DEFAULT FALSE COMMENT '是否探测到电磁对应体',
    kilonova_detected BOOLEAN DEFAULT FALSE COMMENT '是否探测到千新星',
    gamma_ray_burst_associated VARCHAR(30) DEFAULT NULL COMMENT '关联GRB',
    optical_counterpart_mag DECIMAL(5,2) DEFAULT NULL COMMENT '光学对应体星等',
    -- 射电观测
    radio_followup_attempted BOOLEAN DEFAULT FALSE COMMENT '是否尝试射电跟踪',
    radio_counterpart_detected BOOLEAN DEFAULT FALSE COMMENT '射电对应体探测',
    radio_flux_limit_mJy DECIMAL(8,2) DEFAULT NULL COMMENT '射电流量限制 (mJy)',
    -- 物理影响
    graviton_mass_limit_eV DECIMAL(10,6) DEFAULT NULL COMMENT '引力子质量限制 (eV)',
    speed_of_gw_c DECIMAL(10,9) DEFAULT NULL COMMENT '引力波速度 (c)',
    polarization VARCHAR(20) DEFAULT NULL COMMENT '偏振模式',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_gw_name (event_name)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(detection_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 4. 快速射电暴 (FRB) - 毫秒级宇宙射电信号
CREATE TABLE IF NOT EXISTS fast_radio_bursts (
    id BIGINT AUTO_INCREMENT,
    frb_name VARCHAR(30) NOT NULL COMMENT 'FRB编号 (如 FRB 20191221A)',
    detection_time DATETIME NOT NULL COMMENT '探测时间',
    telescope VARCHAR(50) DEFAULT NULL COMMENT '探测望远镜 (CHIME/Parkes等)',
    -- 观测参数
    dm_pc_cm3 DECIMAL(10,2) DEFAULT NULL COMMENT '色散量 (pc/cm³)',
    dm_excess DECIMAL(8,2) DEFAULT NULL COMMENT '色散超量 (来自银河系外)',
    fluence_jy_ms DECIMAL(10,4) DEFAULT NULL COMMENT '能流 (Jy·ms)',
    peak_flux_mJy DECIMAL(10,2) DEFAULT NULL COMMENT '峰值流量 (mJy)',
    width_ms DECIMAL(8,3) DEFAULT NULL COMMENT '爆发宽度 (ms)',
    central_frequency_mhz DECIMAL(8,2) DEFAULT NULL COMMENT '中心频率 (MHz)',
    bandwidth_mhz DECIMAL(6,2) DEFAULT NULL COMMENT '带宽 (MHz)',
    -- 位置信息
    ra_deg DECIMAL(10,6) DEFAULT NULL COMMENT '赤经 (度)',
    dec_deg DECIMAL(10,6) DEFAULT NULL COMMENT '赤纬 (度)',
    galactic_longitude DECIMAL(8,4) DEFAULT NULL COMMENT '银经 (度)',
    galactic_latitude DECIMAL(8,4) DEFAULT NULL COMMENT '银纬 (度)',
    sky_error_arcsec DECIMAL(8,2) DEFAULT NULL COMMENT '定位误差 (角秒)',
    -- 距离与宿主
    redshift DECIMAL(8,6) DEFAULT NULL COMMENT '红移',
    distance_mpc DECIMAL(12,4) DEFAULT NULL COMMENT '距离 (Mpc)',
    host_galaxy VARCHAR(100) DEFAULT NULL COMMENT '宿主星系',
    host_offset_arcsec DECIMAL(8,2) DEFAULT NULL COMMENT '与星系中心偏移 (角秒)',
    -- 重复暴
    is_repeater BOOLEAN DEFAULT FALSE COMMENT '是否重复FRB',
    repeater_name VARCHAR(30) DEFAULT NULL COMMENT '重复暴名称',
    burst_count INT DEFAULT 1 COMMENT '该源爆发次数',
    -- 物理参数
    isotropic_energy_erg DECIMAL(15,4) DEFAULT NULL COMMENT '各向同性能量 (erg)',
    magnetic_field_strength_g DECIMAL(10,4) DEFAULT NULL COMMENT '磁场强度 (G)',
    environment_density_cm3 DECIMAL(10,4) DEFAULT NULL COMMENT '环境密度 (cm⁻³)',
    -- 与已知源关联
    associated_pulsar VARCHAR(30) DEFAULT NULL COMMENT '关联脉冲星',
    associated_magnetar VARCHAR(30) DEFAULT NULL COMMENT '关联磁星',
    associated_gw_event VARCHAR(30) DEFAULT NULL COMMENT '关联引力波事件',
    -- 射电传播影响
    scintillation_timescale_ms DECIMAL(8,2) DEFAULT NULL COMMENT '闪烁时标 (ms)',
    scattering_time_ms DECIMAL(8,4) DEFAULT NULL COMMENT '散射时标 (ms)',
    rm_rad_m2 DECIMAL(10,2) DEFAULT NULL COMMENT '旋转测量 (rad/m²)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_frb_name (frb_name)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(detection_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 5. 太阳质子事件 (SPE) - 高能粒子影响
CREATE TABLE IF NOT EXISTS solar_proton_events (
    id BIGINT AUTO_INCREMENT,
    event_start DATETIME NOT NULL COMMENT '事件开始时间',
    event_end DATETIME DEFAULT NULL COMMENT '事件结束时间',
    proton_flux_peak DECIMAL(10,2) DEFAULT NULL COMMENT '峰值质子通量 (pfu)',
    proton_energy_mev DECIMAL(6,2) DEFAULT NULL COMMENT '质子能量 (MeV)',
    fluence_protons_cm2 DECIMAL(12,4) DEFAULT NULL COMMENT '积分通量 (protons/cm²)',
    event_category VARCHAR(10) DEFAULT NULL COMMENT '事件等级 (S1-S5)',
    associated_flare_class VARCHAR(5) DEFAULT NULL COMMENT '关联耀斑级别',
    associated_cme_speed DECIMAL(8,2) DEFAULT NULL COMMENT '关联CME速度 (km/s)',
    -- 地球影响
    ssc_observed BOOLEAN DEFAULT FALSE COMMENT '是否观测到急始磁暴',
    ssc_time DATETIME DEFAULT NULL COMMENT '急始时间',
    pcutoff_rigidity DECIMAL(6,2) DEFAULT NULL COMMENT '宇宙线截止刚度变化 (GV)',
    radiation_belt_enhancement BOOLEAN DEFAULT FALSE COMMENT '辐射带增强',
    satellite_anomalies INT DEFAULT 0 COMMENT '卫星异常事件数',
    hf_communication_blackout_hours DECIMAL(4,2) DEFAULT NULL COMMENT 'HF通信中断时长',
    polar_cap_absorption_db DECIMAL(6,2) DEFAULT NULL COMMENT '极盖吸收 (dB)',
    gps_scintillation_index DECIMAL(5,2) DEFAULT NULL COMMENT 'GPS闪烁指数',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_start) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 6. 银河系中心活动 (人马座A*)
CREATE TABLE IF NOT EXISTS galactic_center_activity (
    id BIGINT AUTO_INCREMENT,
    observation_time DATETIME NOT NULL COMMENT '观测时间',
    activity_type VARCHAR(50) DEFAULT NULL COMMENT '活动类型 (耀斑/爆发/宁静)',
    -- 多波段流量
    xray_flux_cgs DECIMAL(12,6) DEFAULT NULL COMMENT 'X射线流量 (erg/cm²/s)',
    infrared_flux_mJy DECIMAL(10,4) DEFAULT NULL COMMENT '红外流量 (mJy)',
    radio_flux_density_mJy DECIMAL(10,4) DEFAULT NULL COMMENT '射电流量 (mJy)',
    radio_frequency_ghz DECIMAL(6,2) DEFAULT NULL COMMENT '射电频率 (GHz)',
    -- 爆发参数
    flare_duration_hours DECIMAL(6,2) DEFAULT NULL COMMENT '耀斑持续时间 (小时)',
    flare_amplitude_factor DECIMAL(6,2) DEFAULT NULL COMMENT '耀斑幅度倍数',
    polarization_percent DECIMAL(5,2) DEFAULT NULL COMMENT '偏振度 (%)',
    -- 物理参数
    black_hole_mass_million_solar DECIMAL(6,2) DEFAULT 4.3 COMMENT '黑洞质量 (百万太阳质量)',
    accretion_rate_solar_per_year DECIMAL(10,6) DEFAULT NULL COMMENT '吸积率 (太阳质量/年)',
    jet_activity_observed BOOLEAN DEFAULT FALSE COMMENT '是否观测到喷流活动',
    -- 地球影响
    cosmic_ray_anisotropy_percent DECIMAL(6,2) DEFAULT NULL COMMENT '宇宙射线各向异性 (%)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(observation_time) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 7. 系外行星事件 (凌日/射电辐射)
CREATE TABLE IF NOT EXISTS exoplanet_events (
    id BIGINT AUTO_INCREMENT,
    planet_name VARCHAR(50) NOT NULL COMMENT '行星名称 (如 HD 189733b)',
    host_star VARCHAR(50) DEFAULT NULL COMMENT '宿主恒星',
    event_type VARCHAR(30) DEFAULT NULL COMMENT '事件类型 (凌日/射电爆发/磁层)',
    event_start DATETIME NOT NULL COMMENT '事件开始',
    event_end DATETIME DEFAULT NULL COMMENT '事件结束',
    -- 行星参数
    distance_ly DECIMAL(10,2) DEFAULT NULL COMMENT '距离 (光年)',
    orbital_period_days DECIMAL(10,4) DEFAULT NULL COMMENT '轨道周期 (天)',
    transit_depth_percent DECIMAL(6,4) DEFAULT NULL COMMENT '凌日深度 (%)',
    -- 射电特征
    radio_emission_detected BOOLEAN DEFAULT FALSE COMMENT '射电辐射探测',
    radio_frequency_mhz DECIMAL(8,2) DEFAULT NULL COMMENT '射电频率 (MHz)',
    radio_flux_density_mJy DECIMAL(8,2) DEFAULT NULL COMMENT '射电流量 (mJy)',
    cyclotron_maser_observed BOOLEAN DEFAULT FALSE COMMENT '回旋脉泽辐射',
    -- 恒星活动
    host_star_flare_observed BOOLEAN DEFAULT FALSE COMMENT '恒星耀斑',
    stellar_wind_interaction VARCHAR(200) DEFAULT NULL COMMENT '恒星风相互作用',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_start) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 8. 宇宙线异常事件 (Forbush下降等)
CREATE TABLE IF NOT EXISTS cosmic_ray_anomalies (
    id BIGINT AUTO_INCREMENT,
    event_start DATETIME NOT NULL COMMENT '事件开始时间',
    event_type VARCHAR(50) NOT NULL COMMENT '事件类型 (Forbush下降/地面增强)',
    station_name VARCHAR(50) DEFAULT NULL COMMENT '监测站',
    detector_type VARCHAR(50) DEFAULT NULL COMMENT '探测器类型 (中子 monitor/缪子)',
    -- 幅度参数
    amplitude_percent DECIMAL(6,2) DEFAULT NULL COMMENT '幅度变化 (%)',
    min_count_rate DECIMAL(10,2) DEFAULT NULL COMMENT '最小计数率',
    recovery_time_hours DECIMAL(6,2) DEFAULT NULL COMMENT '恢复时间 (小时)',
    -- 关联事件
    associated_cme BOOLEAN DEFAULT FALSE COMMENT '关联CME',
    associated_spe BOOLEAN DEFAULT FALSE COMMENT '关联太阳质子事件',
    associated_grb VARCHAR(30) DEFAULT NULL COMMENT '关联GRB',
    associated_supernova VARCHAR(50) DEFAULT NULL COMMENT '关联超新星',
    -- 地球影响
    ionization_change_percent DECIMAL(6,2) DEFAULT NULL COMMENT '电离层电离度变化 (%)',
    cloud_cover_correlation DECIMAL(5,2) DEFAULT NULL COMMENT '云量相关性',
    temperature_effect_observed BOOLEAN DEFAULT NULL COMMENT '是否观测到温度效应',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_start) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 9. 大尺度宇宙结构影响 (星系团/宇宙空洞)
CREATE TABLE IF NOT EXISTS large_scale_structure (
    id BIGINT AUTO_INCREMENT,
    structure_name VARCHAR(100) DEFAULT NULL COMMENT '结构名称',
    structure_type VARCHAR(50) DEFAULT NULL COMMENT '类型 (星系团/超星系团/空洞)',
    distance_mpc DECIMAL(10,2) DEFAULT NULL COMMENT '距离 (Mpc)',
    redshift DECIMAL(8,6) DEFAULT NULL COMMENT '红移',
    -- 射电特征
    radio_halo_detected BOOLEAN DEFAULT FALSE COMMENT '射电晕探测',
    radio_halo_luminosity_erg_s DECIMAL(15,4) DEFAULT NULL COMMENT '射电晕光度 (erg/s)',
    relic_detected BOOLEAN DEFAULT FALSE COMMENT '射电遗迹探测',
    mini_halo_detected BOOLEAN DEFAULT FALSE COMMENT '迷你晕探测',
    -- 物理参数
    mass_solar DECIMAL(15,2) DEFAULT NULL COMMENT '质量 (太阳质量)',
    temperature_kev DECIMAL(8,2) DEFAULT NULL COMMENT '温度 (keV)',
    xray_luminosity_erg_s DECIMAL(15,4) DEFAULT NULL COMMENT 'X射线光度 (erg/s)',
    -- 宇宙学
    baryon_fraction DECIMAL(6,4) DEFAULT NULL COMMENT '重子分数',
    dark_matter_fraction DECIMAL(6,4) DEFAULT NULL COMMENT '暗物质分数',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(structure_name) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- 10. 综合宇宙事件日志 (按时间排序的所有事件)
CREATE TABLE IF NOT EXISTS cosmic_event_timeline (
    id BIGINT AUTO_INCREMENT,
    event_time DATETIME NOT NULL COMMENT '事件时间',
    event_type VARCHAR(50) NOT NULL COMMENT '事件类型',
    event_name VARCHAR(100) NOT NULL COMMENT '事件名称',
    source_table VARCHAR(50) NOT NULL COMMENT '来源表名',
    source_id BIGINT NOT NULL COMMENT '来源表ID',
    significance_level VARCHAR(20) DEFAULT NULL COMMENT '重要级别 (高/中/低)',
    distance_mpc DECIMAL(12,4) DEFAULT NULL COMMENT '距离 (Mpc)',
    energy_erg DECIMAL(20,4) DEFAULT NULL COMMENT '能量 (erg)',
    impact_on_earth VARCHAR(200) DEFAULT NULL COMMENT '对地球影响',
    propagation_effect_expected VARCHAR(500) DEFAULT NULL COMMENT '预期传播效应',
    -- 关联QSO分析
    qso_during_event INT DEFAULT NULL COMMENT '事件期间QSO数',
    qso_success_rate_change DECIMAL(6,2) DEFAULT NULL COMMENT '成功率变化(%)',
    band_affected VARCHAR(50) DEFAULT NULL COMMENT '受影响波段',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_event_time (event_time),
    KEY idx_event_type (event_type)
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(event_time) BUCKETS 8
PROPERTIES ("replication_num" = "1");

-- 创建物化视图：宇宙事件与QSO关联统计
CREATE MATERIALIZED VIEW IF NOT EXISTS cosmic_event_qso_impact_mv
BUILD IMMEDIATE
REFRESH COMPLETE ON SCHEDULE EVERY 1 DAY
AS
SELECT 
    DATE(cet.event_time) as event_date,
    cet.event_type,
    cet.event_name,
    cet.significance_level,
    COUNT(q.id) as total_qso,
    COUNT(CASE WHEN q.distance > 5000 THEN 1 END) as dx_qso,
    AVG(q.distance) as avg_distance,
    AVG(CAST(q.rst_rcvd AS DECIMAL)) as avg_rst,
    -- 对比事件前后
    (SELECT COUNT(*) FROM qso_log q2 
     WHERE DATE(q2.qso_time) = DATE_SUB(DATE(cet.event_time), INTERVAL 1 DAY)
    ) as qso_prev_day,
    (SELECT COUNT(*) FROM qso_log q3 
     WHERE DATE(q3.qso_time) = DATE_ADD(DATE(cet.event_time), INTERVAL 1 DAY)
    ) as qso_next_day
FROM cosmic_event_timeline cet
LEFT JOIN qso_log q ON DATE(q.qso_time) = DATE(cet.event_time)
WHERE cet.event_time >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
GROUP BY DATE(cet.event_time), cet.event_type, cet.event_name, cet.significance_level;
