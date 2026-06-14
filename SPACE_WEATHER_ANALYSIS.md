# 空间天气与短波传播横向分析指南

## 概述

本文档描述如何将空间天气数据（太阳活动、地磁指数、太阳风、电离层参数）与 PSK Reporter 无线电数据进行关联分析，以研究传播规律。

## 空间天气参数与短波传播的关系

### 1. 太阳活动指标

| 参数 | 影响机制 | 传播效应 |
|------|---------|---------|
| **太阳黑子数 (SSN)** | 反映太阳活动水平，与EUV辐射正相关 | 影响F2层电子密度，高SSN → 高频传播改善 |
| **F10.7 通量** | 10.7cm射电辐射，与EUV强相关 | 更好的电离层电离指标，高F10.7 → MUF升高 |
| **太阳耀斑 (X射线)** | 增强D层电离 | 突然电离层扰动(SID)，短波吸收增加 |

**传播规律:**
- SSN > 100: 高波段(20m/15m/10m)传播良好
- SSN < 50: 低波段(40m/80m)更可靠
- 太阳耀斑期间: D层吸收增加，10-20m暂时中断

### 2. 地磁活动指标

| 参数 | 范围 | 影响机制 |
|------|------|---------|
| **Kp指数** | 0-9 | 3小时行星地磁活动指数 |
| **Dst指数** | -300~+50 nT | 环电流强度，负值表示磁暴 |
| **Ap指数** | 0-400 | 日平均地磁活动 |

**传播规律:**
- Kp < 3 (G0): 平静条件，传播稳定
- Kp 3-4 (G1): 小扰动，高纬路径受影响
- Kp 5-6 (G2-G3): 中等磁暴，极光吸收增加
- Kp > 7 (G4-G5): 强磁暴，高波段中断，低波段噪声增加

**地理差异:**
- 高纬度(>50°): 地磁活动影响更显著
- 中纬度(30-50°): 中等敏感
- 低纬度(<30°): 相对不受影响

### 3. 太阳风参数

| 参数 | 单位 | 典型值 | 异常影响 |
|------|------|--------|---------|
| **太阳风速度** | km/s | 300-500 | >600 km/s 增加地磁活动 |
| **Bz分量** | nT | ±5 | 南向Bz(<-5nT)引发磁暴 |
| **质子密度** | n/cm³ | 5-10 | 与CME相关 |
| **动压** | nPa | 1-3 | 高动压压缩磁层 |

**传播影响:**
- 南向Bz + 高速太阳风 → 磁暴 → 极光吸收 → 高纬路径中断
- CME到达 → 突然压缩 → 地磁急始(SSC) → 传播闪烁

### 4. 电离层参数

| 参数 | 单位 | 传播意义 |
|------|------|---------|
| **foF2** | MHz | F2层临界频率，决定MUF |
| **MUF** | MHz | 最高可用频率，超过此频率无法反射 |
| **TEC** | TECU | 总电子含量，影响相位和时延 |

**传播规律:**
- MUF > 工作频率: 天波传播可能
- MUF < 工作频率: 穿透电离层，无法传播
- TEC变化: 导致信号衰落和多径效应

### 5. 昼夜变化

| 时段 | D层 | E层 | F层 | 传播特点 |
|------|-----|-----|-----|---------|
| **白天** | 强烈电离 | 存在 | 分层 | 低波段吸收，高波段可用 |
| **黄昏** | 衰减 | 消失 | 合并 | Gray line传播，跨昼夜路径 |
| **夜间** | 消失 | 消失 | F2主导 | 低波段可用，高波段依赖F2 |

**Gray Line效应:**
- 日出/日落前后30-60分钟
- D层吸收最小，F层仍电离
- 跨昼夜路径（东→西或西→东）传播增强

## 数据库关联查询示例

### 1. 太阳活动与传播成功率关联

```sql
-- 分析太阳黑子数与不同波段QSO数量的关系
SELECT 
    CASE 
        WHEN sa.sunspot_number < 50 THEN '低 (0-50)'
        WHEN sa.sunspot_number < 100 THEN '中 (50-100)'
        WHEN sa.sunspot_number < 150 THEN '高 (100-150)'
        ELSE '极高 (150+)'
    END as ssn_range,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.distance) as avg_distance,
    AVG(CASE WHEN q.snr > -10 THEN 1 ELSE 0 END) as good_snr_rate
FROM qso_log q
JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
WHERE sa.observation_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
GROUP BY ssn_range, q.band
ORDER BY FIELD(ssn_range, '低 (0-50)', '中 (50-100)', '高 (100-150)', '极高 (150+)'), 
         FIELD(q.band, '160m', '80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m');
```

