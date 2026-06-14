# PSK Reporter 传播分析系统 — 规格说明书 (SDD)

> **文档性质**：本文档采用规格驱动开发 (Spec-Driven Development) 结构，从既有代码库
> 反推出系统的需求规格、设计契约与组件职责，作为后续开发、维护与评审的单一参照。
>
> **适用版本**：StarRocks 后端 + Flask Web 应用 + 28 个 Python 模块 + 43 个 HTTP 路由。
> **主呼号**：BG1SB（`config.json` 可配）。
> **最后核对**：基于 `web_app.py` (3907 行)、`init.sql`、`band_utils.py`、`config.json` 实测。

---

## 1. 系统概述 (Overview)

### 1.1 一句话定义
一个面向业余无线电 (HAM) 的**信号传播分析系统**：把 PSK Reporter 上几十万条 FT8/数字模式
通联报告，连同 WSJT-X/JTDX 本地通联日志和空间天气数据，汇入 StarRocks 列存数据库，
通过 Flask Web 应用提供地图可视化、统计分析、DXCC 进度追踪，以及**用大数据反推天线
硬件性能**的深度分析能力。

### 1.2 核心价值主张
- **无仪器天线诊断**：不依赖任何测量设备，仅凭天上飞过的 FT8 信号报告，反推天线的
  辐射方向图、主瓣指向、定向/全向特征、各波段最佳仰角。
- **同城横向对比**：以同网格 (Maidenhead grid) 邻居电台为基准，计算 ΔSNR，定位本站
  天线在哪个方位、哪个波段存在短板。
- **跨域关联**：把空间天气（太阳黑子、地磁 Kp、电离层 foF2）与传播质量关联分析。

### 1.3 系统边界
| 在范围内 | 不在范围内 |
|---------|-----------|
| 数据采集、存储、查询、可视化、分析 | 控制电台硬件 / 发射 |
| 历史数据 (2025) + 准实时数据 (2026) | 实时 SDR 解调 |
| AI 辅助分析报告 | 自动调整天线 |

---

## 2. 需求规格 (Requirements)

### 2.1 功能性需求 (Functional Requirements)

#### FR-1 数据采集
- **FR-1.1** 系统应能通过 PSK Reporter ADIF 接口获取指定呼号过去 24+ 小时的完整传播记录。
- **FR-1.2** 系统应能通过 PSK Reporter 实时 JSON API 获取增量数据。
- **FR-1.3** 系统应能批量拉取所有呼号的传播数据（全量模式）。
- **FR-1.4** 系统应能导入 WSJT-X / JTDX 的 `.adi` 本地通联日志。
- **FR-1.5** 系统应能采集空间天气数据（太阳/地磁/电离层指数）。
- **FR-1.6** 所有采集应自动去重，并遵守 PSK Reporter 的查询频率限制
  (`min_query_interval = 300s`)。

#### FR-2 数据存储
- **FR-2.1** 传播记录应按发射方/接收方视角分表存储 (`sender_records` / `receiver_records`)。
- **FR-2.2** 表应按 `qso_time` 月度分区，按呼号 HASH 分桶。
- **FR-2.3** 应通过物化视图预聚合小时/日/国家维度统计，加速查询。
- **FR-2.4** 频率到波段的映射应有单一真相源 (`band_utils.py`)。
- **FR-2.5** 呼号到 DXCC 实体的映射应有单一真相源 (`dxcc_lookup.py`，290+ 实体)。

#### FR-3 Web 可视化（页面）
| 路由 | 页面 | 职责 |
|------|------|------|
| `/` | 传播地图 | 大圆路径、传播热点地图展示 |
| `/qso` | 通联分析 | 本地 QSO 日志统计、DXCC 进度 |
| `/all` | 全量数据 | 所有呼号的传播统计 |
| `/advanced` | 深度分析 | 辐射方向、距离分布、传播热力图 |
| `/antenna` | 天线分析 | 天线方向图反推、弱点诊断、主瓣判定 |

