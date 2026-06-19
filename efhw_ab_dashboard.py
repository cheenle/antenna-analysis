#!/usr/bin/env python3
"""EFHW A/B comparison dashboard — self-contained Flask Blueprint.

Serves the /efhw-ab page plus JSON APIs, all backed by the dedicated
StarRocks table `efhw_ab_reports` (role=dut|probe, config=A|B, segment=A1|B1|A2…).
Kept out of the 4000-line web_app.py; web_app.py only does `register_blueprint`.

Methodology recap (why these endpoints exist):
  * Report COUNT is polluted by TX duty cycle — it is NOT a valid antenna
    metric. We surface it but label it as such.
  * Per-common-receiver ΔSNR (same callsign in both A and B) is the valid
    paired metric: each receiver is its own control, cancelling path/distance.
  * ON80 probe stations (antenna fixed) give a propagation baseline; the
    antenna's net effect = DUT ΔSNR − probe ΔSNR.
  * Multi-segment (A1/B1/A2): merged view groups all A vs all B ignoring
    segment; per-segment breakdown shows each individually; A1-vs-A2 check
    quantifies pure propagation drift (same config, different time).

APIs (all GET, return JSON):
  /api/efhw-ab/timeline        switch timeline from efhw_ab_switches
  /api/efhw-ab/summary         test metadata + per role/config/segment counts
  /api/efhw-ab/paired_snr      DUT per-common-receiver ΔSNR + aggregate
                                (?view=merged|segments, default merged)
  /api/efhw-ab/probe_baseline  each probe's ΔSNR + pooled baseline + net effect
  /api/efhw-ab/segments        per-segment breakdown (DUT + probes)
  /api/efhw-ab/drift           A1-vs-A2 pure propagation drift check
  /api/efhw-ab/snr_hist        SNR histograms, A vs B (DUT)
  /api/efhw-ab/by_distance     reports/avg-SNR by distance bucket, A vs B
  /api/efhw-ab/by_direction    reports/avg-SNR by bearing octant, A vs B
"""
import math
import statistics

import mysql.connector
from flask import Blueprint, render_template, jsonify, request

efhw_ab_bp = Blueprint("efhw_ab", __name__)

DB_CONFIG = {
    "host": "ham.vlsc.net", "port": 9030, "user": "root",
    "password": "", "database": "pskreporter", "charset": "utf8mb4",
}

TEST_ID = "efhw_49un_vs_lc_20260619"

# Static test facts (recorded during the session).
TEST_META = {
    "test_id": TEST_ID,
    "title": "49:1 变压器 vs LC 调谐器",
    "band": "全波段 · 全模式",
    "power": "100 W",
    "dut": "BG1SB",
    "grid": "ON80da",
    "config_a": {"name": "49:1 变压器 (3×FT-240-51)", "swr": 1.47},
    "config_b": {"name": "LC 调谐器", "swr": 1.30},
    "mismatch_loss_a_db": 0.16,   # SWR 1.47
    "mismatch_loss_b_db": 0.075,  # SWR 1.30
    "segments": [
        {"segment": "A1", "config": "A", "switch_time": "2026-06-19 12:02:00",
         "swr": 1.47, "note": "初始 49:1 变压器 3xFT-240-51"},
        {"segment": "B1", "config": "B", "switch_time": "2026-06-19 12:26:52",
         "swr": 1.30, "note": "LC 调谐器"},
        {"segment": "A2", "config": "A", "switch_time": "2026-06-19 16:10:00",
         "swr": 1.47, "note": "回切 49:1 变压器"},
    ],
}


def _conn():
    return mysql.connector.connect(**DB_CONFIG)


def _rows(sql, params=()):
    conn = _conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _ci95(vals):
    """Bootstrap-free normal-approx 95% CI for the mean."""
    n = len(vals)
    if n < 2:
        return None, None
    m = statistics.mean(vals)
    se = statistics.pstdev(vals) / math.sqrt(n)
    return round(m - 1.96 * se, 2), round(m + 1.96 * se, 2)


