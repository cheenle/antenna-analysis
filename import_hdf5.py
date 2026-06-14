#!/usr/bin/env python3
"""HDF5 → StarRocks Stream Load 导入脚本"""
import h5py, numpy as np, os, sys, math, subprocess, json

# === Maidenhead grid conversion ===
def latlon_to_grid(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return ''
    lon += 180; lat += 90
    # Field
    f1 = chr(ord('A') + int(lon / 20))
    f2 = chr(ord('A') + int(lat / 10))
    # Square
    s1 = str(int((lon % 20) / 2))
    s2 = str(int((lat % 10)))
    # Subsquare
    ss1 = chr(ord('a') + int((lon % 2) * 12))
    ss2 = chr(ord('a') + int((lat % 1) * 24))
    return f1 + f2 + s1 + s2 + ss1 + ss2

# === StarRocks connection ===
SR_HOST = "ham.vlsc.net"
SR_PORT = 8030  # HTTP port for Stream Load
SR_DB = "pskreporter"
SR_TABLE = "psk_hdf5"
SR_USER = "root"
SR_PASS = ""

# === SQL to create table ===
CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {SR_TABLE} (
    id BIGINT NOT NULL,
    sender_callsign VARCHAR(20),
    receiver_callsign VARCHAR(20),
    sender_locator VARCHAR(10),
    receiver_locator VARCHAR(10),
    frequency INT,
    snr INT,
    mode VARCHAR(20),
    ssrc VARCHAR(10),
    qso_time DATETIME NOT NULL,
    distance DOUBLE,
    bearing DOUBLE,
    country VARCHAR(50)
)
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 32
PROPERTIES ("replication_num" = "1");
"""

def stream_load(csv_lines: list):
    """Stream Load CSV data into StarRocks"""
    csv_data = "\n".join(csv_lines)
    url = f"http://{SR_HOST}:{SR_PORT}/api/{SR_DB}/{SR_TABLE}/_stream_load"
    proc = subprocess.run([
        "curl", "-s", "--location-trusted", "-u", f"{SR_USER}:{SR_PASS}",
        "-H", "format: csv",
        "-H", "column_separator: |",
        "-H", "Expect:100-continue",
        "-T", "-", url
    ], input=csv_data, capture_output=True, text=True, timeout=300)
    return proc.stdout

def import_file(fpath):
    """Import one HDF5 file"""
    fname = os.path.basename(fpath)
    print(f"  Reading {fname}...", flush=True)
    
    try:
        f = h5py.File(fpath, 'r')
        data = f['Data/Table Layout']
        n = len(data)
        print(f"  {n:,} rows", flush=True)
        
        # Process in chunks of 500K
        chunk = 500000
        total_inserted = 0
        
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            batch = data[start:end]
            
            lines = []
            for i in range(len(batch)):
                row = batch[i]
                # Handle both bytes and str fields
                def _s(val): return val.decode().strip() if isinstance(val, bytes) else str(val).strip()
                tx = _s(row['call_sign_tx'])
                rx = _s(row['call_sign_rx'])
                sn_val = row['sn']
                if np.isnan(sn_val): continue  # skip NaN SNR
                sn = int(round(sn_val))
                freq = int(round(row['tfreq']))
                mode = _s(row['smode'])
                ssrc = _s(row['ssrc'])
                
                yr = int(row['year']); mo = int(row['month']); dy = int(row['day'])
                hr = int(row['hour']); mi = int(row['min']); se = int(row['sec'])
                qso_time = f"{yr:04d}-{mo:02d}-{dy:02d} {hr:02d}:{mi:02d}:{se:02d}"
                
                tx_grid = latlon_to_grid(float(row['txlat']), float(row['txlon']))
                rx_grid = latlon_to_grid(float(row['rxlat']), float(row['rxlon']))
                uid = int(row['ut1_unix']) * 1000000 + int(row['recno'])
                
                line = f"{uid}|{tx}|{rx}|{tx_grid}|{rx_grid}|{freq}|{sn}|{mode}|{ssrc}|{qso_time}|||"
                lines.append(line)
            
            result = stream_load(lines)
            
            # Parse result
            try:
                rj = json.loads(result)
                status = rj.get('Status', 'Unknown')
                rows_loaded = rj.get('NumberLoadedRows', 0)
                total_inserted += rows_loaded
                if start % (chunk * 5) == 0:
                    pct = end / n * 100
                    print(f"    {pct:.0f}% {total_inserted:,}/{n:,} rows", flush=True)
            except:
                if "Publish timeout" in result or "Success" in result:
                    total_inserted += len(lines)
            
        print(f"    Done: {total_inserted:,} rows inserted", flush=True)
        f.close()
        return total_inserted
        
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)
        return 0

# === Main ===
if __name__ == '__main__':
    import mysql.connector
    
    # Create table
    print("Creating table...", flush=True)
    conn = mysql.connector.connect(host="ham.vlsc.net", port=9030, user="root", password="", database="pskreporter")
    cur = conn.cursor()
    try:
        cur.execute(CREATE_SQL)
        print("  Table created OK", flush=True)
    except Exception as e:
        print(f"  Table may already exist: {e}", flush=True)
    cur.close()
    conn.close()
    
    # Import files
    datadir = sys.argv[1] if len(sys.argv) > 1 else "/home/cheenle/pskdata/2025"
    files = sorted([f for f in os.listdir(datadir) if f.endswith('.hdf5')])
    print(f"\nImporting {len(files)} files from {datadir}\n", flush=True)
    
    total = 0
    for fname in files:
        fpath = os.path.join(datadir, fname)
        n = import_file(fpath)
        total += n
    
    print(f"\nALL DONE: {total:,} total rows imported", flush=True)