#### FR-4 天线分析（核心差异化能力）
- **FR-4.1** 系统应从网格坐标实测计算大圆方位角与距离。
- **FR-4.2** 系统应通过球面多跳电离层模型，从通联距离反推辐射仰角。
- **FR-4.3** 系统应生成二维方向图（方位 × 仰角）极坐标热力图。
- **FR-4.4** 系统应用圆形统计逐波段计算主瓣方位与方向集中度，判定定向/全向。
- **FR-4.5** 系统应以同网格邻居为基准计算每方向每波段的 ΔSNR 弱点图。
- **FR-4.6** 系统应区分**实测硬数据**（方位、距离、SNR）与**模型估计值**（仰角），
  并在 UI 与 API 响应中明确标注。

#### FR-5 AI 分析
- **FR-5.1** 系统应能调用远程 LM Studio API 生成自然语言分析报告。
- **FR-5.2** AI 调用应通过统一客户端 (`lm_client.py`)，禁止 shell 注入式调用。

### 2.2 非功能性需求 (Non-Functional Requirements)

| ID | 需求 | 实现约束 |
|----|------|---------|
| NFR-1 性能 | 分析类查询应在数秒内返回 | 物化视图预聚合 + 分区裁剪 + `LIMIT` 采样 + TTL 缓存 |
| NFR-2 缓存 | 重复查询应命中缓存 | `ALL_CACHE` (TTL 120s)、`ANTENNA_CACHE` (TTL 300s)，响应头 `X-Cache: HIT/MISS` |
| NFR-3 安全 | SQL 应防注入 | 全部使用参数化查询 (`%s` 占位符) |
| NFR-4 安全 | AI 调用应防注入 | 统一 `lm_client`，移除 SSH+subprocess 路径 |
| NFR-5 可维护 | 共享逻辑单一真相源 | `band_utils` / `dxcc_lookup` / `lm_client` |
| NFR-6 可移植 | 数据库连接可配 | `config.json`，MySQL 兼容协议 |
| NFR-7 诚实性 | 区分实测与模型推断 | 仰角等估计值在 note 字段显式声明 |

---

## 3. 系统架构 (Architecture)

### 3.1 数据流

```
┌────────────────────┐
│  PSK Reporter API  │──ADIF──▶ pskreporter_adif.py ────┐
│  (传播报告源)       │──JSON──▶ pskreporter_fetcher.py  │
└────────────────────┘──全量──▶ pskreporter_all.py      │
                                                          ├──▶ StarRocks
┌────────────────────┐                                   │   (ham.vlsc.net:9030)
│ WSJT-X / JTDX .adi │────────▶ wsjtx_log_import.py ─────┤   MySQL 兼容协议
└────────────────────┘                                   │
                                                          │
┌────────────────────┐                                   │
│  空间天气 APIs      │────────▶ space_weather_fetcher.py─┘
└────────────────────┘
                                                          │
                              ┌───────────────────────────┘
                              ▼
                    ┌──────────────────┐        ┌─────────────────────┐
                    │  Flask web_app.py │◀──────▶│ LM Studio 远程 API   │
                    │  (43 路由)        │ lm_client│ (ham.vlsc.net:8888) │
                    └──────────────────┘        └─────────────────────┘
                              │
                ┌─────────────┼─────────────┬──────────┬───────────┐
                ▼             ▼             ▼          ▼           ▼
              地图 /        通联 /qso     全量 /all  深度       天线
                                                   /advanced   /antenna
```

### 3.2 分层

| 层 | 组件 | 职责 |
|----|------|------|
| 采集层 | `pskreporter_*.py`, `wsjtx_log_import.py`, `space_weather_*.py` | 外部数据 → StarRocks |
| 存储层 | StarRocks (`init.sql` 定义) | 分区表 + 物化视图 |
| 共享内核 | `band_utils.py`, `dxcc_lookup.py`, `lm_client.py` | 单一真相源工具 |
| 服务层 | `web_app.py` | HTTP 路由 + SQL 查询 + 几何计算 + 缓存 |
| 分析层 | `cross_domain_analyzer.py`, `ai_*.py`, `snr_market_deep.py` | 离线/深度分析 |
| 表现层 | `templates/*.html` + Chart.js / 原生 Canvas | 可视化 |

### 3.3 年度数据双轨制（关键设计）

系统同时维护两个数据集，查询时由 `get_raw_table_and_partitions(year)` 路由：