def _paired_deltas(role, monitored=None, group_by="config"):
    """Per-common-receiver ΔSNR = mean(B) − mean(A) for a station.

    group_by='config': merges all segments of same config (A1+A2 vs B1).
    group_by='segment': compares per-segment (respects config ordering).

    Returns list of dicts {rx, mean_a, mean_b, d, n_a, n_b}.
    """
    if group_by == "segment":
        # Compare across segments — complex multi-way, handled by caller
        raise NotImplementedError("use _segment_deltas instead")
    where = "role=%s AND test_id=%s AND snr IS NOT NULL"
    params = [role, TEST_ID]
    if monitored:
        where += " AND monitored=%s"
        params.append(monitored)
    rows = _rows(
        f"""SELECT rx_callsign rx, config, AVG(snr) m, COUNT(*) n
            FROM efhw_ab_reports WHERE {where}
            GROUP BY rx_callsign, config""",
        params,
    )
    by_rx = {}
    for r in rows:
        by_rx.setdefault(r["rx"], {})[r["config"]] = (float(r["m"]), int(r["n"]))
    out = []
    for rx, cfg in by_rx.items():
        if "A" in cfg and "B" in cfg:
            ma, na = cfg["A"]
            mb, nb = cfg["B"]
            out.append({
                "rx": rx, "mean_a": round(ma, 1), "mean_b": round(mb, 1),
                "d": round(mb - ma, 1), "n_a": na, "n_b": nb,
            })
    out.sort(key=lambda x: x["d"], reverse=True)
    return out


def _segment_deltas(role, monitored=None, seg_a="A1", seg_b="A2"):
    """Per-common-receiver ΔSNR between two named segments (e.g. A1 vs A2)."""
    where = "role=%s AND test_id=%s AND segment IN (%s,%s) AND snr IS NOT NULL"
    params = [role, TEST_ID, seg_a, seg_b]
    if monitored:
        where += " AND monitored=%s"
        params.append(monitored)
    rows = _rows(
        f"""SELECT rx_callsign rx, segment, AVG(snr) m, COUNT(*) n
            FROM efhw_ab_reports WHERE {where}
            GROUP BY rx_callsign, segment""",
        params,
    )
    by_rx = {}
    for r in rows:
        by_rx.setdefault(r["rx"], {})[r["segment"]] = (float(r["m"]), int(r["n"]))
    out = []
    for rx, segs in by_rx.items():
        if seg_a in segs and seg_b in segs:
            ma, na = segs[seg_a]
            mb, nb = segs[seg_b]
            out.append({
                "rx": rx, f"mean_{seg_a}": round(ma, 1), f"mean_{seg_b}": round(mb, 1),
                "d": round(mb - ma, 1), f"n_{seg_a}": na, f"n_{seg_b}": nb,
            })
    out.sort(key=lambda x: x["d"], reverse=True)
    return out


# ── Page route ────────────────────────────────────────────────────

@efhw_ab_bp.route("/efhw-ab")
def efhw_ab_page():
    return render_template("efhw_ab.html", active_page="efhw_ab")


# ── API: Timeline ─────────────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/timeline")
def api_timeline():
    rows = _rows(
        """SELECT seq, switch_time, config, segment, swr, note
           FROM efhw_ab_switches WHERE test_id=%s ORDER BY seq ASC""",
        (TEST_ID,),
    )
    for r in rows:
        r["switch_time"] = str(r["switch_time"])
        if r["swr"] is not None:
            r["swr"] = float(r["swr"])
    return jsonify({"switches": rows})


# ── API: Summary ──────────────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/summary")
def api_summary():
    # Merged config view
    rows = _rows(
        """SELECT role, config, COUNT(*) reports,
                  COUNT(DISTINCT rx_callsign) rx,
                  COUNT(DISTINCT dxcc) ctry,
                  ROUND(AVG(snr),1) snr_avg, MIN(snr) snr_min, MAX(snr) snr_max,
                  ROUND(AVG(distance_km),0) dist_avg, ROUND(MAX(distance_km),0) dist_max,
                  MIN(qso_time) t0, MAX(qso_time) t1
           FROM efhw_ab_reports WHERE test_id=%s
           GROUP BY role, config ORDER BY role, config""",
        (TEST_ID,),
    )
    for r in rows:
        r["t0"] = str(r["t0"]); r["t1"] = str(r["t1"])
        for k in ("snr_avg", "dist_avg", "dist_max"):
            if r[k] is not None:
                r[k] = float(r[k])

    # Per-segment view
    seg_rows = _rows(
        """SELECT role, segment, config, COUNT(*) reports,
                  COUNT(DISTINCT rx_callsign) rx,
                  ROUND(AVG(snr),1) snr_avg,
                  MIN(qso_time) t0, MAX(qso_time) t1
           FROM efhw_ab_reports WHERE test_id=%s
           GROUP BY role, segment, config ORDER BY role, segment""",
        (TEST_ID,),
    )
    for r in seg_rows:
        r["t0"] = str(r["t0"]); r["t1"] = str(r["t1"])
        if r["snr_avg"] is not None:
            r["snr_avg"] = float(r["snr_avg"])

    return jsonify({
        "meta": TEST_META,
        "groups": rows,           # merged config
        "segments": seg_rows,     # per-segment
    })


