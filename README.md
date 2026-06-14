# PSK Reporter 数据获取与通联分析系统

从 PSK Reporter 服务器查询和保存业余无线电信号传播报告，支持 WSJT-X/JTDX 通联日志导入、MySQL 数据库存储和 Web 可视化分析。

## 功能特性

- **完整历史数据**: 使用 ADIF 接口获取过去 24+ 小时的完整传播记录
- **通联日志导入**: 自动同步 WSJT-X/JTDX 的真实通联记录
- **Web 可视化**: 地图展示传播路径、通联统计分析
- **DXCC 分析**: 验证呼号有效性、统计 DXCC 进度
- **双格式保存**: 同时保存 ADIF 文件和数据库
- **自动去重**: 数据库使用唯一键避免重复记录
- **定时同步**: 支持 crontab 自动获取和同步

## 项目结构

```
pskreporter/
├── pskreporter_adif.py     # PSK Reporter 数据获取器
├── wsjtx_log_import.py     # WSJT-X/JTDX 通联日志导入
├── web_app.py              # Flask Web 应用
├── config.json             # 配置文件
├── docker-compose.yml      # MySQL 数据库配置
├── init-mysql.sql          # 数据库初始化脚本
├── start.sh                # 启动脚本
├── stop.sh                 # 停止脚本
├── templates/              # Web 前端模板
│   ├── index.html          # 传播地图页面
│   └── qso.html            # 通联分析页面
├── venv/                   # Python 虚拟环境
└── logs/                   # 日志和 ADIF 文件
    ├── BG1SB/              # 按呼号分类
    └── *.log               # 运行日志
```

## 系统架构

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  PSK Reporter   │     │ pskreporter_     │     │    MySQL        │
│  ADIF API       │────▶│ adif.py          │────▶│   Database      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                         │
                               ▼                         ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   ADIF 文件       │     │   Web App       │
                        │   (.adi)         │     │   (Flask)       │
                        └──────────────────┘     └─────────────────┘
                                                     │
                        ┌──────────────────┐         │
                        │ WSJT-X/JTDX      │         │
                        │ wsjtx_log.adi    │─────────┤
                        └──────────────────┘         │
                               │                     ▼
                               ▼              ┌─────────────────┐
                        ┌──────────────────┐  │  前端可视化      │
                        │ wsjtx_log_       │  │  - 传播地图      │
                        │ import.py        │  │  - 通联统计      │
                        └──────────────────┘  │  - DXCC 分析     │
                                              └─────────────────┘
```

## 快速开始

### 1. 环境要求

- Python 3.12+
- Docker Desktop（用于 MySQL）
- macOS / Linux

### 2. 安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install mysql-connector-python flask flask-cors
```

### 3. 启动服务

```bash
# 一键启动：数据库 + 数据获取 + Web 应用
./start.sh

# 或分步启动
./start.sh db       # 仅启动数据库
./start.sh fetch    # 仅获取数据
./start.sh sync     # 仅同步通联日志
./start.sh web      # 仅启动 Web
```

### 4. 访问 Web 界面

- **传播地图**: http://localhost:5000
- **通联分析**: http://localhost:5000/qso

## Web 功能

### 传播地图 (/:index)

- 🗺️ 地图可视化传播路径
- 📊 按时间范围、记录类型筛选
- 🌍 DXCC 国家/地区统计
- 📻 模式、波段分布
- ✅ 呼号有效性验证 (ALLCALL7 数据库)
- 📡 波段传播分析、最佳通联时间

### 通联分析 (/qso)

- 📈 总通联数、不同呼号、DXCC 实体数
- 🌍 按大洲分组的 DXCC 进度
- 📡 波段分布条形图
- 📻 模式统计 (FT8/FT4 等)
- 🕐 24 小时通联热力图
- 📏 最远通联 TOP 10
- 🗺️ 通联地图
- 📋 通联记录表（支持筛选）

## 命令行工具

### pskreporter_adif.py - PSK Reporter 数据获取

```bash
# 基本使用
venv/bin/python pskreporter_adif.py

# 指定呼号
venv/bin/python pskreporter_adif.py --callsign BG1SB

# 获取过去 2 天数据
venv/bin/python pskreporter_adif.py --days 2

# 只获取发送/接收记录
venv/bin/python pskreporter_adif.py --sender-only
venv/bin/python pskreporter_adif.py --receiver-only

# 只保存 ADIF 文件，不入库
venv/bin/python pskreporter_adif.py --no-db

# 静默模式
venv/bin/python pskreporter_adif.py --quiet
```

### wsjtx_log_import.py - 通联日志导入

