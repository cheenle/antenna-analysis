#!/usr/bin/env python3
"""
DXCC opportunity recommender for PSK Reporter and space-weather data.

The module is intentionally database-free so scoring can be tested without
StarRocks/MySQL. Web/database code should pass plain row dictionaries in.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set

from band_utils import get_band_from_frequency


HIGH_BANDS = {"20m", "17m", "15m", "12m", "10m", "6m"}
LOW_BANDS = {"160m", "80m", "40m", "30m"}


def normalize_country(country: Optional[str]) -> str:
    """Return a stable country/DXCC entity label for comparisons."""
    return (country or "").strip()


def _hour_from_value(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.hour
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).hour
    except ValueError:
        return None


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _space_weather_band_adjustment(band: str, space_weather: Dict) -> float:
    f107 = _safe_float(space_weather.get("f107"))
    kp = _safe_float(space_weather.get("kp"))
    bt = _safe_float(space_weather.get("bt"))
    speed = _safe_float(space_weather.get("solar_wind_speed"))

    adjustment = 0.0
    if band in HIGH_BANDS:
        if f107 >= 150:
            adjustment += 1.4
        elif f107 >= 110:
            adjustment += 0.7
        elif f107 and f107 < 90:
            adjustment -= 0.8

        if kp >= 5:
            adjustment -= 1.8
        elif kp >= 4:
            adjustment -= 0.9
        if bt >= 10:
            adjustment -= 0.8
        if speed >= 550:
            adjustment -= 0.6
    elif band in LOW_BANDS:
        if kp < 4 and kp > 0:
            adjustment += 0.4
        if speed >= 500:
            adjustment += 0.3
        if bt >= 12:
            adjustment -= 0.4

    return adjustment


def score_candidate(candidate: Dict, space_weather: Optional[Dict] = None) -> float:
    """Score a country/band/hour opportunity. Higher means more actionable."""
    tx = int(candidate.get("tx_heard_count", 0) or 0)
    rx = int(candidate.get("rx_heard_count", 0) or 0)
    unique_callsigns = int(candidate.get("unique_callsigns", 0) or 0)
    avg_snr = _safe_float(candidate.get("avg_snr"), -30.0)

    score = 0.0
    score += math.log1p(tx) * 1.1
    score += math.log1p(rx) * 1.4
    score += math.log1p(unique_callsigns) * 0.8
    score += max(0.0, avg_snr + 24.0) / 8.0
    if tx and rx:
        score += 1.5

    if space_weather:
        score += _space_weather_band_adjustment(str(candidate.get("band", "")), space_weather)

    return round(max(score, 0.0), 3)


def _add_rows(
    accumulator: Dict,
    rows: Iterable[Dict],
    worked_countries: Set[str],
    direction: str,
) -> None:
    for row in rows:
        country = normalize_country(row.get("country"))
        if not country or country in worked_countries:
            continue

        band = get_band_from_frequency(row.get("frequency"))
        if band in {"Unknown", "Other"}:
            continue

        hour = _hour_from_value(row.get("qso_time"))
        if hour is None:
            continue

        key = (country, band, hour)
        item = accumulator.setdefault(
            key,
            {
                "country": country,
                "band": band,
                "hour": hour,
                "tx_heard_count": 0,
                "rx_heard_count": 0,
                "snr_sum": 0.0,
                "snr_count": 0,
                "callsigns": set(),
            },
        )
        if direction == "tx":
            item["tx_heard_count"] += 1
        else:
            item["rx_heard_count"] += 1
        item["snr_sum"] += _safe_float(row.get("snr"), -30.0)
        item["snr_count"] += 1
        if row.get("callsign"):
            item["callsigns"].add(str(row["callsign"]).upper())


def build_recommendations(
    worked_countries: Set[str],
    sender_rows: Iterable[Dict],
    receiver_rows: Iterable[Dict],
    space_weather: Optional[Dict] = None,
    limit: int = 20,
) -> Dict:
    """Build ranked unworked DXCC opportunities from local TX/RX evidence."""
    normalized_worked = {normalize_country(c) for c in worked_countries if normalize_country(c)}
    windows: Dict = {}
    _add_rows(windows, sender_rows, normalized_worked, "tx")
    _add_rows(windows, receiver_rows, normalized_worked, "rx")

    recommendations: List[Dict] = []
    for item in windows.values():
        count = item["snr_count"]
        avg_snr = round(item["snr_sum"] / count, 1) if count else None
        candidate = {
            "country": item["country"],
            "band": item["band"],
            "utc_hour": item["hour"],
            "tx_heard_count": item["tx_heard_count"],
            "rx_heard_count": item["rx_heard_count"],
            "unique_callsigns": len(item["callsigns"]),
            "avg_snr": avg_snr,
        }
        candidate["score"] = score_candidate(
            {
                "country": candidate["country"],
                "band": candidate["band"],
                "hour": candidate["utc_hour"],
                "tx_heard_count": candidate["tx_heard_count"],
                "rx_heard_count": candidate["rx_heard_count"],
                "unique_callsigns": candidate["unique_callsigns"],
                "avg_snr": candidate["avg_snr"],
            },
            space_weather,
        )
        candidate["confidence"] = min(95, int(round(25 + candidate["score"] * 7)))
        candidate["reason"] = _build_reason(candidate, space_weather or {})
        recommendations.append(candidate)

    recommendations.sort(key=lambda r: r["score"], reverse=True)
    return {
        "recommendations": recommendations[: max(1, int(limit))],
        "candidate_windows": len(recommendations),
        "worked_countries": len(normalized_worked),
    }


def _build_reason(candidate: Dict, space_weather: Dict) -> str:
    parts = []
    if candidate["tx_heard_count"] and candidate["rx_heard_count"]:
        parts.append("已有双向传播证据")
    elif candidate["rx_heard_count"]:
        parts.append("本台曾听到该方向")
    else:
        parts.append("本台发射曾被该方向听到")

    if candidate["avg_snr"] is not None:
        parts.append(f"平均 SNR {candidate['avg_snr']:.1f} dB")

    band = candidate["band"]
    f107 = _safe_float(space_weather.get("f107"))
    kp = _safe_float(space_weather.get("kp"))
    if band in HIGH_BANDS and f107 >= 130 and kp < 4:
        parts.append("当前高波段空间天气友好")
    elif band in HIGH_BANDS and kp >= 4:
        parts.append("地磁偏扰动，需降低置信度")
    elif band in LOW_BANDS:
        parts.append("低波段窗口更适合夜间/扰动期尝试")

    return "；".join(parts)


def summarize_space_weather(raw: Dict) -> Dict:
    """Flatten latest weather source rows and flag stale inputs."""
    values = {}
    stale = {}
    for key in ("f107", "kp", "bt", "bz", "solar_wind_speed"):
        source = raw.get(key, {})
        raw_value = source.get("value")
        values[key] = None if raw_value is None else _safe_float(raw_value)
        stale[key] = _safe_float(source.get("age_hours"), 9999) > 72

    labels = []
    if values["f107"] is not None:
        labels.append(f"F10.7 {values['f107']:.0f}")
    if values["kp"] is not None:
        labels.append(f"地磁 Kp {values['kp']:.1f}")
    if values["bt"] is not None:
        labels.append(f"Bt {values['bt']:.1f} nT")
    if values["solar_wind_speed"] is not None:
        labels.append(f"太阳风 {values['solar_wind_speed']:.0f} km/s")

    return {
        **values,
        "stale": stale,
        "summary": "，".join(labels) if labels else "暂无可用空间气象数据",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
