import requests
import itertools
import networkx as nx
import sys
from typing import List, Dict, Any, Tuple

# ----------------------------
# CONFIG
# ----------------------------
FEE = 0.001       # 0.1% per trade
MAX_HOPS = 3      # maximum trades allowed
TOP_RESULTS = 3   # top paths to display
FIATS = ["USD", "AED", "INR", "EUR", "GBP", "JPY", "CHF"]
CRYPTOS = ["BTC", "ETH", "BNB", "XRP", "USDT"]
ALL = FIATS + CRYPTOS

EXCHANGERATE_API_KEY = "fc582c53a8ed7a0ff648920b"
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"
GEMINI_API = "https://api.gemini.com/v1/symbols"
TIMEOUT = 5

# ----------------------------
# FETCH RATES
# ----------------------------
def fetch_fiat_rates(base: str) -> Dict[str, float]:
    if not EXCHANGERATE_API_KEY:
        print("ERROR: EXCHANGERATE_API_KEY is missing. Cannot fetch fiat rates.")
        return {}
    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/{base}"
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException as e:
        print(f"Request failed for {base}: {e}")
        return {}
    return r.get("conversion_rates", {})


def fetch_crypto_rates() -> Dict[Tuple[str, str], float]:
    try:
        r = requests.get(BINANCE_API, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException as e:
        print(f"Request failed for Binance API: {e}")
        return {}
    rates: Dict[Tuple[str, str], float] = {}
    for item in r:
        symbol = item.get("symbol")
        price = float(item.get("price", 0.0))
        for c1, c2 in itertools.permutations(ALL, 2):
            if symbol == f"{c1}{c2}":
                rates[(c1, c2)] = price
    return rates

# ----------------------------
# GEMINI LEGALITY
# ----------------------------
def fetch_gemini_pairs() -> set:
    try:
        resp = requests.get(GEMINI_API, timeout=TIMEOUT).json()
        return set([p.upper() for p in resp])
    except Exception:
        return set()


def check_legality_gemini(src: str, dst: str, gemini_pairs: set) -> bool:
    pair_symbol = f"{src}{dst}".upper()
    if pair_symbol in gemini_pairs:
        return True
    restricted_pairs = {("AED", "XRP"), ("INR", "BTC"), ("INR", "ETH"),
                        ("IRR", "BTC"), ("RUB", "USD")}
    if (src, dst) in restricted_pairs or (dst, src) in restricted_pairs:
        return False
    if src in ALL and dst in ALL:
        return True
    return False

# ----------------------------
# AI TAX FETCH
# ----------------------------
# Simulated AI API function to fetch country TDS/TCS rate
def fetch_country_tax(country: str, currency: str, amount: float) -> float:
    """
    Returns approximate TCS/TDS/withholding tax rate (%) for the country.
    In a real implementation, use an AI API (Gemini/OpenAI) to fetch dynamically.
    """
    # Simulated values for demonstration
    default_rates = {
        "INR": 30.0,   # India: 30% above 10 lakh
        "USD": 25.0,   # USA
        "AED": 0.0,
        "EUR": 20.0,
        "GBP": 20.0,
        "JPY": 15.0,
        "CHF": 15.0
    }
    return default_rates.get(currency, 0.0)

# ----------------------------
# BUILD GRAPH
# ----------------------------
def build_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    fiat_rates_dict: Dict[str, Dict[str, float]] = {}

    print("Fetching fiat rates...")
    for base in FIATS:
        rates = fetch_fiat_rates(base)
        if rates:
            fiat_rates_dict[base] = rates

    print("Fetching Gemini legal pairs...")
    gemini_pairs = fetch_gemini_pairs()

    def add_trade(src: str, dst: str, rate: float):
        effective = rate * (1 - FEE)
        legal = check_legality_gemini(src, dst, gemini_pairs)
        G.add_edge(src, dst, rate=rate, effective=effective, legal=legal)

    # Fiat -> Fiat
    for src in FIATS:
        if src not in fiat_rates_dict:
            continue
        for dst in FIATS:
            if src != dst and dst in fiat_rates_dict[src]:
                add_trade(src, dst, fiat_rates_dict[src][dst])

    # Crypto edges from Binance
    crypto_rates = fetch_crypto_rates()
    for (src, dst), rate in crypto_rates.items():
        add_trade(src, dst, rate)

    # Reciprocal edges
    for u, v, data in list(G.edges(data=True)):
        if not G.has_edge(v, u):
            rate = data.get("rate", None)
            if rate and rate != 0:
                add_trade(v, u, 1.0 / rate)

    return G

# ----------------------------
# DFS SEARCH
# ----------------------------
def find_paths(G: nx.DiGraph, source: str, target: str, max_hops: int):
    results: List[Tuple[List[str], float, List[Dict[str, Any]]]] = []
    total_checks = 0

    def dfs(path: List[str], multiplier: float, hops: int, breakdown: List[Dict[str, Any]]):
        nonlocal total_checks
        last = path[-1]
        if hops >= max_hops:
            return
        for nxt in G.neighbors(last):
            if nxt in path:
                continue
            edge = G[last][nxt]
            if not edge.get("legal", False):
                continue
            total_checks += 1
            new_multiplier = multiplier * edge["effective"]
            new_breakdown = breakdown + [{
                "from": last,
                "to": nxt,
                "rate": edge["rate"],
                "effective": edge["effective"],
                "legal": edge["legal"]
            }]
            new_path = path + [nxt]
            if nxt == target:
                results.append((new_path, new_multiplier, new_breakdown))
            dfs(new_path, new_multiplier, hops + 1, new_breakdown)

    dfs([source], 1.0, 0, [])
    print(f"🔍 Total edges checked during DFS: {total_checks}")
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:TOP_RESULTS]