### 2. 地磁暴期间的传播变化

```sql
-- 分析地磁暴期间传播质量变化
SELECT 
    gi.storm_level,
    gi.kp_value,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.snr) as avg_snr,
    AVG(q.distance) as avg_distance,
    COUNT(DISTINCT q.country) as unique_countries
FROM qso_log q
JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
WHERE gi.storm_level != 'G0'
  AND q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
GROUP BY gi.storm_level, gi.kp_value, q.band
ORDER BY gi.kp_value DESC, FIELD(q.band, '20m', '17m', '15m', '12m', '10m', '40m', '80m');
```

### 3. 太阳风Bz与信号质量实时关联

```sql
-- 分析Bz分量与接收信号强度的关系
SELECT 
    CASE 
        WHEN sw.bz < -10 THEN '强南向 (<-10)'
        WHEN sw.bz < -5 THEN '南向 (-10 to -5)'
        WHEN sw.bz < 0 THEN '弱南向 (-5 to 0)'
        WHEN sw.bz < 5 THEN '弱北向 (0 to 5)'
        ELSE '北向 (>5)'
    END as bz_range,
    HOUR(rr.qso_time) as hour_utc,
    COUNT(*) as record_count,
    AVG(rr.snr) as avg_snr,
    STDDEV(rr.snr) as snr_std
FROM receiver_records rr
JOIN solar_wind sw ON DATE_FORMAT(rr.qso_time, '%Y-%m-%d %H:00:00') = 
    DATE_FORMAT(sw.measurement_time, '%Y-%m-%d %H:00:00')
WHERE rr.qso_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY bz_range, HOUR(rr.qso_time)
ORDER BY hour_utc, FIELD(bz_range, '强南向 (<-10)', '南向 (-10 to -5)', 
                          '弱南向 (-5 to 0)', '弱北向 (0 to 5)', '北向 (>5)');
```

### 4. Gray Line传播分析

```sql
-- 分析日出日落时段的传播增强效应
SELECT 
    CASE 
        WHEN ABS(TIMESTAMPDIFF(MINUTE, q.qso_time, 
            STR_TO_DATE(CONCAT(DATE(q.qso_time), ' ', TIME(ss.sunrise_time)), 
                       '%Y-%m-%d %H:%i:%s'))) <= 30 THEN '日出前后30分钟'
        WHEN ABS(TIMESTAMPDIFF(MINUTE, q.qso_time, 
            STR_TO_DATE(CONCAT(DATE(q.qso_time), ' ', TIME(ss.sunset_time)), 
                       '%Y-%m-%d %H:%i:%s'))) <= 30 THEN '日落前后30分钟'
        ELSE '其他时间'
    END as gray_line_period,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.distance) as avg_distance,
    AVG(q.snr) as avg_snr
FROM qso_log q
JOIN sunrise_sunset ss ON DATE(q.qso_time) = ss.location_date
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
GROUP BY gray_line_period, q.band
HAVING gray_line_period != '其他时间'
ORDER BY FIELD(gray_line_period, '日出前后30分钟', '日落前后30分钟'), 
         FIELD(q.band, '160m', '80m', '40m', '30m', '20m', '17m', '15m', '12m', '10m');
```

### 5. 综合传播条件评分

