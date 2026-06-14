#!/usr/bin/env python3
"""Test download 2025 file"""
import urllib.request
url = 'https://cedar.openmadrigal.org/ftp/fullname/BG1SB/email/bg1sb@ham.vlsc.net/affiliation/Individual+Radio+Amateur/kinst/8308/year/2025/kindat/17578/format/hdf5/fullFilename/%252Fopt%252Fopenmadrigal%252Fmadroot%252Fexperiments3%252F2025%252Frsd%252F01jan25%252Frsd2025-01-01.01.hdf5/'
req = urllib.request.Request(url)
req.add_header('User-Agent', 'PSKReporterFetch/1.0')
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        print(f'HTTP {r.status} Size: {len(data)} bytes')
except Exception as e:
    print(f'Error: {e}')
