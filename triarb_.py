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

# Put your API key here (used for exchangerate API calls)
EXCHANGERATE_API_KEY = "fc582c53a8ed7a0ff648920b"

# Plain URLs (no markdown)
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
        # match only symbols that are direct concatenation of tokens in ALL
        for c1, c2 in itertools.permutations(ALL, 2):
            if symbol == f"{c1}{c2}":
                rates[(c1, c2)] = price
    return rates

# ----------------------------
# GEMINI-BASED LEGALITY CHECK
# ----------------------------
def fetch_gemini_pairs() -> set:
    try:
        resp = requests.get(GEMINI_API, timeout=TIMEOUT).json()
        # Gemini returns a list of symbols like "btcusd", "ethusd", etc.
        return set([p.upper() for p in resp])
    except Exception:
        return set()


def check_legality_gemini(src: str, dst: str, gemini_pairs: set) -> bool:
    """
    Determine if a currency/crypto hop is legal.
    Combines Gemini availability and manual restriction rules.
    """
    pair_symbol = f"{src}{dst}".upper()

    # Step 1: Gemini supported pair?
    if pair_symbol in gemini_pairs:
        return True

    # Step 2: Manually restricted pairs (simulated compliance rules)
    restricted_pairs = {
        ("AED", "XRP"), ("INR", "BTC"), ("INR", "ETH"),
        ("IRR", "BTC"), ("RUB", "USD"),
    }
    if (src, dst) in restricted_pairs or (dst, src) in restricted_pairs:
        return False

    # Step 3: General assumption for major currencies
    if src in ALL and dst in ALL:
        return True

    return False

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

    # Crypto edges from Binance (and fiat-crypto if available)
    crypto_rates = fetch_crypto_rates()
    for (src, dst), rate in crypto_rates.items():
        add_trade(src, dst, rate)

    # Reciprocal edges for all edges added so far
    for u, v, data in list(G.edges(data=True)):
        if not G.has_edge(v, u):
            # avoid division by zero
            rate = data.get("rate", None)
            if rate and rate != 0:
                add_trade(v, u, 1.0 / rate)

    return G

# ----------------------------
# DFS SEARCH (LEGAL FILTER)
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
                continue  # skip illegal hops
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
    return source, target, amount

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("\n--- Multi-Hop Conversion Finder (Legal Version) ---")
    source, target, start_amount = get_user_input()
    print(f"\nConfiguration: {source} {start_amount} -> {target} (Max {MAX_HOPS} trades)")

    print("\n🔄 Building exchange graph with legality checks...")
    G = build_graph()
    if len(G.edges) == 0:
        print("❌ Graph failed to build.")
        return
    print(f"✅ Graph ready: {len(G.nodes)} currencies/cryptos, {len(G.edges)} edges (legal status included)\n")

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
        print(f"--------------------------------------------------")
        print(f"{idx}. Path: {' -> '.join(path)}")
        print(f"--------------------------------------------------")
        print(f"   Starting Amount: {start_amount:.6f} {source}")
        print(f"   Final Amount:    {final_amt:.6f} {target}")
        print(f"   Gain Multiplier: {multiplier:.6f}x (After {len(path)-1} trades, each costing {FEE*100}%)")
        print("\n   Step-by-Step Breakdown:")
        for step in breakdown:
            print(f"     {step['from']} -> {step['to']} | Rate={step['rate']:.8f} | Effective={step['effective']:.8f} | Legal={step['legal']}")
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