| 年份 | 表 | 时间过滤策略 | 原因 |
|------|----|-----------|----|
| 2025 | `psk_hdf5`（分区 `p202501`~`p202504`）| **绝对日期**（数据范围 2025-01-01 ~ 04-22）| `NOW()` 是 2026 年，相对时间对历史数据无效 |
| 2026 | `all_records`（全表）| **相对时间** `DATE_SUB(NOW(), ...)` | 数据接近实时 |

预聚合汇总表：`psk_hdf5_summary` (2025) / `all_records_summary` (2026)。

---

## 4. 数据契约 (Data Contracts)

### 4.1 核心表 `sender_records` / `receiver_records`

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | BIGINT AUTO_INCREMENT | 主键 (DUPLICATE KEY) |
| `sender_callsign` | VARCHAR(20) | 发送方呼号 |
| `receiver_callsign` | VARCHAR(20) | 接收方呼号 |
| `sender_locator` | VARCHAR(10) | 发送方 Maidenhead 网格 |
| `receiver_locator` | VARCHAR(10) | 接收方 Maidenhead 网格 |
| `frequency` | INT | 频率 (Hz) |
| `snr` | INT | 信噪比 (dB) |
| `mode` | VARCHAR(20) | 通信模式 (FT8 等) |
| `qso_time` | DATETIME | 通信时间（分区键）|
| `distance` | DECIMAL(10,1) | 距离 (km) |
| `bearing` | DECIMAL(5,1) | 方位角 |
| `country` / `dxcc` | VARCHAR | 国家 / DXCC 编号 |
| `fetch_time` / `created_at` | DATETIME | 采集/创建时间 |

- **分区**：`PARTITION BY RANGE(qso_time)`，月度（2026 全年逐月 + 2027 整年）。
- **分桶**：`DISTRIBUTED BY HASH(sender_callsign) BUCKETS 10`。

### 4.2 波段契约 (`band_utils.py`)
单一真相源，12 个业余波段：

```
160m: 1.8–2.0 MHz    80m: 3.5–4.0     60m: 5.33–5.405   40m: 7.0–7.3
30m: 10.1–10.15      20m: 14.0–14.35  17m: 18.068–18.168 15m: 21.0–21.45
12m: 24.89–24.99     10m: 28.0–29.7   6m: 50–54         2m: 144–148
```
导出：`BAND_FREQ_MAP`、`CASE_BAND_SQL`（SQL 内频率→波段）、`get_band_from_frequency()`、
`build_band_conditions()`。

### 4.3 DXCC 契约 (`dxcc_lookup.py`)
- 290+ DXCC 实体，前缀优先级匹配（长前缀优先）。
- 导出：`lookup_callsign()`、`get_continent()`、`get_continent_full()`、`get_dxcc_info()`。
- 自包含，无网络依赖（不下载 cty.dat）。

### 4.4 天线分析 API 响应契约

#### `/api/antenna/polar_pattern` — 二维方向图
```json
{
  "callsign": "BG1SB", "role": "tx", "band": "all",
  "az_bin": 5, "el_bin": 3, "el_max": 60,
  "total": 131721,
  "cells": [{"azimuth": 95, "elevation": 9, "count": 28605,
             "avg_snr": -7.2, "max_snr": 32, "stations": 825}],
  "peak": {"azimuth": 95, "elevation": 9, "count": 28605, ...},
  "note": "角向=方位角(实测大圆方位) · 径向=辐射仰角(F2@300km球面模型反推,为估计值) · 颜色=报文密度"
}
```

#### `/api/antenna/lobe_drift` — 主瓣方位漂移
```json
{
  "callsign": "BG1SB", "role": "tx",
  "bands": [{"band": "15m", "mean_azimuth": 105.4, "compass": "ESE",
             "concentration": 0.621, "peak_azimuth": 90, "count": 59927,
             "avg_snr": -11.7, "type": "强定向"}],
  "diagnosis": "各波段主瓣高度一致 (~103° ESE), 方向集中 → 定向天线固定指向",
  "azimuth_spread": 6.0,
  "note": "主瓣方位=报文按方位的圆形平均(实测) · 集中度R∈[0,1],越高越定向 · 方位为硬数据,与仰角模型无关"
}
```

