#!/usr/bin/env python3
"""
Shared band frequency definitions — single source of truth.

All PSK Reporter modules import band ranges from here.
One place to update when adding/modifying bands.
"""

from typing import List, Tuple, Optional, Dict

# Canonical band definitions: (low_hz, high_hz, band_name)
# Ranges follow IARU Region 3 band plans (HF/VHF amateur allocations).
BAND_RANGES: List[Tuple[int, int, str]] = [
    (1_800_000,   2_000_000,  '160m'),
    (3_500_000,   4_000_000,  '80m'),
    (5_330_000,   5_405_000,  '60m'),
    (7_000_000,   7_300_000,  '40m'),
    (10_100_000,  10_150_000, '30m'),
    (14_000_000,  14_350_000, '20m'),
    (18_068_000,  18_168_000, '17m'),
    (21_000_000,  21_450_000, '15m'),
    (24_890_000,  24_990_000, '12m'),
    (28_000_000,  29_700_000, '10m'),
    (50_000_000,  54_000_000, '6m'),
    (144_000_000, 148_000_000, '2m'),
]

# Dict form: band_name -> (low_hz, high_hz)
BAND_FREQ_MAP: Dict[str, Tuple[int, int]] = {
    name: (low, high) for low, high, name in BAND_RANGES
}

# Pre-built SQL CASE WHEN block for inlining into SELECT/GROUP BY queries.
# Usage: f"SELECT {CASE_BAND_SQL} as band, COUNT(*) ... GROUP BY band"
# WARNING: StarRocks GROUP BY on CASE expressions returns per-tablet rows (bug).
# Use SUM_BAND_SQL instead for aggregate queries.
CASE_BAND_SQL: str = (
    "CASE\n" +
    "\n".join(
        f"        WHEN frequency BETWEEN {low} AND {high} THEN '{name}'"
        for low, high, name in BAND_RANGES
    ) +
    "\n        ELSE 'Other'\n    END"
)

# SUM-based band aggregation — avoids StarRocks GROUP BY bug.
# Returns a single SQL fragment usable as:
#   SELECT {SUM_BAND_SQL} FROM {table} WHERE ...
# Result columns: band_160m, band_80m, ... band_2m, band_other
SUM_BAND_SQL: str = (
    "    " + ",\n    ".join(
        f"SUM(CASE WHEN frequency BETWEEN {low} AND {high} THEN 1 ELSE 0 END) AS band_{name}"
        for low, high, name in BAND_RANGES
    ) +
    ",\n    SUM(CASE WHEN frequency IS NOT NULL THEN 1 ELSE 0 END)"
    " - (" + " + ".join(
        f"SUM(CASE WHEN frequency BETWEEN {low} AND {high} THEN 1 ELSE 0 END)"
        for low, high, name in BAND_RANGES
    ) + ") AS band_Other"
)

# Column name list matching SUM_BAND_SQL output
SUM_BAND_COLUMNS: List[str] = [f"band_{name}" for _, _, name in BAND_RANGES] + ["band_Other"]

# Band name for each SUM column (strip "band_" prefix)
SUM_BAND_NAMES: List[str] = [c[5:] for c in SUM_BAND_COLUMNS]


def parse_sum_band_row(row: Dict) -> List[Dict]:
    """Convert a SUM_BAND_SQL result row into the standard bands list format.

    Args:
        row: Dict from cursor.fetchone() with keys like 'band_20m', 'band_40m', ...

    Returns:
        [{"band": "20m", "count": 12345}, ...] sorted by count desc
    """
    result = []
    for col, name in zip(SUM_BAND_COLUMNS, SUM_BAND_NAMES):
        cnt = int(row.get(col, 0) or 0)
        if cnt > 0:
            result.append({"band": name, "count": cnt})
    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def get_band_from_frequency(freq: Optional[int]) -> str:
    """Map a frequency in Hz to its amateur band name.

    Returns 'Unknown' for None, 'Other' for frequencies outside defined bands.
    """
    if freq is None:
        return 'Unknown'
    freq = int(freq)
    for low, high, name in BAND_RANGES:
        if low <= freq <= high:
            return name
    return 'Other'


def build_band_conditions(
    band_filter: str,
    existing_conditions: List[str],
    existing_params: List,
) -> Tuple[List[str], List]:
    """Append a band frequency WHERE clause if band_filter matches a known band.

    Returns (updated_conditions, updated_params).
    """
    if band_filter and band_filter in BAND_FREQ_MAP:
        low, high = BAND_FREQ_MAP[band_filter]
        existing_conditions.append("frequency BETWEEN %s AND %s")
        existing_params.extend([low, high])
    return existing_conditions, existing_params
