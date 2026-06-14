#!/usr/bin/env python3
"""
FT8 SNR by Band & Continent vs VIX/SPX correlation analysis - DEEP DIVE
Global SNR-VIX r=0.51. Now: which bands/continents drive this signal?
"""
import mysql.connector
import json, sys, csv, io, urllib.request, time
sys.path.insert(0, '/Users/cheenle/pskreporter')
from dxcc_lookup import lookup_callsign
from band_utils import CASE_BAND_SQL
from datetime import datetime
from collections import defaultdict
import math

conn = mysql.connector.connect(host='ham.vlsc.net', port=9030, user='root', password='', database='pskreporter', charset='utf8mb4')
cur = conn.cursor(dictionary=True)

# ============================================================
# Part 1: Fetch market data (VIX, SPX) from CBOE (free, no auth)
# ============================================================
print("=== 1. Market Data (CBOE) ===")

def fetch_cboe(symbol, date_col=0, close_col=3):
    """Fetch daily data from CBOE CSV endpoint"""
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    result = {}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode('utf-8')
                reader = csv.reader(io.StringIO(data))
                header = next(reader)
                for row in reader:
                    if not row:
                        continue
                    dt_str = row[date_col].strip()
                    close_str = row[close_col].strip()
                    if dt_str and close_str:
                        try:
                            # Convert MM/DD/YYYY to YYYY-MM-DD
                            parts = dt_str.split('/')
                            if len(parts) == 3:
                                dt_iso = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                            else:
                                dt_iso = dt_str
                            result[dt_iso] = float(close_str)
                        except (ValueError, IndexError):
                            pass
                return result
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  {symbol} error: {e}")
                return {}

vix_data = fetch_cboe("VIX")
print(f"  VIX: {len(vix_data)} data points from {min(vix_data.keys()) if vix_data else 'N/A'} to {max(vix_data.keys()) if vix_data else 'N/A'}")

spx_data = fetch_cboe("SPX", close_col=1)  # SPX has DATE,SPX format
print(f"  SPX: {len(spx_data)} data points from {min(spx_data.keys()) if spx_data else 'N/A'} to {max(spx_data.keys()) if spx_data else 'N/A'}")

# ============================================================
# Part 2: Daily FT8 SNR by Band
# ============================================================
print("\n=== 2. Daily SNR by Band ===")
bands_sql = f'''
    SELECT DATE(qso_time) dt,
           {CASE_BAND_SQL} as band,
           COUNT(*) spots, AVG(snr) avg_snr,
           COUNT(DISTINCT sender_callsign) senders,
           COUNT(DISTINCT sender_dxcc) dxcc_count
    FROM all_records
    WHERE qso_time >= '2026-02-25' AND snr IS NOT NULL
    GROUP BY dt, band ORDER BY dt, band
'''
cur.execute(bands_sql)
band_rows = cur.fetchall()
print(f"  {len(band_rows)} band-day rows")

band_daily = defaultdict(dict)
for r in band_rows:
    dt_str = str(r['dt'])
    band = r['band']
    band_daily[band][dt_str] = {
        'avg_snr': float(r['avg_snr']),
        'spots': r['spots'],
        'senders': r['senders'],
        'dxcc': r['dxcc_count']
    }

# ============================================================
# Part 3: Daily SNR by Continent (via lookup_callsign on sender_dxcc prefix)
# ============================================================
print("\n=== 3. Daily SNR by Continent ===")
cur.execute('''
    SELECT DATE(qso_time) dt, sender_dxcc, COUNT(*) spots, AVG(snr) avg_snr
    FROM all_records
    WHERE qso_time >= '2026-02-25' AND snr IS NOT NULL AND sender_dxcc IS NOT NULL AND sender_dxcc != ''
    GROUP BY dt, sender_dxcc ORDER BY dt, sender_dxcc
''')
dxcc_rows = cur.fetchall()
print(f"  {len(dxcc_rows)} prefix-day rows")

# Continent mapping cache
prefix_continent_cache = {}

def get_continent_from_prefix(prefix):
    if prefix in prefix_continent_cache:
        return prefix_continent_cache[prefix]
    result = lookup_callsign(prefix)
    if result:
        cont = result['continent']
    else:
        cont = 'XX'
    prefix_continent_cache[prefix] = cont
    return cont

continent_daily = defaultdict(lambda: defaultdict(lambda: {'w_snr': 0.0, 'spots': 0}))
unknown = set()

for r in dxcc_rows:
    dt_str = str(r['dt'])
    prefix = r['sender_dxcc']
    cont = get_continent_from_prefix(prefix)
    if cont == 'XX':
        unknown.add(prefix)
        continue
    continent_daily[cont][dt_str]['w_snr'] += float(r['avg_snr']) * r['spots']
    continent_daily[cont][dt_str]['spots'] += r['spots']

if unknown:
    print(f"  Unresolved prefixes ({len(unknown)}): {sorted(unknown)[:30]}")

