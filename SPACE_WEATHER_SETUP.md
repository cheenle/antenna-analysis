# 空间天气数据整合 - 快速设置指南

## 概述

本模块将空间天气数据（太阳活动、地磁指数、太阳风、电离层参数）与 PSK Reporter 无线电数据进行整合，支持横向分析和传播预测。

## 已创建的文件

| 文件 | 用途 |
|------|------|
| `space_weather_schema.sql` | 数据库表结构定义（6个表 + 2个物化视图） |
| `space_weather_fetcher.py` | 数据获取脚本（从多个数据源自动获取） |
| `space_weather_visualizer.py` | 可视化分析工具（生成HTML报告和JSON导出） |
| `SPACE_WEATHER_ANALYSIS.md` | 详细分析指南（包含SQL查询示例和分析方法） |
| `SPACE_WEATHER_SETUP.md` | 本文件 - 快速设置指南 |

## 快速开始

### 1. 初始化数据库

```bash
# 连接到StarRocks数据库
mysql -h ham.vlsc.net -P 9030 -u root pskreporter

# 或在命令行直接执行
mysql -h ham.vlsc.net -P 9030 -u root pskreporter < space_weather_schema.sql
```

这将创建以下数据表：
- `solar_activity` - 太阳活动数据（太阳黑子、F10.7等）
- `solar_wind` - 太阳风实时数据
- `geomagnetic_indices` - 地磁指数（Kp、Dst等）
- `ionosphere_data` - 电离层参数
- `sunrise_sunset` - 日出日落时间
- `space_weather_daily` - 每日摘要

### 2. 获取空间天气数据

```bash
# 获取最近7天的数据
python3 space_weather_fetcher.py

# 获取最近30天的数据
python3 space_weather_fetcher.py --days 30

# 仅获取，不保存到数据库（测试用）
python3 space_weather_fetcher.py --days 7 --no-db
```

### 3. 生成可视化报告

```bash
# 生成HTML可视化报告
python3 space_weather_visualizer.py --html --days 30

# 导出JSON数据
python3 space_weather_visualizer.py --json --days 90

# 同时生成两种格式
python3 space_weather_visualizer.py --html --json --days 30

# 指定输出目录
python3 space_weather_visualizer.py --html --output ./reports
```

报告将保存在 `visualizations/` 目录（可自定义）。

## 数据源说明

| 数据类型 | 来源 | 更新频率 | 数据延迟 |
|---------|------|---------|---------|
| 太阳黑子数 (SSN) | SIDC (比利时) | 日 | 1天 |
| F10.7 射电通量 | NOAA SWPC | 日 | 1天 |
| 太阳风 (速度/Bz) | NOAA DSCOVR | 1分钟 | 实时 |
| Kp 地磁指数 | GFZ Potsdam | 3小时 | 3小时 |
| Dst 地磁指数 | WDC Kyoto | 1小时 | 1小时 |
| 日出日落 | 本地计算 | 日 | 无 |

## 核心关联分析

### 1. 太阳活动与波段传播

```sql
-- 查看不同太阳活动水平下的QSO分布
SELECT 
    CASE 
        WHEN sa.f107_flux < 80 THEN '低活动期'
        WHEN sa.f107_flux < 120 THEN '中活动期'
        ELSE '高活动期'
    END as solar_activity,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.distance) as avg_distance
FROM qso_log q
JOIN solar_activity sa ON DATE(q.qso_time) = sa.observation_date
WHERE sa.observation_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
GROUP BY solar_activity, q.band
ORDER BY FIELD(solar_activity, '高活动期', '中活动期', '低活动期'),
         FIELD(q.band, '20m', '15m', '10m', '40m', '80m');
```

### 2. 地磁暴影响分析

```sql
-- 分析地磁暴期间的传播质量变化
SELECT 
    gi.storm_level,
    gi.storm_description,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.snr) as avg_snr,
    COUNT(DISTINCT q.country) as countries
FROM qso_log q
JOIN geomagnetic_indices gi ON DATE(q.qso_time) = gi.measurement_date
WHERE gi.storm_level != 'G0'
GROUP BY gi.storm_level, gi.storm_description, q.band;
```

### 3. 实时太阳风与信号质量

```sql
-- 分析Bz分量（南向磁场）对接收信号的影响
SELECT 
    CASE 
        WHEN sw.bz < -10 THEN '强南向'
        WHEN sw.bz < -5 THEN '南向'
        WHEN sw.bz < 0 THEN '弱南向'
        ELSE '北向'
    END as bz_direction,
    HOUR(rr.qso_time) as hour_utc,
    COUNT(*) as records,
    AVG(rr.snr) as avg_snr
FROM receiver_records rr
JOIN solar_wind sw ON DATE_FORMAT(rr.qso_time, '%Y-%m-%d %H:00:00') = 
    DATE_FORMAT(sw.measurement_time, '%Y-%m-%d %H:00:00')
WHERE rr.qso_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY bz_direction, HOUR(rr.qso_time);
```