# ── API: Segments breakdown ───────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/segments")
def api_segments():
    """Per-segment stats for DUT and probes, including band/modode breakdown."""
    rows = _rows(
        """SELECT role, monitored, segment, config, COUNT(*) reports,
                  COUNT(DISTINCT rx_callsign) rx, COUNT(DISTINCT dxcc) ctry,
                  ROUND(AVG(snr),1) snr_avg,
                  ROUND(AVG(distance_km),0) dist_avg,
                  MIN(qso_time) t0, MAX(qso_time) t1
           FROM efhw_ab_reports WHERE test_id=%s
           GROUP BY role, monitored, segment, config
           ORDER BY role, monitored, segment""",
        (TEST_ID,),
    )
    for r in rows:
        r["t0"] = str(r["t0"]); r["t1"] = str(r["t1"])
        for k in ("snr_avg", "dist_avg"):
            if r[k] is not None:
                r[k] = float(r[k])

    # Band breakdown per segment (DUT only)
    band_rows = _rows(
        """SELECT segment, band, COUNT(*) reports, ROUND(AVG(snr),1) snr_avg
           FROM efhw_ab_reports WHERE test_id=%s AND role='dut' AND band != ''
           GROUP BY segment, band ORDER BY segment, band""",
        (TEST_ID,),
    )
    for r in band_rows:
        if r["snr_avg"] is not None:
            r["snr_avg"] = float(r["snr_avg"])

    # Mode breakdown per segment (DUT only)
    mode_rows = _rows(
        """SELECT segment, mode, COUNT(*) reports, ROUND(AVG(snr),1) snr_avg
           FROM efhw_ab_reports WHERE test_id=%s AND role='dut' AND mode != ''
           GROUP BY segment, mode ORDER BY segment, mode""",
        (TEST_ID,),
    )
    for r in mode_rows:
        if r["snr_avg"] is not None:
            r["snr_avg"] = float(r["snr_avg"])

    return jsonify({
        "all": rows,
        "bands": band_rows,
        "modes": mode_rows,
    })


# ── API: A1-vs-A2 drift check ─────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/drift")
def api_drift():
    """Pure propagation drift: A1 vs A2 (same config, different time)."""
    dut_deltas = _segment_deltas("dut", seg_a="A1", seg_b="A2")
    dut_ds = [d["d"] for d in dut_deltas]
    dut_agg = {}
    if dut_ds:
        ci = _ci95(dut_ds)
        dut_agg = {
            "n": len(dut_ds),
            "mean": round(statistics.mean(dut_ds), 2),
            "median": round(statistics.median(dut_ds), 2),
            "sd": round(statistics.pstdev(dut_ds), 2) if len(dut_ds) > 1 else 0.0,
            "ci95": ci,
        }

    # Probe drift too
    probes = _rows(
        """SELECT DISTINCT monitored FROM efhw_ab_reports
           WHERE role='probe' AND test_id=%s ORDER BY monitored""",
        (TEST_ID,),
    )
    probe_out = []
    pooled = []
    for p in probes:
        mon = p["monitored"]
        d = _segment_deltas("probe", mon, seg_a="A1", seg_b="A2")
        ds = [x["d"] for x in d]
        if not ds:
            continue
        pooled.extend(ds)
        probe_out.append({
            "probe": mon, "n": len(ds),
            "mean": round(statistics.mean(ds), 2),
            "median": round(statistics.median(ds), 2),
        })
    probe_agg = {}
    if pooled:
        probe_agg = {
            "n": len(pooled),
            "mean": round(statistics.mean(pooled), 2),
            "median": round(statistics.median(pooled), 2),
        }

    return jsonify({
        "description": "A1 vs A2 — 同配置不同时段，纯传播漂移。若配置无变化，ΔSNR 应接近 0。",
        "dut": {"deltas": dut_deltas, "aggregate": dut_agg},
        "probes": {"items": probe_out, "pooled": probe_agg},
    })


# ── API: Paired ΔSNR (core) ───────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/paired_snr")
def api_paired_snr():
    view = request.args.get("view", "merged")  # merged | segments
    deltas = _paired_deltas("dut")
    ds = [d["d"] for d in deltas]
    agg = {}
    if ds:
        ci = _ci95(ds)
        agg = {
            "n": len(ds),
            "mean": round(statistics.mean(ds), 2),
            "median": round(statistics.median(ds), 2),
            "sd": round(statistics.pstdev(ds), 2) if len(ds) > 1 else 0.0,
            "ci95": ci,
        }
    return jsonify({"deltas": deltas, "aggregate": agg, "view": view})


