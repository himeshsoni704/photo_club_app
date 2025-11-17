# Multi-hop currency/crypto conversion finder (up to 3 trades)
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

EXCHANGERATE_API_KEY = "fc582c53a8ed7a0ff648920b"  # <<< INSERT YOUR API KEY HERE >>>
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"
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
    rates = {}
    for item in r:
        symbol = item["symbol"]
        price = float(item["price"])
        for c1, c2 in itertools.permutations(ALL, 2):
            if symbol == f"{c1}{c2}":
                rates[(c1, c2)] = price
    return rates

# ----------------------------
# BUILD GRAPH
# ----------------------------
def build_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    fiat_rates_dict = {}
    for base in FIATS:
        rates = fetch_fiat_rates(base)
        if rates:
            fiat_rates_dict[base] = rates

    def add_trade(src: str, dst: str, rate: float):
        effective = rate * (1 - FEE)
        G.add_edge(src, dst, rate=rate, effective=effective)

    # Fiat -> Fiat
    for src in FIATS:
        if src not in fiat_rates_dict: continue
        for dst in FIATS:
            if src != dst and dst in fiat_rates_dict[src]:
                add_trade(src, dst, fiat_rates_dict[src][dst])

    # Crypto edges
    crypto_rates = fetch_crypto_rates()
    for (src, dst), rate in crypto_rates.items():
        add_trade(src, dst, rate)

    # Reciprocal edges
    temp_edges = list(G.edges(data=True))
    for u, v, data in temp_edges:
        if not G.has_edge(v, u):
            add_trade(v, u, 1.0 / data["rate"])

    return G

# ----------------------------
# DFS SEARCH
# ----------------------------
def find_paths(G: nx.DiGraph, source: str, target: str, max_hops: int):
    results = []
    total_checks = 0

    def dfs(path: List[str], multiplier: float, hops: int, breakdown: List[Dict[str, Any]]):
        nonlocal total_checks
        last = path[-1]
        if hops >= max_hops: return
        for nxt in G.neighbors(last):
            if nxt in path: continue
            total_checks += 1
            edge = G[last][nxt]
            new_multiplier = multiplier * edge["effective"]
            new_breakdown = breakdown + [{
                "from": last, "to": nxt, "rate": edge["rate"], "effective": edge["effective"]
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
        if source in valid_currencies: break
        print("Invalid input.")
    while True:
        target = input(f"Enter target currency/crypto ({', '.join(sorted(ALL))}): ").strip().upper()
        if target in valid_currencies and target != source: break
        print("Invalid input or same as source.")
    while True:
        try:
            amount = float(input("Enter starting amount: ").strip())
            if amount > 0: break
            print("Amount must be positive.")
        except ValueError:
            print("Invalid input.")
    return source, target, amount

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("\n--- Multi-Hop Conversion Finder ---")
    source, target, start_amount = get_user_input()
    print(f"\nConfiguration: {source} {start_amount} -> {target} (Max {MAX_HOPS} trades)")

    print("\n🔄 Building exchange graph...")
    G = build_graph()
    if len(G.edges) == 0:
        print("❌ Graph failed to build.")
        return
    print(f"✅ Graph ready: {len(G.nodes)} currencies/cryptos, {len(G.edges)} effective edges\n")

    print(f"🔍 Searching all paths from {source} -> {target} (up to {MAX_HOPS} trades)...\n")
    paths = find_paths(G, source, target, MAX_HOPS)
    if not paths:
        print(f"No paths found from {source} -> {target} within {MAX_HOPS} trades.")
        return

    print(f"--- Top {len(paths)} Paths Found ---\n")
    best_amt = 0
    best_idx = 0
    for idx, (path, multiplier, breakdown) in enumerate(paths, 1):
        final_amt = start_amount * multiplier
        print(f"--------------------------------------------------")
        print(f"{idx}. Path: {' -> '.join(path)}")
        print(f"--------------------------------------------------")
        print(f"   Starting Amount: {start_amount:.6f} {source}")
        print(f"   Final Amount:    {final_amt:.6f} {target}")
        print(f"   Gain Multiplier: {multiplier:.6f}x (After {len(path)-1} trades, each costing {FEE*100}%)")
        print("\n   Step-by-Step Breakdown:")
        for step in breakdown:
            print(f"     {step['from']} -> {step['to']} | Direct Rate={step['rate']:.8f} | Effective Rate={step['effective']:.8f}")
        print()
        if final_amt > best_amt:
            best_amt = final_amt
            best_idx = idx

    print(f"✅ Best path is #{best_idx} with final amount {best_amt:.6f} {target}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScript terminated by user.")
        sys.exit(0)