# Compute final daily avg SNR per continent
continent_final = {}
for cont in ['AS','EU','NA','SA','AF','OC','AN']:
    dates = continent_daily.get(cont, {})
    if not dates:
        continue
    result = {}
    for dt, vals in dates.items():
        if vals['spots'] > 0:
            result[dt] = vals['w_snr'] / vals['spots']
    if result:
        continent_final[cont] = result

cont_names = {'AS':'Asia','EU':'Europe','NA':'North America','SA':'South America',
              'AF':'Africa','OC':'Oceania','AN':'Antarctica'}

# ============================================================
# Part 4: Correlation by Band and Continent
# ============================================================
print("\n=== 4. Correlation Analysis ===")

def pearson_r(x, y):
    n = len(x)
    if n < 5:
        return None, None, n
    mx = sum(x)/n
    my = sum(y)/n
    sx = math.sqrt(sum((xi-mx)**2 for xi in x)/(n-1))
    sy = math.sqrt(sum((yi-my)**2 for yi in y)/(n-1))
    if sx == 0 or sy == 0:
        return None, None, n
    cov = sum((xi-mx)*(yi-my) for xi,yi in zip(x,y))/(n-1)
    r = cov/(sx*sy)
    t = r * math.sqrt((n-2)/(1-r*r)) if abs(r) < 1 else float('inf')
    return r, t, n

try:
    from scipy import stats as scipy_stats
    def calc_p(t, df):
        return 2 * scipy_stats.t.sf(abs(t), df)
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    def calc_p(t, df):
        return None

# 4a. Band vs VIX
print("\n--- BAND SNR vs VIX ---")
band_vix_results = []
for band in ['160m','80m','40m','30m','20m','17m','15m','12m','10m','6m']:
    dates = band_daily.get(band, {})
    snr_v, vix_v = [], []
    for dt in sorted(dates.keys()):
        if dt in vix_data:
            snr_v.append(dates[dt]['avg_snr'])
            vix_v.append(vix_data[dt])
    if len(snr_v) < 10:
        continue
    r, t_stat, n = pearson_r(snr_v, vix_v)
    p = calc_p(t_stat, n-2) if t_stat else None
    spots_daily = sum(dates[dt]['spots'] for dt in dates if dt in vix_data)/max(len(snr_v),1)
    band_vix_results.append((band, r, n, p, spots_daily))

band_vix_results.sort(key=lambda x: abs(x[1]) if x[1] is not None else 0, reverse=True)

print(f"{'Band':<8} {'r(SNR~VIX)':>12} {'N':>5} {'p-value':>10} {'DailySpots':>14}")
print("-" * 55)
for band, r, n, p, spots_day in band_vix_results:
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else ""))
    p_str = f"{p:.4f}{sig}" if p else "-"
    print(f"{band:<8} {r:>+12.4f} {n:>5} {p_str:>10} {spots_day:>14,.0f}")

# 4b. Band vs SPX
print("\n--- BAND SNR vs SPX ---")
for band,_,_,_,_ in band_vix_results:
    dates = band_daily.get(band, {})
    snr_v, spx_v = [], []
    for dt in sorted(dates.keys()):
        if dt in spx_data:
            snr_v.append(dates[dt]['avg_snr'])
            spx_v.append(spx_data[dt])
    if len(snr_v) < 10:
        continue
    r, t_stat, n = pearson_r(snr_v, spx_v)
    p = calc_p(t_stat, n-2) if t_stat else None
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else ""))
    p_str = f"{p:.4f}{sig}" if p else "-"
    print(f"{band:<8} {r:>+12.4f} {n:>5} {p_str:>10}")

# 4c. Continent vs VIX
print("\n--- CONTINENT SNR vs VIX ---")
cont_results = []
for cont in ['AS','EU','NA','SA','AF','OC']:
    dates = continent_final.get(cont, {})
    snr_v, vix_v = [], []
    for dt in sorted(dates.keys()):
        if dt in vix_data:
            snr_v.append(dates[dt])
            vix_v.append(vix_data[dt])
    if len(snr_v) < 10:
        continue
    r, t_stat, n = pearson_r(snr_v, vix_v)
    p = calc_p(t_stat, n-2) if t_stat else None
    total_spots = sum(continent_daily[cont][dt]['spots'] for dt in continent_daily[cont])
    cont_results.append((cont, cont_names.get(cont, cont), r, n, p, total_spots))

cont_results.sort(key=lambda x: abs(x[2]) if x[2] is not None else 0, reverse=True)

print(f"{'Cont':<6} {'Name':<18} {'r(SNR~VIX)':>12} {'N':>5} {'p-value':>10} {'Spots':>14}")
print("-" * 70)
for cont, cname, r, n, p, spots in cont_results:
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else ""))
    p_str = f"{p:.4f}{sig}" if p else "-"
    print(f"{cont:<6} {cname:<18} {r:>+12.4f} {n:>5} {p_str:>10} {spots:>14,d}")