```sql
-- 创建传播条件综合评分视图
CREATE VIEW propagation_score AS
SELECT 
    sa.observation_date,
    -- 太阳活动评分 (0-40分)
    LEAST(sa.f107_flux / 5, 40) as solar_score,
    
    -- 地磁活动评分 (0-40分，平静=40，暴=0)
    CASE 
        WHEN gi.kp_value < 3 THEN 40
        WHEN gi.kp_value < 5 THEN 40 - (gi.kp_value - 3) * 10
        ELSE 0
    END as geomag_score,
    
    -- 电离层评分 (基于foF2，0-20分)
    LEAST(id.fof2 / 2, 20) as iono_score,
    
    -- 综合评分
    LEAST(sa.f107_flux / 5, 40) + 
    CASE 
        WHEN gi.kp_value < 3 THEN 40
        WHEN gi.kp_value < 5 THEN 40 - (gi.kp_value - 3) * 10
        ELSE 0
    END + 
    LEAST(COALESCE(id.fof2, 10) / 2, 20) as total_score,
    
    -- 评级
    CASE 
        WHEN sa.f107_flux > 150 AND gi.kp_value < 3 THEN '优秀'
        WHEN sa.f107_flux > 100 AND gi.kp_value < 4 THEN '良好'
        WHEN sa.f107_flux > 70 AND gi.kp_value < 5 THEN '一般'
        ELSE '较差'
    END as propagation_rating
    
FROM solar_activity sa
LEFT JOIN geomagnetic_indices gi ON sa.observation_date = gi.measurement_date
LEFT JOIN (
    SELECT observation_date, AVG(fof2) as fof2
    FROM ionosphere_data
    GROUP BY observation_date
) id ON sa.observation_date = id.observation_date;

-- 查询传播条件与QSO成功率
SELECT 
    ps.propagation_rating,
    COUNT(q.id) as qso_count,
    AVG(q.distance) as avg_distance,
    AVG(q.snr) as avg_snr
FROM propagation_score ps
LEFT JOIN qso_log q ON ps.observation_date = DATE(q.qso_time)
WHERE ps.observation_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
GROUP BY ps.propagation_rating
ORDER BY FIELD(ps.propagation_rating, '优秀', '良好', '一般', '较差');
```

## 预测模型思路

### 1. MUF预测

基于以下参数预测MUF:
- 太阳天顶角
- F10.7通量 (代表EUV辐射)
- 地磁活动水平
- 季节

```python
# 简化MUF预测公式示例
def predict_muf(fof2, latitude, month, f107):
    """
    基于foF2预测MUF
    MUF = foF2 * M(距离, 入射角)
    """
    # 基本M因子 (3000km路径)
    m_factor = 3.0  # 简化为常数，实际与距离和入射角相关
    
    # 季节修正 (夏季F2层更高)
    seasonal_factor = 1 + 0.1 * math.cos((month - 6) * math.pi / 6)
    
    # 太阳活动修正
    solar_factor = 1 + (f107 - 100) / 500
    
    return fof2 * m_factor * seasonal_factor * solar_factor
```

### 2. 传播概率预测

```sql
-- 基于历史数据建立传播概率模型
CREATE TABLE propagation_probability AS
SELECT 
    band,
    target_region,
    hour_utc,
    CASE 
        WHEN sa.f107_flux < 80 THEN 'low'
        WHEN sa.f107_flux < 120 THEN 'medium'
        ELSE 'high'
    END as solar_level,
    CASE 
        WHEN gi.kp_value < 3 THEN 'quiet'
        WHEN gi.kp_value < 5 THEN 'active'
        ELSE 'storm'
    END as geomag_level,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_qsos,
    AVG(snr) as avg_snr
FROM (
    SELECT 
        q.*,
        CASE 
            WHEN q.distance < 1000 THEN 'near'
            WHEN q.distance < 5000 THEN 'mid'
            ELSE 'long'
        END as target_region,
        HOUR(q.qso_time) as hour_utc,
        1 as success
    FROM qso_log q
) q
JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
GROUP BY band, target_region, hour_utc, solar_level, geomag_level;
```

## 数据获取频率建议

| 数据类型 | 更新频率 | 历史数据 | 实时延迟 |
|---------|---------|---------|---------|
| 太阳黑子数 | 日 | 每日更新 | 1天 |
| F10.7通量 | 日 | 每日更新 | 1天 |
| 太阳风 | 1分钟 | 7天 | 实时 |
| Kp指数 | 3小时 | 实时+预报 | 3小时 |
| Dst指数 | 1小时 | 实时+预报 | 1小时 |
| 电离层 | 15分钟 | 实时 | 15分钟 |
| 日出日落 | 日 | 计算 | 无 |

## 可视化建议

### 1. 多层时间序列图
- X轴: 时间
- Y轴1: QSO数量/SNR
- Y轴2: Kp/Dst
- Y轴3: F10.7

### 2. 散点图矩阵
- X: F10.7, Y: QSO成功率
- 颜色: 波段
- 大小: 距离

### 3. 热力图
- X: 时间(小时)
- Y: 日期
- 颜色: 传播质量评分

## 进一步研究方向

1. **机器学习预测**: 使用随机森林/LSTM预测最佳传播窗口
2. **路径分析**: 结合大圆路径与地磁纬度分析传播特性
3. **季节性模式**: 分析年变化和11年太阳周期影响
4. **事件研究**: 特定耀斑/磁暴事件的传播响应
5. **多站对比**: 不同地理位置电台的传播差异