---

## 5. 组件规格 (Component Specs)

### 5.1 数据采集模块

| 模块 | 输入 | 输出 | 关键约束 |
|------|------|------|---------|
| `pskreporter_adif.py` | 呼号、时间窗 | ADIF 文件 + DB | 历史完整数据，主采集器 |
| `pskreporter_fetcher.py` | 呼号 | DB | 实时 JSON API |
| `pskreporter_all.py` | — | DB | 全量呼号 |
| `wsjtx_log_import.py` | `.adi` 文件 | `qso_log` 表 | 用 `dxcc_lookup` 替代旧 DXCC_MAP |
| `space_weather_fetcher.py` | 空间天气 API | DB | 太阳/地磁/电离层 |
| `parallel_import.py` | ADIF 文件集 | DB | 多进程导入 |
| `import_hdf5.py` | HDF5 | StarRocks Stream Load | 批量历史导入 |

### 5.2 服务层 `web_app.py` (3907 行)

**职责**：全部 HTTP 路由 + SQL 查询 + 几何计算 + 缓存。

**关键几何函数**（`compute_*` 系列）：
- `compute_bearing(lat1,lon1,lat2,lon2)` → 大圆方位角 0–360°（**实测硬数据**）
- `compute_distance_km(...)` → Haversine 距离（**实测硬数据**）
- `elevation_angle_deg(distance_km, iono_height_km=300)` → 球面多跳模型反推辐射仰角
  （**模型估计值**），最大单跳 F2@300km ≈ 3822km，超出按整数跳数等分
- `grid_to_latlon(locator)` → Maidenhead 网格 → 经纬度

**缓存**：`TTLCache` 类，`ALL_CACHE`(120s) / `ANTENNA_CACHE`(300s)，命中标记响应头。

### 5.3 天线分析端点族 (`/api/antenna/*`)

| 端点 | 分析 | 维度 |
|------|------|------|
| `elevation` | 辐射仰角分布 vs 邻居 | 仰角(2°分箱) |
| `band_angle` | 各波段最佳仰角 | 波段 × 仰角分位 |
| `hop_analysis` | 电离层跳距 | E/F2 单跳/多跳 |
| `noise_floor` | 方向性噪声底限 | 方位(10°) × 最低SNR |
| `tx_quality` | 发射质量诊断 | 波段 × SNR标准差 |
| `polar_pattern` | **二维方向图** | 方位(5°) × 仰角(3°) |
| `lobe_drift` | **主瓣方位漂移** | 波段 × 圆形统计 |
| `weak_spots` | ΔSNR 弱点 | 方位扇区 × 波段 vs 邻居 |

### 5.4 共享内核（单一真相源）
- `band_utils.py` — 波段定义，被 `web_app`/`snr_market_deep`/`check_data` 引用。
- `dxcc_lookup.py` — DXCC 映射，被 `web_app`/`pskreporter_adif`/`wsjtx_log_import` 引用。
- `lm_client.py` — `call_lm()` / `check_status()`，统一 AI 调用，杜绝 shell 注入。

---

## 6. 关键设计决策 (Design Decisions)

### DD-1 实测 vs 模型推断的诚实标注
**决策**：方位角和距离是从网格坐标几何实测的硬数据；仰角是球面电离层模型的估计值。
所有涉及仰角的 API 响应必须在 `note` 字段声明其为估计值，UI 同步标注。
**理由**：避免把模型伪影（如一维仰角图上的「48° 尖峰」实为正南近距信号被反推）
误读为天线真实特性。二维视角 + 圆形统计能揭穿此类伪影。

### DD-2 方位用圆形统计而非算术平均
**决策**：`lobe_drift` 把每条报文当单位向量 `(cos az, sin az)` 累加，合向量角度为主瓣
方位，合向量长度 R∈[0,1] 为方向集中度。
**理由**：方位是圆形量，350° 与 10° 的算术平均会错误得到 180°。圆形统计正确处理跨 0°
环绕，且 R 天然量化「定向程度」。

### DD-3 年度数据双轨 + 时间过滤分流
**决策**：2025 用 `psk_hdf5` 分区表 + 绝对日期；2026 用 `all_records` 全表 + 相对时间。
**理由**：`NOW()` 处于 2026，对 2025 历史数据用相对时间会全部落空。

