#!/usr/bin/env python3
"""极简重试下载器 - 每30秒试一个文件，失败跳过，循环直到全部完成"""
import urllib.request, urllib.parse, os, time, calendar

BASE = "https://cedar.openmadrigal.org/ftp/fullname/BG1SB/email/bg1sb@ham.vlsc.net/affiliation/Individual+Radio+Amateur/kinst/8308/year"
MON = {1:"jan",2:"feb",3:"mar",4:"apr",5:"may",6:"jun",
       7:"jul",8:"aug",9:"sep",10:"oct",11:"nov",12:"dec"}
OUT = "/home/cheenle/pskdata/2025"
YEAR = 2025
os.makedirs(OUT, exist_ok=True)
print(f"Starting download: {OUT}", flush=True)

def build_url(y, m, d):
    mmmyy = f"{d:02d}{MON[m]}{str(y)[2:]}"
    fname = f"rsd{y}-{m:02d}-{d:02d}.01.hdf5"
    for exp in ["experiments3","experiments4","experiments2"]:
        raw = f"/opt/openmadrigal/madroot/{exp}/{y}/rsd/{mmmyy}/{fname}"
        enc = urllib.parse.quote(urllib.parse.quote(raw,safe=""),safe="")
        yield f"{BASE}/{y}/kindat/17578/format/hdf5/fullFilename/{enc}/", fname, exp

def dl(url, dest, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"PSKReporter/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if len(data) > 10000:
                with open(dest,"wb") as f: f.write(data)
                return len(data)
    except: pass
    return 0

total = 366 if calendar.isleap(YEAR) else 365

while True:
    for m in range(1,13):
        for d in range(1, calendar.monthrange(YEAR,m)[1]+1):
            fname = f"rsd{YEAR}-{m:02d}-{d:02d}.01.hdf5"
            dest = os.path.join(OUT, fname)
            if os.path.exists(dest) and os.path.getsize(dest) > 10000:
                continue
            
            for url, _, exp in build_url(YEAR, m, d):
                t0 = time.time()
                sz = dl(url, dest, timeout=60)
                if sz > 10000:
                    elapsed = time.time() - t0
                    print(f"OK {fname} {sz/1e6:.0f}MB {elapsed:.0f}s [{exp}]", flush=True)
                    break
            else:
                print(f"FAIL {fname}", flush=True)
            
            time.sleep(5)  # 礼貌间隔
    
    # Check completion
    done = sum(1 for _ in range(1,13) for d in range(1,calendar.monthrange(YEAR,_)[1]+1) 
               if os.path.exists(os.path.join(OUT, f"rsd{YEAR}-{_:02d}-{d:02d}.01.hdf5")) 
               and os.path.getsize(os.path.join(OUT, f"rsd{YEAR}-{_:02d}-{d:02d}.01.hdf5")) > 10000)
    
    print(f"\n=== Round complete: {done}/{total} files ===\n", flush=True)
    if done >= total:
        print("ALL DONE!", flush=True)
        break
    time.sleep(300)  # 5分钟后再来一轮
