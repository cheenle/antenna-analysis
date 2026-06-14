#!/usr/bin/env python3
"""从 Madrigal 下载 PSK Reporter HDF5 并聚合每日 SNR/count/DXCC"""
import urllib.request, urllib.parse, os, json, sys, datetime, gzip

BASE = "https://cedar.openmadrigal.org/ftp/fullname/BG1SB/email/bg1sb@ham.vlsc.net/affiliation/Individual+Radio+Amateur/kinst/8308/year"

MONTH_ABBR = {1:'jan',2:'feb',3:'mar',4:'apr',5:'may',6:'jun',
              7:'jul',8:'aug',9:'sep',10:'oct',11:'nov',12:'dec'}

def build_url(year, month, day):
    """Build Madrigal download URL for a given date"""
    mmmyy = f"{day:02d}{MONTH_ABBR[month]}{str(year)[2:]}"
    filename = f"rsd{year:04d}-{month:02d}-{day:02d}.01.hdf5"
    # URL-encoded path
    raw_path = f"/opt/openmadrigal/madroot/experiments4/{year}/rsd/{mmmyy}/{filename}"
    encoded = urllib.parse.quote(urllib.parse.quote(raw_path, safe=''), safe='')
    url = f"{BASE}/{year}/kindat/17578/format/hdf5/fullFilename/{encoded}/"
    return url, filename

def download_file(url, dest):
    """Download with retry"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "PSKReporterFetch/1.0 (BG1SB; bg1sb@ham.vlsc.net)")
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                if len(data) < 10000:  # too small = error page
                    continue
                with open(dest, 'wb') as f:
                    f.write(data)
                return True
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
    return False

def aggregate_hdf5(filepath):
    """Extract daily aggregates from HDF5: total spots, avg SNR, unique DXCC, etc.
    Falls back to reading HDF5 with h5py if available."""
    try:
        import h5py
    except ImportError:
        return None
    
    try:
        with h5py.File(filepath, 'r') as f:
            # Explore structure
            def explore(name, obj):
                pass  # We'll figure out the structure from the first file
            
            # Try common dataset names
            snr_data = None
            count = 0
            for key in f.keys():
                if 'snr' in key.lower() or 'signal' in key.lower():
                    ds = f[key]
                    if hasattr(ds, '__len__'):
                        snr_data = ds[:]
                        count = len(snr_data)
            
            if snr_data is not None and count > 0:
                import numpy as np
                snr_arr = np.array(snr_data, dtype=float)
                snr_arr = snr_arr[np.isfinite(snr_arr)]
                return {
                    'spots': int(count),
                    'snr_avg': round(float(np.mean(snr_arr)), 2),
                    'snr_min': int(np.min(snr_arr)),
                    'snr_max': int(np.max(snr_arr)),
                }
    except Exception as e:
        print(f"  HDF5 read error: {e}")
    return None

# ===== Main: test download of 1 file first =====
if __name__ == '__main__':
    year, month, day = 2024, 6, 15
    url, fname = build_url(year, month, day)
    dest = f"/tmp/{fname}"
    
    print(f"URL: {url}")
    print(f"Downloading {fname}...")
    
    if download_file(url, dest):
        size_mb = os.path.getsize(dest) / 1e6
        print(f"Downloaded: {size_mb:.1f} MB")
        
        result = aggregate_hdf5(dest)
        if result:
            print(f"Daily aggregates: {result}")
        else:
            print("HDF5 aggregation failed (need h5py or different structure)")
            # Show HDF5 structure
            try:
                import h5py
                with h5py.File(dest, 'r') as f:
                    print("\nHDF5 structure:")
                    f.visititems(lambda name, obj: print(f"  {name}: {type(obj).__name__}" + 
                          (f" shape={obj.shape}" if hasattr(obj, 'shape') else "")))
            except:
                print("Cannot read HDF5 structure")
    else:
        print("Download failed")