### DD-4 物化视图 + 采样 + 缓存三级提速
**决策**：预聚合 MV 承载常规统计；天线分析类用 `LIMIT 25000~60000` 采样 + 分区遍历 +
TTLCache。
**理由**：天线分析需逐条做几何计算（网格→经纬→方位/仰角），无法全表扫描；采样在统计
意义上足够，缓存吸收重复查询。

### DD-5 共享内核消除重复
**决策**：波段/DXCC/AI 三类逻辑各收敛到一个模块。
**理由**：历史上 4 个文件各自维护 DXCC 映射、AI 调用含 shell 注入风险。收敛后单点维护、
单点加固。

---

## 7. 部署与运行 (Operations)

### 7.1 配置 (`config.json`)
```json
{
  "callsign": "BG1SB",
  "database": {"type": "starrocks", "host": "ham.vlsc.net",
               "port": 9030, "http_port": 8030, "name": "pskreporter"},
  "wsjtx_log_paths": ["~/Library/Application Support/WSJT-X/wsjtx_log.adi", ...],
  "min_query_interval": 300
}
```

### 7.2 启停 (`start.sh`)
- `fetch_data` — 拉取 PSK Reporter 数据
- `sync_qso_log` — 同步本地 WSJT-X/JTDX 日志
- `stop_services` — 停止服务

### 7.3 依赖外部服务
| 服务 | 地址 | 用途 |
|------|------|------|
| StarRocks | `ham.vlsc.net:9030` (MySQL协议) / `:8030` (HTTP) | 数据存储 |
| LM Studio | `ham.vlsc.net:8888` | AI 推理（见 `LM_API_SETUP.md`）|
| PSK Reporter | retrieve.pskreporter.info | 数据源 |

---

## 8. 验证与测试策略 (Verification)

| 验证项 | 方法 |
|--------|------|
| SQL 注入 | 全部参数化查询，code review 检查 `%s` 占位 |
| 几何正确性 | 已知网格对 → 方位/距离 与在线计算器比对 |
| 仰角模型 | F2@300km 最大单跳 ≈ 3822km 边界检查 |
| 圆形统计 | 跨 0° 环绕用例（如 350°+10° → 0°）|
| 缓存 | 响应头 `X-Cache` 验证命中 |
| 数据双轨 | 2025/2026 分别查询返回非空 |

---

## 9. 已知约束与未来工作 (Constraints & Future)

- **C-1** 2025 历史数据范围固定 2025-01-01 ~ 04-22，分区写死 `RAW_2025_PARTITIONS`。
- **C-2** 仰角依赖固定电离层高度预设 (D/E/F1/F2)，未接入实时 foF2 动态高度。
- **C-3** 天线分析采样上限（25k~60k），极端高产呼号可能欠采样。
- **F-1** 可将 `elevation_angle_deg` 接入实时电离层高度（`space_weather` 已有 foF2 采集）。
- **F-2** `web_app.py` 已达 3907 行，可按路由族 (`/api/antenna`, `/api/advanced`) 拆分蓝图。

---

## 附录 A：路由清单（43 条）

**页面**：`/`, `/qso`, `/all`, `/advanced`, `/antenna`
**配置/采集**：`/api/config`, `/api/fetch_log`, `/api/validate/<callsign>`
**基础数据**：`/api/records`, `/api/stats`, `/api/dxcc_analysis`, `/api/band_analysis`,
`/api/unvalidated_callsigns`
**QSO**：`/api/qso/{records,stats,dxcc_progress,band_analysis,map_data,recent}`
**全量**：`/api/all/{stats,band_analysis,continent_analysis,timeline}`, `/api/space_weather`
**深度**：`/api/advanced/{stats,radiation,distance,heatmap,band_snr,hourly_efficiency,
grid_compare,grid_radiation,station_audit}`
**天线**：`/api/antenna/{elevation,band_angle,hop_analysis,noise_floor,tx_quality,
polar_pattern,lobe_drift,weak_spots}`
**AI**：`/api/ai/analyze` (POST), `/api/ai/status` (GET)
