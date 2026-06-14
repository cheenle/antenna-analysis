"""Fetch VIX and SPX data using yfinance with retry"""
import yfinance as yf
import json, time

def fetch_ticker(symbol, name):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            # Use download instead of history for better rate limiting
            df = yf.download(symbol, start="2026-02-20", end="2026-06-03", progress=False)
            if df.empty:
                print(f"  {name}: empty dataframe")
                return {}
            result = {}
            for idx, row in df.iterrows():
                dt_str = idx.strftime('%Y-%m-%d')
                result[dt_str] = float(row['Close'])
            print(f"  {name}: {len(result)} data points, {min(result.keys())} ~ {max(result.keys())}")
            return result
        except Exception as e:
            print(f"  {name} attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    return {}

vix = fetch_ticker("^VIX", "VIX")
spx = fetch_ticker("^GSPC", "SPX")

# Save to file for reuse
all_data = {"VIX": vix, "SPX": spx}
with open('/Users/cheenle/pskreporter/market_data.json', 'w') as f:
    json.dump(all_data, f, indent=2)
print(f"\nSaved {len(vix)} VIX + {len(spx)} SPX data points to market_data.json")
