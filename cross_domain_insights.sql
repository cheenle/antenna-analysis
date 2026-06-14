-- =====================================================
-- 跨领域关联分析SQL查询集
-- 用于发现无线电传播与各领域的隐藏关联
-- =====================================================

-- -----------------------------------------------------
-- 1. 月相 vs 高频传播成功率 (EME影响/潮汐效应)
-- -----------------------------------------------------
SELECT 
    CASE 
        WHEN mp.moon_phase < 0.25 THEN '新月(0-25%)'
        WHEN mp.moon_phase < 0.5 THEN '上弦(25-50%)'
        WHEN mp.moon_phase < 0.75 THEN '满月(50-75%)'
        ELSE '下弦(75-100%)'
    END as moon_phase,
    COUNT(*) as total_qso,
    COUNT(DISTINCT q.callsign) as unique_stations,
    ROUND(AVG(q.distance), 0) as avg_distance_km,
    ROUND(AVG(CAST(q.rst_rcvd AS DECIMAL)), 1) as avg_signal_report,
    COUNT(CASE WHEN q.distance > 10000 THEN 1 END) as dx_qso_count,
    ROUND(100.0 * COUNT(CASE WHEN q.distance > 10000 THEN 1 END) / COUNT(*), 1) as dx_ratio_percent
FROM qso_log q
JOIN moon_position mp ON DATE(q.qso_time) = DATE(mp.observation_time)
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
GROUP BY moon_phase
ORDER BY FIELD(moon_phase, '新月(0-25%)', '上弦(25-50%)', '满月(50-75%)', '下弦(75-100%)');

-- -----------------------------------------------------
-- 2. 流星雨 vs 6米/2米波段通联成功率 (流星散射MS)
-- -----------------------------------------------------
SELECT 
    ms.shower_name as meteor_shower,
    ms.peak_date,
    ms.zhr as expected_zhr,
    DATE(ms.start_date) as shower_start,
    DATE(ms.end_date) as shower_end,
    COUNT(q.id) as ms_band_qso,
    COUNT(DISTINCT q.callsign) as unique_calls,
    ROUND(AVG(q.distance), 0) as avg_distance_km
FROM meteor_shower ms
LEFT JOIN qso_log q ON 
    DATE(q.qso_time) BETWEEN ms.start_date AND ms.end_date
    AND q.band IN ('6m', '2m', '70cm')
WHERE ms.peak_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
GROUP BY ms.shower_name, ms.peak_date, ms.zhr, ms.start_date, ms.end_date
ORDER BY ms.peak_date;

-- -----------------------------------------------------
-- 3. 空间天气综合影响分析 (多因素关联)
-- -----------------------------------------------------
SELECT 
    DATE(q.qso_time) as qso_date,
    COUNT(*) as daily_qso,
    -- 太阳活动
    sa.f107_flux,
    CASE 
        WHEN sa.f107_flux > 150 THEN '高太阳活动'
        WHEN sa.f107_flux >= 100 THEN '中太阳活动'
        ELSE '低太阳活动'
    END as solar_level,
    -- 地磁活动
    AVG(gi.kp_value) as avg_kp,
    MAX(CASE WHEN gi.storm_level != 'G0' THEN 1 ELSE 0 END) as had_storm,
    -- 太阳风
    AVG(sw.bz) as avg_bz,
    MIN(sw.bz) as min_bz,
    -- 月球
    AVG(mp.moon_elevation) as avg_moon_elevation,
    -- QSO质量
    ROUND(AVG(q.distance), 0) as avg_distance,
    COUNT(CASE WHEN q.distance > 10000 THEN 1 END) as dx_count
FROM qso_log q
LEFT JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
LEFT JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
LEFT JOIN solar_wind sw ON DATE_FORMAT(q.qso_time, '%Y-%m-%d %H') = DATE_FORMAT(sw.measurement_time, '%Y-%m-%d %H')
LEFT JOIN moon_position mp ON DATE(q.qso_time) = DATE(mp.observation_time)
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY DATE(q.qso_time), sa.f107_flux
ORDER BY qso_date DESC;

