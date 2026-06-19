#!/usr/bin/env python3
"""EFHW A/B comparison dashboard — self-contained Flask Blueprint.

Serves the /efhw-ab page plus JSON APIs, all backed by the dedicated
StarRocks table `efhw_ab_reports` (role=dut|probe, config=A|B). Kept out of
the 4000-line web_app.py; web_app.py only does `register_blueprint`.

Methodology recap (why these endpoints exist):
  * Report COUNT is polluted by TX duty cycle — it is NOT a valid antenna
    metric. We surface it but label it as such.
  * Per-common-receiver ΔSNR (same callsign in both A and B) is the valid
    paired metric: each receiver is its own control, cancelling path/distance.
  * ON80 probe stations (antenna fixed) give a propagation baseline; the
    antenna's net effect = DUT ΔSNR − probe ΔSNR.

APIs (all GET, return JSON):
  /api/efhw-ab/summary         test metadata + per role/config counts
  /api/efhw-ab/paired_snr      DUT per-common-receiver ΔSNR + aggregate
  /api/efhw-ab/probe_baseline  each probe's ΔSNR + pooled baseline + net effect
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
    "band": "15m · 21.074 MHz · FT8",
    "power": "100 W",
    "dut": "BG1SB",
    "grid": "ON80da",
    "switch_cst": "2026-06-19 12:26:52",
    "config_a": {"name": "49:1 变压器 (3×FT-240-51)", "swr": 1.47},
    "config_b": {"name": "LC 调谐器", "swr": 1.30},
    "mismatch_loss_a_db": 0.16,   # SWR 1.47
    "mismatch_loss_b_db": 0.075,  # SWR 1.30
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


def _paired_deltas(role, monitored=None):
    """Per-common-receiver ΔSNR = mean(B) − mean(A) for a station.

    Returns list of dicts {rx, mean_a, mean_b, d, n_a, n_b}.
    """
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


@efhw_ab_bp.route("/efhw-ab")
def efhw_ab_page():
    return render_template("efhw_ab.html", active_page="efhw_ab")


@efhw_ab_bp.route("/api/efhw-ab/summary")
def api_summary():
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
    return jsonify({"meta": TEST_META, "groups": rows})


@efhw_ab_bp.route("/api/efhw-ab/paired_snr")
def api_paired_snr():
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
    return jsonify({"deltas": deltas, "aggregate": agg})


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
