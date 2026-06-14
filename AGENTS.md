## 共享模块

| 模块 | 描述 |
|------|------|
| `dxcc_lookup.py` | DXCC 前缀查找 — 290+ 实体完整映射 |
| `band_utils.py` | 波段频率定义 — 12个业余波段单一真相源 |
| `lm_client.py` | LM API 客户端 — 统一 AI 推理接口 |

### band_utils 用法

```python
from band_utils import BAND_FREQ_MAP, CASE_BAND_SQL, get_band_from_frequency, build_band_conditions
# BAND_FREQ_MAP: {'40m': (7000000, 7300000), ...}
# CASE_BAND_SQL: "CASE WHEN frequency BETWEEN 7000000 AND 7300000 THEN '40m' ... END"
# 波段过滤条件构建:
conditions, params = build_band_conditions('40m', conditions, params)
```

### lm_client 用法

```python
from lm_client import call_lm, check_status
result = call_lm("分析传播条件...")
# => {"success": True, "content": "...", "model": "qwen/qwen3.5-9b", ...}
```

## DXCC 查找模块

### 文件

| 文件 | 描述 |
|------|------|
| `dxcc_lookup.py` | 共享 DXCC 前缀查找模块 - 290+ DXCC 实体完整映射 |

### 用法

```python
from dxcc_lookup import lookup_callsign, get_continent, get_continent_full, get_dxcc_info

# 呼号 → DXCC 实体
result = lookup_callsign("JA1ABC")
# => {"adif": 339, "name": "Japan", "continent": "AS"}

# DXCC 实体 → 大洲
get_continent("Japan")      # => "AS"
get_continent_full("AS")    # => "Asia"

# 按名称或 ADIF 编号查询实体
get_dxcc_info("Japan")      # => {...}
get_dxcc_info(339)          # => {...}
```

### 覆盖范围

- 290+ DXCC 实体，涵盖 ARRL DXCC List 绝大部分
- 支持前缀优先级匹配（长前缀优先，实体定义顺序秒杀）
- 正确处理 Alaska (KL)、Hawaii (KH6/7)、俄罗斯亚洲/欧洲分部、JD1 等复杂情况

### 已集成的模块

| 模块 | 集成方式 |
|------|---------|
| `web_app.py` | 导入 lookup_callsign, get_continent, get_continent_full, get_dxcc_info |
| `pskreporter_adif.py` | 导入 lookup_callsign，替换 _get_country_from_callsign |
| `wsjtx_log_import.py` | 导入 lookup_callsign，替换 get_dxcc 和 DXCC_MAP |
| `snr_market_deep.py` | 导入 lookup_callsign + CASE_BAND_SQL (band_utils) |
| `check_data.py` | 导入 CASE_BAND_SQL (band_utils) |
| `ai_analyzer.py` | 导入 call_lm, DEFAULT_MODEL (lm_client)，删除 SSH+subprocess |
| `ai_analyzer_simple.py` | 导入 call_lm (lm_client)，删除 shell injection |

### 设计决策

- 自包含模块，无外部依赖（不依赖 cty.dat 网络下载）
- 共享代码，避免 4 个文件各自维护 DXCC 映射
- 别名映射 (`DXCC_NAME_ALIASES` in web_app.py) 处理 PSK Reporter API 返回的非标准名称
