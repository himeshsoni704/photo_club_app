# Multi-hop currency/crypto conversion finder with DFS / Bellman-Ford (K-hops) / A*
# Up to MAX_HOPS trades. Choose algorithm at runtime.

import requests
import itertools
import networkx as nx
import heapq
import math
import sys
import time
from typing import List, Dict, Any, Tuple, Optional

# ----------------------------
# CONFIG
# ----------------------------
FEE = 0.001       # 0.1% per trade
MAX_HOPS = 3      # maximum trades allowed
MIN_GAIN = 1.0    # minimum multiplier to consider (1.0 = break even)
TOP_RESULTS = 3   # top results for DFS listing

# Expanded Fiat List (you can add more currencies)
FIATS = [
    "USD", "AED", "INR", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
    "NZD", "SGD", "HKD", "MXN", "BRL", "ZAR", "TRY"
]
CRYPTOS = ["BTC", "ETH", "BNB", "XRP", "USDT"]
ALL = FIATS + CRYPTOS

# Put your key here to enable live fiat fetch; otherwise code will use Binance-only crypto pairs
EXCHANGERATE_API_KEY = "fc582c53a8ed7a0ff648920b"  # <<<< INSERT KEY OR LEAVE EMPTY FOR BINANCE-ONLY FALLBACK >>>>
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"
TIMEOUT = 5

# ----------------------------
# FETCH RATES
# ----------------------------
def fetch_fiat_rates(base: str) -> Dict[str, float]:
    """Fetch fiat exchange rates from ExchangeRate-API; returns {} on error or missing key."""
    if not EXCHANGERATE_API_KEY:
        # No API key: return empty so graph will rely on Binance pairs and reciprocals.
        return {}
    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/{base}"
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException:
        return {}
    if r.get("result") == "success" or "conversion_rates" in r:
        return r.get("conversion_rates", {})
    return {}

def fetch_crypto_rates() -> Dict[Tuple[str, str], float]:
    """Fetch pairs from Binance; returns mapping (SRC, DST) -> price."""
    try:
        resp = requests.get(BINANCE_API, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException:
        return {}
    rates = {}
    for item in resp:
        symbol = item.get("symbol")
        try:
            price = float(item.get("price", 0))
        except Exception:
            continue
        # match symbol exactly to concatenation of our tickers
        for c1, c2 in itertools.permutations(ALL, 2):
            if symbol == f"{c1}{c2}":
                rates[(c1, c2)] = price
    return rates

# ----------------------------
# BUILD GRAPH
# ----------------------------
def build_graph() -> nx.DiGraph:
    """
    Build directed graph G where G[u][v]['rate'] is the raw rate and
    G[u][v]['effective'] is rate*(1-FEE).
    """
    G = nx.DiGraph()
    fiat_rates = {}

    # fetch fiat rates for each fiat base if API key present
    for base in FIATS:
        rates = fetch_fiat_rates(base)
        if rates:
            fiat_rates[base] = rates

    def add_edge(src: str, dst: str, rate: float):
        if rate <= 0:
            return
        effective = rate * (1 - FEE)
        G.add_edge(src, dst, rate=rate, effective=effective)

    # If fiat_rates not empty, add fiat->fiat edges
    for src in FIATS:
        if src not in fiat_rates:
            continue
        for dst in FIATS:
            if src == dst: continue
            if dst in fiat_rates[src]:
                add_edge(src, dst, fiat_rates[src][dst])

    # Add crypto pairs from Binance
    crypto_pairs = fetch_crypto_rates()
    for (src, dst), rate in crypto_pairs.items():
        add_edge(src, dst, rate)

    # Add reciprocals for completeness (if A->B exists, add B->A if missing)
    for u, v, d in list(G.edges(data=True)):
        if not G.has_edge(v, u) and d.get("rate", 0) > 0:
            add_edge(v, u, 1.0 / d["rate"])

    return G

# ----------------------------
# UTIL: convert multiplicative goal into additive costs: cost = -log(effective)
# ----------------------------
def get_neglog_weights(G: nx.DiGraph) -> Dict[Tuple[str, str], float]:
    weights = {}
    for u, v, d in G.edges(data=True):
        eff = d.get("effective", None)
        if eff is None or eff <= 0:
            continue
        weights[(u, v)] = -math.log(eff)
    return weights

# ----------------------------
# DFS (existing exhaustive multi-hop search) - returns top-N by multiplier
# ----------------------------
def find_paths_dfs(G: nx.DiGraph, source: str, target: str, max_hops: int, top_n: int = TOP_RESULTS):
    results = []
    checks = 0

    def dfs(path: List[str], mult: float, hops: int, breakdown: List[Dict[str, Any]]):
        nonlocal checks
        last = path[-1]
        if hops >= max_hops:
            return
        for nxt in G.neighbors(last):
            if nxt in path:
                continue
            checks += 1
            edge = G[last][nxt]
            new_mult = mult * edge["effective"]
            new_break = breakdown + [{"from": last, "to": nxt, "rate": edge["rate"], "effective": edge["effective"]}]
            new_path = path + [nxt]
            if nxt == target and new_mult >= MIN_GAIN:
                results.append((new_path, new_mult, new_break))
            dfs(new_path, new_mult, hops + 1, new_break)

    dfs([source], 1.0, 0, [])
    print(f"🔍 DFS total edges checked: {checks}")
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]

