"""Debug sender_dxcc field values and DXCC lookup"""
import sys, mysql.connector
sys.path.insert(0, '/Users/cheenle/pskreporter')
from dxcc_lookup import get_dxcc_info

# Test by ADIF code
print("=== get_dxcc_info by ADIF code ===")
for code in [263, 1, 339, 291, 54, 61, 100, 117]:
    info = get_dxcc_info(code)
    name = info['name'] if info else 'NOT FOUND'
    print(f'  ADIF {code:3d} -> {name}')

print()

conn = mysql.connector.connect(host='ham.vlsc.net', port=9030, user='root', password='', database='pskreporter')
cur = conn.cursor()

# But wait - sender_dxcc might be the COUNTRY name, not the ADIF code
# Let's check actual values
cur.execute("SELECT sender_dxcc, COUNT(*) cnt FROM all_records WHERE qso_time >= '2026-02-25' AND sender_dxcc IS NOT NULL AND sender_dxcc != '' GROUP BY sender_dxcc ORDER BY cnt DESC LIMIT 30")
print('=== Top 30 sender_dxcc values ===')
for val, cnt in cur.fetchall():
    # Try as ADIF int
    name = None
    try:
        info = get_dxcc_info(int(val))
        if info:
            name = info['name']
    except (ValueError, TypeError):
        pass
    if not name:
        info = get_dxcc_info(val)
        if info:
            name = info['name']
    name = name or 'NOT FOUND'
    print(f'  {val:10s} cnt={cnt:>10,d}  -> {name}')

print()

# What type are the values? Let's check sample
cur.execute("SELECT DISTINCT sender_dxcc FROM all_records WHERE sender_dxcc IS NOT NULL AND sender_dxcc != '' LIMIT 50")
samples = [r[0] for r in cur.fetchall()]
print(f'Sample values: {samples[:20]}')

# Count numeric vs non-numeric
numeric = sum(1 for s in samples if s.isdigit())
print(f'Numeric: {numeric}, Non-numeric: {len(samples)-numeric}')

cur.close()
conn.close()