```bash
# 查看可用的日志文件
venv/bin/python wsjtx_log_import.py --list

# 自动导入所有日志文件
venv/bin/python wsjtx_log_import.py

# 强制重新导入
venv/bin/python wsjtx_log_import.py --force

# 导入指定文件
venv/bin/python wsjtx_log_import.py --file "/path/to/wsjtx_log.adi"
```

## 配置文件

`config.json`:

```json
{
    "callsign": "BG1SB",
    "log_dir": "logs",
    "days": 1,
    "database": {
        "type": "mysql",
        "host": "localhost",
        "port": 3306,
        "user": "pskuser",
        "password": "pskpass123",
        "name": "pskreporter"
    },
    "wsjtx_log_paths": [
        "~/Library/Application Support/WSJT-X/wsjtx_log.adi",
        "~/Library/Application Support/JTDX/wsjtx_log.adi"
    ]
}
```

## 数据库

### 连接信息

| 项目 | 值 |
|------|-----|
| 主机 | localhost |
| 端口 | 3306 |
| 用户 | pskuser |
| 密码 | pskpass123 |
| 数据库 | pskreporter |

### 数据表

| 表名 | 说明 |
|------|------|
| sender_records | 本台发射被他人接收的记录 |
| receiver_records | 本台接收到他人信号的记录 |
| qso_log | 真实通联记录（从 WSJT-X/JTDX 导入） |
| sync_log | 日志同步状态记录 |
| fetch_log | 数据获取日志 |

### 常用查询

```bash
# 连接数据库
docker exec -it pskreporter-db mysql -upskuser -ppskpass123 pskreporter

-- 通联统计
SELECT 
    COUNT(*) as total_qsos,
    COUNT(DISTINCT callsign) as unique_callsigns,
    COUNT(DISTINCT country) as unique_countries
FROM qso_log;

-- 按波段统计
SELECT band, COUNT(*) as count 
FROM qso_log 
GROUP BY band 
ORDER BY count DESC;

-- 按国家统计
SELECT country, COUNT(*) as count 
FROM qso_log 
GROUP BY country 
ORDER BY count DESC 
LIMIT 10;

-- 最远通联
SELECT callsign, distance, band, qso_date 
FROM qso_log 
ORDER BY distance DESC 
LIMIT 10;
```

## 定时任务

已配置 crontab 自动运行：

```bash
# 查看定时任务
crontab -l
```

当前配置：
- 每小时整点获取 PSK Reporter 数据
- 每小时第 5 分钟同步通联日志

## API 接口

### 传播数据

| 端点 | 说明 |
|------|------|
| `/api/config` | 获取当前配置 |
| `/api/records` | 获取传播记录 |
| `/api/stats` | 获取统计数据 |
| `/api/dxcc_analysis` | DXCC 分析 |
| `/api/band_analysis` | 波段传播分析 |
| `/api/validate/<callsign>` | 验证呼号 |

### 通联日志

| 端点 | 说明 |
|------|------|
| `/api/qso/stats` | 通联综合统计 |
| `/api/qso/records` | 通联记录列表 |
| `/api/qso/dxcc_progress` | DXCC 进度 |
| `/api/qso/band_analysis` | 波段分析 |
| `/api/qso/map_data` | 地图数据 |
| `/api/qso/recent` | 最近通联 |

## IPv6 远程访问

本系统支持通过 IPv6 远程访问内网服务（使用 socat 端口转发）：

| 外部端口 | 内网目标 |
|---------|---------|
| 8800 | 192.168.1.63:80 |
| 60001 | 192.168.1.63:60001 |

访问地址：
- http://radio.vlsc.net:8800/
- http://radio.vlsc.net:60001/

## 相关资源

- PSK Reporter 地图: https://pskreporter.info/pskmap.html
- PSK Reporter API: https://pskreporter.info/pskdev.html
- ADIF 标准: https://www.adif.org/

## 常见问题

### Q: 数据库连接失败怎么办？

A: 确保 MySQL 容器已启动：
```bash
docker ps | grep pskreporter
# 如果没有运行
./start.sh db
```

### Q: 如何修改呼号？

A: 编辑 `config.json` 文件或使用 `--callsign` 参数：
```bash
venv/bin/python pskreporter_adif.py --callsign YOUR_CALLSIGN
```

### Q: 通联日志没有同步？

A: 检查 `config.json` 中的 `wsjtx_log_paths` 配置，确保路径正确。可以手动运行：
```bash
venv/bin/python wsjtx_log_import.py --list
```

### Q: Web 页面无法访问？

A: 检查 Web 应用是否运行：
```bash
pgrep -f "web_app.py"
# 如果没有运行
./start.sh web
```

## License

MIT