# ----------------------------
# Bellman-Ford limited to K hops (dynamic programming)
# returns best path up to max_hops (1..K) as single best result (or None)
# Works in -log space: minimize sum(cost) => maximize product(effective)
# ----------------------------
def bellman_ford_k_hops(G: nx.DiGraph, source: str, target: str, max_hops: int):
    weights = get_neglog_weights(G)
    nodes = list(G.nodes)
    INF = float("inf")
    # dp[k][v] = best cost to reach v using exactly k edges
    dp = [ {n: INF for n in nodes} for _ in range(max_hops+1) ]
    prev = [ {n: None for n in nodes} for _ in range(max_hops+1) ]
    dp[0][source] = 0.0

    for k in range(1, max_hops+1):
        for (u, v), w in weights.items():
            if dp[k-1][u] + w < dp[k][v]:
                dp[k][v] = dp[k-1][u] + w
                prev[k][v] = u

    # find best k<=max_hops for target
    best_k = None
    best_cost = INF
    for k in range(1, max_hops+1):
        if dp[k][target] < best_cost:
            best_cost = dp[k][target]
            best_k = k

    if best_k is None or best_cost == INF:
        return None  # no path found within K hops

    # reconstruct path backwards using prev
    path = []
    cur = target
    k = best_k
    while k > 0:
        path.append(cur)
        cur = prev[k][cur]
        k -= 1
        if cur is None:
            # reconstruction failed
            return None
    path.append(source)
    path.reverse()

    multiplier = math.exp(-best_cost)  # because cost = -log(mult)
    # prepare breakdown
    breakdown = []
    for i in range(len(path)-1):
        u, v = path[i], path[i+1]
        edge = G[u][v]
        breakdown.append({"from": u, "to": v, "rate": edge["rate"], "effective": edge["effective"]})
    return (path, multiplier, breakdown)

# ----------------------------
# A* search (on -log(effective) costs). Heuristic currently zero (admissible).
# We track hops and disallow states with hops > max_hops.
# Returns best path (first found goal pop is optimal when heuristic is admissible).
# ----------------------------
def astar_k_hops(G: nx.DiGraph, source: str, target: str, max_hops: int):
    weights = get_neglog_weights(G)
    # heuristic = 0 (admissible). Could be improved if you precompute optimistic estimates.
    def h(n):
        return 0.0

    # priority queue on f = g + h, store (f, g, node, hops, path)
    pq = []
    heapq.heappush(pq, (h(source), 0.0, source, 0, [source]))
    visited = {}  # (node, hops) -> best g seen

    while pq:
        f, g, node, hops, path = heapq.heappop(pq)
        # if popped state worse than best known, skip
        key = (node, hops)
        if key in visited and g > visited[key]:
            continue
        if node == target and hops <= max_hops and len(path) - 1 >= 1:
            # found a path; g is the cost = sum(-log(eff)) -> multiplier = exp(-g)
            multiplier = math.exp(-g)
            # build breakdown
            breakdown = []
            for i in range(len(path)-1):
                u, v = path[i], path[i+1]
                edge = G[u][v]
                breakdown.append({"from": u, "to": v, "rate": edge["rate"], "effective": edge["effective"]})
            return (path, multiplier, breakdown)
        if hops >= max_hops:
            continue
        for nbr in G.neighbors(node):
            if nbr in path:
                continue
            w = weights.get((node, nbr))
            if w is None:
                continue
            new_g = g + w
            new_h = h(nbr)
            new_f = new_g + new_h
            new_hops = hops + 1
            key2 = (nbr, new_hops)
            if key2 in visited and new_g >= visited[key2]:
                continue
            visited[key2] = new_g
            heapq.heappush(pq, (new_f, new_g, nbr, new_hops, path + [nbr]))
    return None

