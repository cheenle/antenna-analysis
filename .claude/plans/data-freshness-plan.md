# 确保汇总表更新 + 2026 实时数据持续获取

## 诊断结论(已验证)

| 链路 | 现状 | 问题 |
|---|---|---|
| `all_records`(700万行,增长最快) | cron `*/5min` 在跑,数据到 06-12 | 正常,无需动 |
| 10 个物化视图(MV) | 全部 `REFRESH ASYNC EVERY 1 HOUR`,自动刷新 | **本身没问题**,SKIPPED=基表无新数据 |
| `sender/receiver_records`(ADIF) | 无 cron,停在 06-08 | 链路断 + **伪去重已致 27.7% 重复** |
| `qso_log`(WSJT/JTDX 真实通联) | 无 cron,停在 06-08;保留 -36 月 | 链路断 + 2023 历史濒临被删 |

**核心根因**:`pskreporter_adif.py` 的 `save_to_db()` 用 `int(time.time()*1e6)+random()` 生成 id。表实际是 `PRIMARY KEY(id)`,随机 id 导致主键永不冲突 → 去重彻底失效。注释 `# 忽略重复记录错误` 是假象。所以现在不能直接加每小时 cron,否则 `--days 1` 每小时重插 24h 数据 → 24 倍膨胀,MV 的 count/unique 统计全部失真。

web_app.py 不依赖 sender/receiver_records 的 `id` 列(已验证),改 id 生成方式安全。

---

## 实施步骤

### 1. 修复 adif 去重(核心)— `pskreporter_adif.py`
把随机 id 改为**基于内容的确定性 id**,让 StarRocks PRIMARY KEY 表自动 upsert(幂等)。

- 新增 helper:`_content_id(sender, receiver, qso_time, frequency, snr)`,用 `hashlib` 对拼接串做哈希,取 63-bit 正整数(`% 9223372036854775807`)作 BIGINT id。
- sender 与 receiver 各自计算 id(两表独立,无需跨表唯一)。
- 删除 `base_id + random()` 与 `id_counter` 逻辑。
- 同一条记录无论抓几次,id 恒定 → 重插即覆盖。
- `fetch_log` 的 id 维持原样(审计日志,允许多行)。

### 2. 清理历史重复(一次性)— 新建 `dedup_records.py`
对 `sender_records` / `receiver_records` 去重,保留每组 `(sender,receiver,qso_time,frequency,snr,mode)` 一条。
- StarRocks 无 `DELETE ... USING`;用 `INSERT OVERWRITE` 重建:
  `CREATE TABLE tmp LIKE ...` → 插入去重后数据(`GROUP BY` 或窗口取 min(id))→ `INSERT OVERWRITE` 回原表 → drop tmp。
- 脚本先打印去重前后行数,做 `--dry-run` 默认,加 `--apply` 才真正执行。
- 跑完后手动触发一次 MV 刷新(`REFRESH MATERIALIZED VIEW ...`)让汇总表立即对齐。

### 3. 加 cron 自动化(crontab)
```cron
# ADIF 抓取(本台 sender/receiver),每小时 7 分
7 * * * * cd /Users/cheenle/pskreporter && venv/bin/python3 pskreporter_adif.py --days 1 --quiet >> logs/adif.log 2>&1
# WSJT/JTDX 真实通联同步,每 10 分钟
*/10 * * * * cd /Users/cheenle/pskreporter && venv/bin/python3 wsjtx_log_import.py >> logs/wsjtx_sync.log 2>&1
```
- 错开整点(用 7 分),避开 all.py 的 `*/5` 和空间天气的 `0` 分,减少并发争用。
- adif 自带 300s 频率保护,每小时跑安全。
- 修复去重后,每小时重抓 24h 数据不再产生重复(幂等覆盖)。

### 4. 延长 qso_log 保留 — `init.sql` + 线上 ALTER
- 线上执行:`ALTER TABLE qso_log SET ("dynamic_partition.start" = "-120")`(保护 2023 起的真实通联,不可再生)。
- 同步改 `init.sql` 第 385 行 `-36` → `-120`,保持文档与实际一致。

---

## 验证
1. 改完 adif:手动跑两次 `pskreporter_adif.py --days 1`,确认第二次后 `SELECT COUNT(*)` 不增长(幂等)。
2. dedup 脚本:`--dry-run` 看预期删除量 → `--apply` → 复查重复率应为 0。
3. cron:写入后 `crontab -l` 确认;1 小时后查 `fetch_log` 和 sender_records max(qso_time) 是否推进。
4. MV:手动 `REFRESH MATERIALIZED VIEW propagation_sender_hourly_mv` 后查 max(hour) 对齐基表。
5. qso_log:`SHOW PARTITIONS` 确认 start 改为 -120,2023 分区不再处于删除窗口。

## 不做
- 不动 all_records(已正常)。
- 不给 all_records 新建 MV(本次聚焦"确保更新",性能优化另开)。
- 不动 web_app.py(查询不依赖 id)。