### 4. Gray Line传播效应

```sql
-- 分析日出日落时段的传播增强
SELECT 
    CASE 
        WHEN ABS(TIMESTAMPDIFF(MINUTE, q.qso_time, ss.sunrise_time)) <= 30 THEN '日出前后'
        WHEN ABS(TIMESTAMPDIFF(MINUTE, q.qso_time, ss.sunset_time)) <= 30 THEN '日落前后'
        ELSE '其他时间'
    END as gray_line,
    q.band,
    COUNT(*) as qso_count,
    AVG(q.distance) as avg_distance
FROM qso_log q
JOIN sunrise_sunset ss ON DATE(q.qso_time) = ss.location_date
WHERE q.qso_time >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
GROUP BY gray_line, q.band
HAVING gray_line != '其他时间';
```

## 传播规律总结

### 太阳活动影响

| F10.7 通量 | 传播条件 | 推荐波段 |
|-----------|---------|---------|
| >150 | 优秀 | 15m, 12m, 10m, 6m |
| 100-150 | 良好 | 20m, 17m, 15m |
| 70-100 | 一般 | 30m, 20m, 17m |
| <70 | 较差 | 40m, 80m, 160m |

### 地磁活动影响

| Kp 指数 | 等级 | 传播影响 |
|--------|------|---------|
| 0-2 | 平静 | 所有波段正常 |
| 3 | 不稳定 | 高纬路径受影响 |
| 4-5 | 活跃 | 极光吸收增加 |
| 6-7 | 磁暴 | 高波段中断 |
| 8-9 | 强磁暴 | 低波段噪声增大 |

### 昼夜变化

| 时段 | D层 | F层 | 最佳波段 |
|------|-----|-----|---------|
| 白天 | 强 | F1+F2 | 20m-10m |
| 黄昏 | 消失 | 合并 | Gray Line全波段 |
| 夜间 | 无 | F2 | 80m-40m |

## 定时任务设置

建议将数据获取加入crontab：

```bash
# 编辑crontab
crontab -e

# 添加以下任务（每小时获取一次太阳风数据，每天获取一次其他数据）
# 太阳风数据（高频更新）
0 * * * * cd /Users/cheenle/pskreporter && /usr/bin/python3 space_weather_fetcher.py --days 1 >> logs/spaceweather.log 2>&1

# 完整数据更新（每天一次）
0 6 * * * cd /Users/cheenle/pskreporter && /usr/bin/python3 space_weather_fetcher.py --days 7 >> logs/spaceweather.log 2>&1

# 生成周报（每周一早上）
0 8 * * 1 cd /Users/cheenle/pskreporter && /usr/bin/python3 space_weather_visualizer.py --html --days 7 >> logs/viz.log 2>&1
```

## 扩展建议

### 1. 添加更多数据源

- **电离层垂直探测**: 集成foF2/MUF数据
- **GNSS TEC**: 总电子含量数据
- **极光椭圆**: OVATION模型数据
- **太阳图像**: SDO/AIA实时图像

### 2. 机器学习应用

```python
# 预测最佳传播窗口
# 输入: 时间、波段、目标区域、当前空间天气
# 输出: 传播概率预测

# 使用随机森林或LSTM模型
# 特征: F10.7, Kp, Bz, 太阳风速度, 本地时间
# 标签: QSO成功率, 平均SNR
```

### 3. 警报系统

- 太阳耀斑警报 → 预计10-30分钟后D层吸收增加
- 磁暴警报 → Kp>5时高纬路径警告
- CME到达 → 太阳风速度突增预警

## 常见问题

### Q: 为什么有些数据获取失败？

A: 可能原因：
- 数据源临时不可用（检查网络）
- API限流（减少请求频率）
- 数据源格式变化（需要更新解析代码）

### Q: 如何提高数据精度？

A: 建议：
- 使用电离层观测站实时foF2数据
- 添加本地SDR监测（连续记录背景噪声）
- 集成RBN（Reverse Beacon Network）数据

### Q: 如何验证分析结果？

A: 方法：
- 对比不同太阳周期历史数据
- A/B测试（高/低活动期传播对比）
- 与其他HAM的观测结果交叉验证

## 参考资源

- **NOAA SWPC**: https://www.swpc.noaa.gov/
- **SIDC 太阳黑子**: http://www.sidc.be/silso/
- **GFZ Kp指数**: https://kp.gfz-potsdam.de/
- **WDC Kyoto Dst**: https://wdc.kugi.kyoto-u.ac.jp/
- **NASA CCMC**: https://ccmc.gsfc.nasa.gov/
- **HAM Radio Science**: https://hamsci.org/
