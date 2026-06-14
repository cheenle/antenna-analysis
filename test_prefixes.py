"""Verify lookup_callsign works for sender_dxcc prefix values"""
import sys
sys.path.insert(0, '/Users/cheenle/pskreporter')
from dxcc_lookup import lookup_callsign

test_prefixes = ['K', 'UA', 'JA', 'I', 'DL', 'EA', 'F', 'G', 'SP', 'BY', 
                 'VE', 'PA', 'UR', 'UA9', 'PY', 'SV', 'YO', 'ON', 'VK', 
                 'LZ', 'HA', 'YB', '9A', 'OH', 'CT', 'HB', 'OK', 'TA', 
                 'OE', 'SM', 'SV5', 'HB0']

for pfx in test_prefixes:
    result = lookup_callsign(pfx)
    if result:
        print(f'{pfx:10s} -> {result["name"]:30s} ({result["continent"]})')
    else:
        print(f'{pfx:10s} -> NOT FOUND')