-- -----------------------------------------------------
-- 4. 节假日/竞赛活动 vs 通联活跃度
-- -----------------------------------------------------
SELECT 
    ha.event_name,
    ha.event_type,
    ha.event_date,
    ha.activity_level as expected_activity,
    COUNT(q.id) as actual_qso,
    COUNT(DISTINCT q.callsign) as unique_calls,
    COUNT(DISTINCT q.band) as bands_used,
    ROUND(AVG(q.distance), 0) as avg_distance,
    -- 对比前后3天平均值
    (SELECT COUNT(*) FROM qso_log q2 
     WHERE DATE(q2.qso_time) BETWEEN DATE_SUB(ha.event_date, INTERVAL 3 DAY) AND DATE_SUB(ha.event_date, INTERVAL 1 DAY)
    ) as avg_3days_before,
    (SELECT COUNT(*) FROM qso_log q3 
     WHERE DATE(q3.qso_time) BETWEEN DATE_ADD(ha.event_date, INTERVAL 1 DAY) AND DATE_ADD(ha.event_date, INTERVAL 3 DAY)
    ) as avg_3days_after
FROM human_activity ha
LEFT JOIN qso_log q ON DATE(q.qso_time) = ha.event_date
WHERE ha.event_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
GROUP BY ha.event_name, ha.event_type, ha.event_date, ha.activity_level
ORDER BY actual_qso DESC;

-- -----------------------------------------------------
-- 5. 气象因素 vs 信号质量 (气压/湿度影响)
-- -----------------------------------------------------
SELECT 
    CASE 
        WHEN wd.pressure < 1000 THEN '低压(<1000)'
        WHEN wd.pressure < 1020 THEN '常压(1000-1020)'
        ELSE '高压(>1020)'
    END as pressure_level,
    CASE 
        WHEN wd.humidity < 40 THEN '干燥(<40%)'
        WHEN wd.humidity < 70 THEN '适中(40-70%)'
        ELSE '潮湿(>70%)'
    END as humidity_level,
    COUNT(*) as qso_count,
    ROUND(AVG(CAST(q.rst_rcvd AS DECIMAL)), 1) as avg_rst,
    ROUND(AVG(q.distance), 0) as avg_distance,
    ROUND(STDDEV(q.distance), 0) as distance_stddev
FROM qso_log q
JOIN weather_data wd ON DATE(q.qso_time) = DATE(wd.observation_time)
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY pressure_level, humidity_level
ORDER BY qso_count DESC;

-- -----------------------------------------------------
-- 6. 大气环流指数(NAO) vs 跨大西洋传播
-- -----------------------------------------------------
SELECT 
    ai.index_date,
    ai.index_type,
    ai.index_value,
    ai.phase,
    COUNT(q.id) as qso_count,
    COUNT(CASE WHEN q.country IN ('United States', 'Canada', 'Brazil', 'Argentina') THEN 1 END) as americas_qso,
    COUNT(CASE WHEN q.country IN ('England', 'Germany', 'France', 'Italy', 'Spain') THEN 1 END) as europe_qso,
    ROUND(AVG(CASE WHEN q.distance > 5000 THEN q.distance END), 0) as avg_long_distance
FROM atmospheric_indices ai
LEFT JOIN qso_log q ON ai.index_date = DATE(q.qso_time)
WHERE ai.index_type = 'NAO'
  AND ai.index_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
GROUP BY ai.index_date, ai.index_type, ai.index_value, ai.phase
ORDER BY ai.index_date DESC;

-- -----------------------------------------------------
-- 7. 日出日落(Gray Line)效应分析
-- -----------------------------------------------------
SELECT 
    CASE 
        WHEN ABS(TIME_TO_SEC(TIME(q.qso_time)) - TIME_TO_SEC(TIME(ss.sunrise_time))) < 3600 THEN '日出前后1h'
        WHEN ABS(TIME_TO_SEC(TIME(q.qso_time)) - TIME_TO_SEC(TIME(ss.sunset_time))) < 3600 THEN '日落前后1h'
        WHEN TIME(q.qso_time) BETWEEN '10:00:00' AND '14:00:00' THEN '正午时段'
        WHEN TIME(q.qso_time) BETWEEN '22:00:00' AND '02:00:00' THEN '午夜时段'
        ELSE '其他时段'
    END as time_category,
    COUNT(*) as qso_count,
    COUNT(DISTINCT q.callsign) as unique_calls,
    ROUND(AVG(q.distance), 0) as avg_distance,
    COUNT(CASE WHEN q.distance > 8000 THEN 1 END) as grayline_dx_count
