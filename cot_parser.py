#!/usr/bin/env python3
import urllib.request
import re
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# URLs for COT Legacy Futures reports
URLS = {
    "CME": "https://www.cftc.gov/dea/futures/deacmesf.htm",
    "CBOT": "https://www.cftc.gov/dea/futures/deacbtsf.htm",
    "NYMEX": "https://www.cftc.gov/dea/futures/deanymesf.htm",
    "COMEX": "https://www.cftc.gov/dea/futures/deacmxsf.htm"
}

def match_asset(title, exchange):
    t = title.upper()
    
    # Exclude cross rates, spreads, and dividends
    if any(x in t for x in ["XRATE", "CROSS RATE", "CROSS-RATE", "/", "INDEX DE CONVERGENCE", "DIVIDEND"]):
        return None
        
    if exchange == "CME":
        if t.startswith("EURO FX"):
            return "EURUSD"
        if t.startswith("BRITISH POUND"):
            return "GBPUSD"
        if t.startswith("JAPANESE YEN"):
            return "USDJPY"
        if t.startswith("CANADIAN DOLLAR"):
            return "USDCAD"
        if t.startswith("SWISS FRANC"):
            return "USDCHF"
        if t.startswith("AUSTRALIAN DOLLAR"):
            return "AUDUSD"
        if t.startswith("NZ DOLLAR"):
            return "NZDUSD"
        if "NASDAQ" in t and "MINI" in t:
            return "NASDAQ"
        if ("S&P 500" in t or "S&P 500 CONSOLIDATED" in t) and "MINI" in t:
            return "SPX500"
        if "RUSSELL 2000" in t and "MINI" in t:
            return "RUSSELL"
                
    elif exchange == "CBOT":
        if "DJIA" in t or "DOW JONES INDUSTRIAL" in t:
            if any(x in t for x in ["CONSOLIDATED", "MINI", "x $5", "X$5", "X0.5", "x0.5"]):
                return "DOW"
                
    elif exchange == "NYMEX":
        if "CRUDE OIL, LIGHT SWEET" in t or "WTI FINANCIAL CRUDE OIL" in t:
            return "USOIL"
        if t.startswith("PLATINUM"):
            return "PLATINUM"
            
    elif exchange == "COMEX":
        if t.startswith("GOLD"):
            return "GOLD"
        if t.startswith("SILVER"):
            return "SILVER"
        if t.startswith("COPPER-") or t.startswith("MICRO COPPER"):
            return "COPPER"
        if "IRON ORE" in t:
            return "Iron Ore"
            
    return None

def parse_report(exchange, text):
    results = {}
    pattern = r"([A-Z0-9,\. \-\(\)\/]+)\s+-\s+(CHICAGO MERCANTILE EXCHANGE|CHICAGO BOARD OF TRADE|NEW YORK MERCANTILE EXCHANGE|COMMODITY EXCHANGE INC\.)"
    
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        block = text[start:end]
        
        full_title = matches[i].group(1).strip()
        
        mapped_name = match_asset(full_title, exchange)
        if not mapped_name:
            continue
            
        # Parse commitments numbers
        commitments_match = re.search(r"COMMITMENTS\r?\n\s*([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)\s+([\d,\-]+)", block, re.IGNORECASE)
        if commitments_match:
            try:
                non_comm_long = int(commitments_match.group(1).replace(",", ""))
                non_comm_short = int(commitments_match.group(2).replace(",", ""))
                comm_long = int(commitments_match.group(4).replace(",", ""))
                comm_short = int(commitments_match.group(5).replace(",", ""))
                
                # Sentiment calculations
                # Speculators (Non-Commercial)
                spec_total = non_comm_long + non_comm_short
                spec_long_pct = round((non_comm_long / spec_total) * 100, 2) if spec_total > 0 else 50.0
                spec_short_pct = round(100 - spec_long_pct, 2)
                
                # Commercials (Hedgers)
                comm_total = comm_long + comm_short
                comm_long_pct = round((comm_long / comm_total) * 100, 2) if comm_total > 0 else 50.0
                comm_short_pct = round(100 - comm_long_pct, 2)
                
                # Date extract
                date_match = re.search(r"POSITIONS AS OF\s+(\d{2}/\d{2}/\d{2})", block, re.IGNORECASE)
                date_str = date_match.group(1) if date_match else "Unknown"
                
                results[mapped_name] = {
                    "asset": mapped_name,
                    "original_title": full_title,
                    "exchange": exchange,
                    "date": date_str,
                    "speculator_long_pct": spec_long_pct,
                    "speculator_short_pct": spec_short_pct,
                    "commercial_long_pct": comm_long_pct,
                    "commercial_short_pct": comm_short_pct,
                    "raw": {
                        "spec_long": non_comm_long,
                        "spec_short": non_comm_short,
                        "comm_long": comm_long,
                        "comm_short": comm_short
                    }
                }
            except Exception as e:
                print(f"Error parsing commitments for {full_title}: {e}")
                
    return results

def run_scraper():
    all_data = {}
    for exchange, url in URLS.items():
        print(f"Fetching {exchange} data from {url}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode('utf-8')
                data = parse_report(exchange, html)
                all_data.update(data)
                print(f"-> Successfully parsed {len(data)} assets from {exchange}")
        except Exception as e:
            print(f"-> Error fetching/parsing {exchange}: {e}")
            
    # Sort by speculator long percentage descending
    sorted_data = dict(sorted(all_data.items(), key=lambda item: item[1]['speculator_long_pct'], reverse=True))
    
    # Save to file
    with open("cot_data.json", "w") as f:
        json.dump(list(sorted_data.values()), f, indent=2)
    print(f"\nSaved {len(sorted_data)} assets successfully to cot_data.json")
    return list(sorted_data.values())

class COTServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/cot_data.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            # Re-scrape if json doesn't exist, otherwise read it
            if not os.path.exists("cot_data.json"):
                data = run_scraper()
            else:
                with open("cot_data.json", "r") as f:
                    data = json.load(f)
                    
            self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def start_server(port=8080):
    server = HTTPServer(('0.0.0.0', port), COTServerHandler)
    print(f"\nStarting COT HTTP server on port {port}...")
    print(f"App can fetch from http://<your-pc-ip>:{port}/cot_data.json")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
        sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
        start_server(port)
    else:
        print("--- COT Commitments of Traders Parser ---")
        run_scraper()
        print("\nTo start a local server to host this data for the Android app, run:")
        print("  python cot_parser.py --server")
