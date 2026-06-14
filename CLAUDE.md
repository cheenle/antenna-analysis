# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A **PSK Reporter data acquisition and propagation analysis system** for amateur radio. It queries PSK Reporter servers for signal propagation reports, imports WSJT-X/JTDX QSO logs, stores data in StarRocks, and provides a Flask web app with map visualization and statistical analysis.

- **Callsign**: BG1SB (configurable in `config.json`)
- **Database**: StarRocks on `ham.vlsc.net:9030` (MySQL-compatible protocol)
- **AI Inference**: LM Studio remote API on `ham.vlsc.net:8888` (see `LM_API_SETUP.md`)

## Architecture

```
PSK Reporter API ──▶ pskreporter_adif.py ──▶ StarRocks (ham.vlsc.net)
WSJT-X/JTDX .adi  ──▶ wsjtx_log_import.py  ──▶ StarRocks
Space Weather APIs ─▶ space_weather_fetcher.py ──▶ StarRocks
                                              │
Flask web_app.py ◀────────────────────────────┘
  ├── /          → Propagation map (index.html)
  ├── /qso       → QSO analysis (qso.html)
  ├── /all       → All callsign data (all.html)
  └── /api/*     → JSON REST endpoints
```

## Key Files

| File | Purpose |
|------|---------|
| `pskreporter_adif.py` | Main data fetcher via ADIF API (historical data) |
| `pskreporter_fetcher.py` | Real-time JSON API fetcher |
| `pskreporter_all.py` | Bulk fetcher for all callsigns |
| `wsjtx_log_import.py` | Imports WSJT-X/JTDX .adi QSO logs into DB |
| `web_app.py` | Flask web app (~2000 lines, all routes + DB queries) |
| `parallel_import.py` | Multi-process ADIF file importer |
| `space_weather_fetcher.py` | Space weather data collector |
| `cross_domain_analyzer.py` | Cross-domain analysis (space weather + propagation) |
| `ai_analyzer.py` / `ai_analyzer_simple.py` | AI-powered analysis modules |
| `ai_report_generator.py` | AI report generation |
| `lm_api_server.py` | LM Studio remote API server (deployed on ham.vlsc.net) |
| `lm_remote_client.py` | Client for remote LM Studio API |
| `init.sql` | StarRocks schema (partitioned tables, materialized views) |
| `config.json` | Callsign, DB connection, log paths |

## Database Tables

| Table | Description |
|-------|-------------|
| `sender_records` | This station's transmissions received by others |
| `receiver_records` | Signals received by this station |
| `all_records` | All callsigns' propagation data |
| `qso_log` | Real QSO records from WSJT-X/JTDX |
| `fetch_log` | Data fetch audit log |
| `sync_log` | Sync status log |
| `solar_activity`, `solar_wind`, `geomagnetic_indices`, `ionosphere_data`, `sunrise_sunset`, `space_weather_daily` | Space weather tables |

Connection: `mysql -h ham.vlsc.net -P 9030 -u root pskreporter`

## Development Commands

```bash
# Activate venv
source venv/bin/activate

# Install deps
pip install mysql-connector-python flask flask-cors requests

# Start everything (DB check + fetch + sync + web)
./start.sh

# Individual commands
./start.sh fetch    # Fetch PSK Reporter data
./start.sh sync     # Sync WSJT-X/JTDX logs
./start.sh web      # Start Flask app on :5000
./start.sh stop     # Kill web app
./start.sh db-check # Check remote StarRocks connectivity
./start.sh db-start # Remote-start StarRocks via SSH

# Direct Python execution
python3 pskreporter_adif.py --callsign BG1SB --days 1
python3 wsjtx_log_import.py --list
python3 web_app.py              # http://localhost:5000
python3 space_weather_fetcher.py --days 7
python3 parallel_import.py      # Import logs/ALL/*.adi files
```

## Web API Endpoints

Propagation: `/api/config`, `/api/records`, `/api/stats`, `/api/dxcc_analysis`, `/api/band_analysis`, `/api/validate/<callsign>`

QSO Log: `/api/qso/stats`, `/api/qso/records`, `/api/qso/dxcc_progress`, `/api/qso/band_analysis`, `/api/qso/map_data`, `/api/qso/recent`

## Important Notes

1. **No local Docker MySQL** — the system uses a remote StarRocks instance on `ham.vlsc.net`. The `docker-compose.yml` is legacy/unused.
2. **StarRocks-specific SQL** — uses `ENGINE=OLAP`, `DUPLICATE KEY`, `PARTITION BY RANGE`, and `DISTRIBUTED BY HASH` clauses. Standard MySQL syntax won't work for table creation.
3. **API rate limiting** — PSK Reporter recommends ≥5 min between queries (`min_query_interval` in config).
4. **Data retention** — PSK Reporter only keeps ~24h of real-time data; historical data must be fetched via the ADIF interface.
5. **Dependencies** — Python 3.12+, `mysql-connector-python`, `flask`, `flask-cors`, `requests`. No `requirements.txt` exists; install manually.
6. **Cron jobs** — hourly data fetch and QSO log sync are configured via crontab.
7. **AI integration** — `ai_analyzer.py` can use the remote LM Studio API when `LM_API_KEY` and `LM_API_URL` env vars are set.