FROM qso_log q
JOIN sunrise_sunset ss ON DATE(q.qso_time) = ss.location_date
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY time_category
ORDER BY FIELD(time_category, '日出前后1h', '日落前后1h', '正午时段', '午夜时段', '其他时段');

-- -----------------------------------------------------
-- 8. 综合传播评分 (多维度打分)
-- ----------------------------------------------------
SELECT 
    DATE(q.qso_time) as date,
    COUNT(*) as total_qso,
    -- 太阳活动评分 (0-100)
    LEAST(100, GREATEST(0, (sa.f107_flux - 70) / 130 * 100)) as solar_score,
    -- 地磁活动评分 (0-100, 越高越好)
    LEAST(100, GREATEST(0, (9 - COALESCE(AVG(gi.kp_value), 5)) / 9 * 100)) as geomag_score,
    -- QSO活跃度评分
    LEAST(100, COUNT(*) / 50 * 100) as activity_score,
    -- 综合传播指数 (CPI)
    ROUND((
        LEAST(100, GREATEST(0, (sa.f107_flux - 70) / 130 * 100)) * 0.4 +
        LEAST(100, GREATEST(0, (9 - COALESCE(AVG(gi.kp_value), 5)) / 9 * 100)) * 0.3 +
        LEAST(100, COUNT(*) / 50 * 100) * 0.3
    ), 1) as composite_propagation_index
FROM qso_log q
LEFT JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
LEFT JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY DATE(q.qso_time), sa.f107_flux
HAVING total_qso > 10
ORDER BY composite_propagation_index DESC
LIMIT 10;

-- -----------------------------------------------------
-- 9. 雷电活动 vs 噪声水平(通过RST推断)
-- -----------------------------------------------------
SELECT 
    CASE 
        WHEN ld.distance_from_station < 50 THEN '<50km'
        WHEN ld.distance_from_station < 100 THEN '50-100km'
        WHEN ld.distance_from_station < 200 THEN '100-200km'
        ELSE '>200km'
    END as lightning_distance,
    COUNT(*) as strike_count,
    AVG(ld.intensity) as avg_intensity,
    -- 找到同时段的QSO
    (SELECT ROUND(AVG(CAST(q.rst_rcvd AS DECIMAL)), 1) 
     FROM qso_log q 
     WHERE DATE(q.qso_time) = DATE(ld.strike_time)
     AND ABS(TIME_TO_SEC(TIME(q.qso_time)) - TIME_TO_SEC(TIME(ld.strike_time))) < 1800
    ) as nearby_qso_rst
FROM lightning_data ld
WHERE ld.strike_time >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
GROUP BY lightning_distance
ORDER BY lightning_distance;

-- -----------------------------------------------------
-- 10. 宇宙射线 vs 电离层扰动(通过通联成功率)
-- -----------------------------------------------------
SELECT 
    DATE(cr.measurement_time) as date,
    ROUND(AVG(cr.neutron_count), 0) as avg_neutron_count,
    COUNT(q.id) as qso_count,
    ROUND(AVG(q.distance), 0) as avg_distance,
    COUNT(CASE WHEN q.distance > 5000 THEN 1 END) as long_distance_qso,
    -- 计算Forbush下降期间(宇宙射线减少)的QSO变化
    LAG(COUNT(q.id)) OVER (ORDER BY DATE(cr.measurement_time)) as prev_day_qso
FROM cosmic_rays cr
LEFT JOIN qso_log q ON DATE(cr.measurement_time) = DATE(q.qso_time)
WHERE cr.measurement_time >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY DATE(cr.measurement_time)
ORDER BY date DESC;