# ----------------------------
# DISPLAY helper
# ----------------------------
def display_results(method_name: str, results, source: str, target: str, start_amount: float):
    print(f"\n=== Results ({method_name}) ===")
    if results is None:
        print("No path found.")
        return
    # results may be list (DFS) or single tuple (BF/A*)
    if isinstance(results, list):
        if len(results) == 0:
            print("No paths found.")
            return
        best_amt = 0
        best_idx = 0
        for idx, (path, mult, breakdown) in enumerate(results, 1):
            final_amt = start_amount * mult
            print("--------------------------------------------------")
            print(f"{idx}. Path: {' -> '.join(path)}")
            print(f"   Starting: {start_amount:.6f} {source}")
            print(f"   Final:    {final_amt:.6f} {target}")
            print(f"   Gain x:   {mult:.6f}x (trades: {len(path)-1})")
            print("   Breakdown:")
            for s in breakdown:
                print(f"     {s['from']} -> {s['to']} | rate={s['rate']:.8f} | effective={s['effective']:.8f}")
            print()
            if final_amt > best_amt:
                best_amt = final_amt
                best_idx = idx
        print(f"🏆 Best path: #{best_idx} final amount = {best_amt:.6f} {target}")
    else:
        path, mult, breakdown = results
        final_amt = start_amount * mult
        print("--------------------------------------------------")
        print(f"Path: {' -> '.join(path)}")
        print(f"   Starting: {start_amount:.6f} {source}")
        print(f"   Final:    {final_amt:.6f} {target}")
        print(f"   Gain x:   {mult:.6f}x (trades: {len(path)-1})")
        print("   Breakdown:")
        for s in breakdown:
            print(f"     {s['from']} -> {s['to']} | rate={s['rate']:.8f} | effective={s['effective']:.8f}")
        print()
        print(f"🏆 Best path (single) final amount = {final_amt:.6f} {target}")

# ----------------------------
# USER INPUT
# ----------------------------
def get_user_input():
    valid = set(ALL)
    sorted_all = sorted(ALL)
    while True:
        src = input(f"Enter source currency/crypto ({', '.join(sorted_all)}): ").strip().upper()
        if src in valid: break
        print("Invalid source.")
    while True:
        tgt = input(f"Enter target currency/crypto ({', '.join(sorted_all)}): ").strip().upper()
        if tgt in valid and tgt != src: break
        print("Invalid or same as source.")
    while True:
        try:
            amt = float(input("Enter starting amount: ").strip())
            if amt > 0: break
            print("Amount must be positive.")
        except ValueError:
            print("Enter a number.")
    return src, tgt, amt

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("\n--- Multi-Hop Conversion Finder (DFS / Bellman-Ford-K / A*) ---\n")
    source, target, start_amount = get_user_input()
    print(f"\nConfig: {source} {start_amount} -> {target} (Max {MAX_HOPS} trades)\n")

    print("🔄 Building graph (this may call Binance / ExchangeRate APIs)...")
    start = time.time()
    G = build_graph()
    end = time.time()
    print(f"✅ Graph built: nodes={len(G.nodes)} edges={len(G.edges)} (took {end-start:.2f}s)\n")

    if source not in G:
        print(f"❌ Source {source} not present in graph. Aborting.")
        return
    if target not in G:
        print(f"❌ Target {target} not present in graph. Aborting.")
        return

    # menu choose algorithm
    print("Choose search method:")
    print("  1) DFS (exhaustive, returns top paths)")
    print("  2) Bellman-Ford (best path with <= K hops)")
    print("  3) A* (priority-driven; heuristic=0 currently)")
    choice = input("Select [1/2/3] (default 2): ").strip() or "2"

    if choice == "1":
        t0 = time.time()
        results = find_paths_dfs(G, source, target, MAX_HOPS, top_n=TOP_RESULTS)
        t1 = time.time()
        print(f"\n(DFS took {t1-t0:.2f}s)")
        display_results("DFS (top results)", results, source, target, start_amount)

    elif choice == "2":
        t0 = time.time()
        bf_res = bellman_ford_k_hops(G, source, target, MAX_HOPS)
        t1 = time.time()
        print(f"\n(Bellman-Ford K-hops took {t1-t0:.2f}s)")
        display_results("Bellman-Ford (≤K hops)", bf_res, source, target, start_amount)

    else:
        t0 = time.time()
        a_res = astar_k_hops(G, source, target, MAX_HOPS)
        t1 = time.time()
        print(f"\n(A* took {t1-t0:.2f}s)")
        display_results("A* (K-hops limited)", a_res, source, target, start_amount)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTerminated by user.")
        sys.exit(0)