# ── API: Probe baseline ───────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/probe_baseline")
def api_probe_baseline():
    # each probe's ΔSNR
    probes = _rows(
        """SELECT DISTINCT monitored FROM efhw_ab_reports
           WHERE role='probe' AND test_id=%s ORDER BY monitored""",
        (TEST_ID,),
    )
    probe_out = []
    pooled = []
    for p in probes:
        mon = p["monitored"]
        d = _paired_deltas("probe", mon)
        ds = [x["d"] for x in d]
        if not ds:
            continue
        pooled.extend(ds)
        probe_out.append({
            "probe": mon, "n": len(ds),
            "mean": round(statistics.mean(ds), 2),
            "median": round(statistics.median(ds), 2),
        })
    dut = [x["d"] for x in _paired_deltas("dut")]
    dut_mean = round(statistics.mean(dut), 2) if dut else None
    dut_med = round(statistics.median(dut), 2) if dut else None
    base_mean = round(statistics.mean(pooled), 2) if pooled else None
    base_med = round(statistics.median(pooled), 2) if pooled else None
    effect = {
        "by_mean": round(dut_mean - base_mean, 2) if None not in (dut_mean, base_mean) else None,
        "by_median": round(dut_med - base_med, 2) if None not in (dut_med, base_med) else None,
    }
    return jsonify({
        "probes": probe_out,
        "pooled_baseline": {"n": len(pooled), "mean": base_mean, "median": base_med},
        "dut": {"n": len(dut), "mean": dut_mean, "median": dut_med},
        "antenna_effect": effect,
    })


# ── API: SNR histogram ────────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/snr_hist")
def api_snr_hist():
    rows = _rows(
        """SELECT config, snr FROM efhw_ab_reports
           WHERE role='dut' AND test_id=%s AND snr IS NOT NULL""",
        (TEST_ID,),
    )
    lo, hi, step = -28, 16, 2
    bins = list(range(lo, hi + step, step))
    hist = {"A": {b: 0 for b in bins}, "B": {b: 0 for b in bins}}
    for r in rows:
        s = int(r["snr"])
        b = max(lo, min(hi, int(math.floor(s / step) * step)))
        hist[r["config"]][b] += 1
    return jsonify({
        "bins": bins,
        "A": [hist["A"][b] for b in bins],
        "B": [hist["B"][b] for b in bins],
    })


# ── API: By distance ──────────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/by_distance")
def api_by_distance():
    buckets = [(0, 1000), (1000, 2000), (2000, 3000), (3000, 5000),
               (5000, 8000), (8000, 20000)]
    labels = ["0-1k", "1-2k", "2-3k", "3-5k", "5-8k", "8k+"]
    rows = _rows(
        """SELECT config, distance_km d, snr FROM efhw_ab_reports
           WHERE role='dut' AND test_id=%s AND distance_km IS NOT NULL""",
        (TEST_ID,),
    )
    out = {"A": [{"n": 0, "snr_sum": 0} for _ in buckets],
           "B": [{"n": 0, "snr_sum": 0} for _ in buckets]}
    for r in rows:
        d = float(r["d"])
        for i, (a, b) in enumerate(buckets):
            if a <= d < b:
                out[r["config"]][i]["n"] += 1
                if r["snr"] is not None:
                    out[r["config"]][i]["snr_sum"] += int(r["snr"])
                break

    def fmt(arr):
        return [{"n": x["n"],
                 "snr": round(x["snr_sum"] / x["n"], 1) if x["n"] else None}
                for x in arr]

    return jsonify({"labels": labels, "A": fmt(out["A"]), "B": fmt(out["B"])})


# ── API: By direction ─────────────────────────────────────────────

@efhw_ab_bp.route("/api/efhw-ab/by_direction")
def api_by_direction():
    octants = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    rows = _rows(
        """SELECT config, bearing b, snr FROM efhw_ab_reports
           WHERE role='dut' AND test_id=%s AND bearing IS NOT NULL""",
        (TEST_ID,),
    )
    out = {"A": [{"n": 0, "snr_sum": 0} for _ in octants],
           "B": [{"n": 0, "snr_sum": 0} for _ in octants]}
    for r in rows:
        b = float(r["b"])
        idx = int(((b + 22.5) % 360) // 45)
        out[r["config"]][idx]["n"] += 1
        if r["snr"] is not None:
            out[r["config"]][idx]["snr_sum"] += int(r["snr"])

    def fmt(arr):
        return [{"n": x["n"],
                 "snr": round(x["snr_sum"] / x["n"], 1) if x["n"] else None}
                for x in arr]

    return jsonify({"octants": octants, "A": fmt(out["A"]), "B": fmt(out["B"])})