# 4d. Continent vs SPX
print("\n--- CONTINENT SNR vs SPX ---")
for cont, cname, _, _, _, _ in cont_results:
    dates = continent_final.get(cont, {})
    snr_v, spx_v = [], []
    for dt in sorted(dates.keys()):
        if dt in spx_data:
            snr_v.append(dates[dt])
            spx_v.append(spx_data[dt])
    if len(snr_v) < 10:
        continue
    r, t_stat, n = pearson_r(snr_v, spx_v)
    p = calc_p(t_stat, n-2) if t_stat else None
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else ""))
    p_str = f"{p:.4f}{sig}" if p else "-"
    print(f"{cont:<6} {cname:<18} {r:>+12.4f} {n:>5} {p_str:>10}")

# ============================================================
# Part 5: Band × Continent Cross Analysis
# ============================================================
print("\n=== 5. Band × Continent Cross-Correlation with VIX ===")
cur.execute(f'''
    SELECT DATE(qso_time) dt,
           {CASE_BAND_SQL} as band,
           sender_dxcc,
           COUNT(*) spots, AVG(snr) avg_snr
    FROM all_records
    WHERE qso_time >= '2026-02-25' AND snr IS NOT NULL AND sender_dxcc IS NOT NULL AND sender_dxcc != ''
    GROUP BY dt, band, sender_dxcc ORDER BY dt, band, sender_dxcc
''')
cross_rows = cur.fetchall()
print(f"  {len(cross_rows)} band-prefix-day rows")

# Build band×continent daily SNR
cross_daily = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'w_snr': 0.0, 'spots': 0})))
for r in cross_rows:
    dt_str = str(r['dt'])
    band = r['band']
    if band == 'Other':
        continue
    cont = get_continent_from_prefix(r['sender_dxcc'])
    if cont == 'XX':
        continue
    cross_daily[band][cont][dt_str]['w_snr'] += float(r['avg_snr']) * r['spots']
    cross_daily[band][cont][dt_str]['spots'] += r['spots']

# Correlate
bands = ['160m','80m','40m','30m','20m','17m','15m','12m','10m','6m']
conts = ['AS','EU','NA','SA','AF','OC']
cross_results = []

for band in bands:
    for cont in conts:
        dates = cross_daily.get(band, {}).get(cont, {})
        snr_v, vix_v = [], []
        for dt in sorted(dates.keys()):
            if dt in vix_data and dates[dt]['spots'] > 0:
                snr_v.append(dates[dt]['w_snr']/dates[dt]['spots'])
                vix_v.append(vix_data[dt])
        if len(snr_v) < 10:
            continue
        r, t_stat, n = pearson_r(snr_v, vix_v)
        p = calc_p(t_stat, n-2) if t_stat else None
        cross_results.append((band, cont, r, n, p))

cross_results.sort(key=lambda x: abs(x[2]) if x[2] is not None else 0, reverse=True)

print(f"\n{'Band':<8} {'Cont':<6} {'r(SNR~VIX)':>12} {'N':>5} {'p-value':>10}  Sig")
print("-" * 58)
for band, cont, r, n, p in cross_results[:25]:
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else ""))
    p_str = f"{p:.4f}" if p else "-"
    print(f"{band:<8} {cont:<6} {r:>+12.4f} {n:>5} {p_str:>10}  {sig}")

sig_count = sum(1 for x in cross_results if x[4] and x[4] < 0.05)
print(f"\n显著(p<0.05)组合: {sig_count}/{len(cross_results)}")

# ============================================================
# Part 6: Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY - FT8 SNR vs Market (2026-02-25 ~ 2026-06-01, 97 days)")
print("=" * 70)

if vix_data:
    print(f"VIX: {min(vix_data.values()):.2f} ~ {max(vix_data.values()):.2f} ({len(vix_data)} trading days)")
if spx_data:
    print(f"SPX: {min(spx_data.values()):.0f} ~ {max(spx_data.values()):.0f} ({len(spx_data)} trading days)")

print(f"\nBaseline (global):")
print(f"  SNR↔VIX  r=+0.51 (p<.001)")
print(f"  SNR↔SPX  r=-0.31 (p=.003)")

print(f"\nTop Band Drivers (SNR~VIX):")
for band, r, n, p, spots_day in band_vix_results[:3]:
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else "ns"))
    print(f"  {band:<8} r={r:>+7.4f} n={n:>3} {sig} ({spots_day:,.0f} spots/day)")

print(f"\nTop Continent Drivers (SNR~VIX):")
for cont, cname, r, n, p, spots in cont_results[:3]:
    sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else "ns"))
    print(f"  {cont} {cname:<18} r={r:>+7.4f} n={n:>3} {sig} ({spots:,d} total spots)")

if cross_results:
    print(f"\nTop Band×Continent Drivers (SNR~VIX):")
    for band, cont, r, n, p in cross_results[:5]:
        sig = "***" if p and p<0.001 else ("**" if p and p<0.01 else ("*" if p and p<0.05 else "ns"))
        p_str = f"p={p:.4f}" if p else "-"
        print(f"  {band:>6s}×{cont} {cont_names.get(cont,cont):<18} r={r:>+7.4f} n={n:>3} {sig} {p_str}")

cur.close()
conn.close()