# ----------------------------
# USER INPUT
# ----------------------------
def get_user_input():
    valid_currencies = set(ALL)
    while True:
        source = input(f"Enter source currency/crypto ({', '.join(sorted(ALL))}): ").strip().upper()
        if source in valid_currencies:
            break
        print("Invalid input.")
    while True:
        target = input(f"Enter target currency/crypto ({', '.join(sorted(ALL))}): ").strip().upper()
        if target in valid_currencies and target != source:
            break
        print("Invalid input or same as source.")
    while True:
        try:
            amount = float(input("Enter starting amount: ").strip())
            if amount > 0:
                break
            print("Amount must be positive.")
        except ValueError:
            print("Invalid input.")
    country = input("Enter country for tax calculation: ").strip()
    return source, target, amount, country

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("\n--- Multi-Hop Conversion Finder (Legal + Tax) ---")
    source, target, start_amount, country = get_user_input()
    print(f"\nConfiguration: {source} {start_amount} -> {target} (Max {MAX_HOPS} trades) in {country}")

    print("\n🔄 Building exchange graph with legality checks...")
    G = build_graph()
    if len(G.edges) == 0:
        print("❌ Graph failed to build.")
        return
    print(f"✅ Graph ready: {len(G.nodes)} currencies/cryptos, {len(G.edges)} edges\n")

    print(f"🔍 Searching all legal paths from {source} -> {target} (up to {MAX_HOPS} trades)...\n")
    paths = find_paths(G, source, target, MAX_HOPS)
    if not paths:
        print(f"No legal paths found from {source} -> {target} within {MAX_HOPS} trades.")
        return

    print(f"--- Top {len(paths)} Legal Paths Found ---\n")
    best_amt = 0.0
    best_idx = 0

    for idx, (path, multiplier, breakdown) in enumerate(paths, 1):
        final_amt = start_amount * multiplier
        tax_rate = fetch_country_tax(country, target, final_amt)
        tax_amt = final_amt * tax_rate / 100
        net_amt = final_amt - tax_amt

        print(f"--------------------------------------------------")
        print(f"{idx}. Path: {' -> '.join(path)}")
        print(f"--------------------------------------------------")
        print(f"   Starting Amount: {start_amount:.6f} {source}")
        print(f"   Final Amount:    {final_amt:.6f} {target}")
        print(f"   Tax Rate:        {tax_rate}%")
        print(f"   Tax Deducted:    {tax_amt:.6f} {target}")
        print(f"   Net Amount:      {net_amt:.6f} {target}")
        print(f"   Gain Multiplier: {multiplier:.6f}x (After {len(path)-1} trades, fee {FEE*100}%)")
        print("\n   Step-by-Step Breakdown:")
        for step in breakdown:
            print(f"     {step['from']} -> {step['to']} | Rate={step['rate']:.8f} | Effective={step['effective']:.8f} | Legal={step['legal']}")
        print()
        if net_amt > best_amt:
            best_amt = net_amt
            best_idx = idx

    print(f"✅ Best path is #{best_idx} with net amount {best_amt:.6f} {target}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
        sys.exit(0)
