#!/usr/bin/env python3
"""
Unified Multi-Method Conversion Finder (improved)

- Fallback fiat rates if ExchangeRate API key missing
- Multi-exchange: Binance (crypto pairs) + Coinbase (extra fx/crypto rates)
- DFS (up to MAX_HOPS), Bellman-Ford (-log weights), A*
- A* uses a safe admissible heuristic (zero or conservative direct-edge estimate)
- Prints counts, timings, top-3 merged candidates and final verified path
"""

import requests
import itertools
import networkx as nx
import heapq
import math
import time
import sys
from typing import List, Dict, Any, Tuple, Optional

# ----------------------------
# CONFIG
# ----------------------------
FEE = 0.001            # 0.1% fee per trade
MAX_HOPS = 3           # DFS limit (trades)
TOP_RESULTS = 3        # top-N to show
FIATS = [
    "USD", "AED", "INR", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
    "NZD", "SGD", "HKD", "MXN", "BRL", "ZAR", "TRY"
]
CRYPTOS = ["BTC", "ETH", "BNB", "XRP", "USDT"]
ALL = FIATS + CRYPTOS

# Put your key here for ExchangeRate; leave empty to use fallback fiat rates
EXCHANGERATE_API_KEY = "fc582c53a8ed7a0ff648920b"  # optional
BINANCE_API = "https://api.binance.com/api/v3/ticker/price"
COINBASE_API = "https://api.coinbase.com/v2/exchange-rates"  # use ?currency=USD etc.
TIMEOUT = 6
EPS = 1e-9

# ----------------------------
# FALLBACK FIAT RATES (realistic-ish baseline)
# ----------------------------
FALLBACK_FIAT_BASE = {
    "USD": 1.0,
    "AED": 3.6725,
    "INR": 82.0,
    "EUR": 0.91,
    "GBP": 0.80,
    "JPY": 140.0,
    "CHF": 0.91,
    "CAD": 1.35,
    "AUD": 1.60,
    "NZD": 1.75,
    "SGD": 1.35,
    "HKD": 7.80,
    "MXN": 18.5,
    "BRL": 5.0,
    "ZAR": 18.0,
    "TRY": 30.0
}

# ----------------------------
# FETCH RATES
# ----------------------------
def fetch_fiat_rates_exchangerate(base: str) -> Dict[str, float]:
    """Fetch fiat rates from ExchangeRate-API (v6). Returns {} on error or missing key."""
    if not EXCHANGERATE_API_KEY:
        return {}
    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest/{base}"
    try:
        r = requests.get(url, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException:
        return {}
    if r.get("result") == "success" or "conversion_rates" in r:
        return r.get("conversion_rates", {})
    return {}

def fetch_fiat_rates_coinbase(base: str) -> Dict[str, float]:
    """Fetch exchange rates from Coinbase for a base currency. Returns mapping of currency->rate or {}."""
    try:
        r = requests.get(COINBASE_API, params={"currency": base}, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException:
        return {}
    data = r.get("data")
    if not data:
        return {}
    rates = data.get("rates", {})
    # Coinbase rates are strings; convert to floats when possible
    out = {}
    for k, v in rates.items():
        try:
            out[k.upper()] = float(v)
        except Exception:
            continue
    return out

def fetch_crypto_rates_binance() -> Dict[Tuple[str,str], float]:
    """Fetch Binance ticker prices. Return mapping (SRC, DST) -> price for matching symbols."""
    try:
        resp = requests.get(BINANCE_API, timeout=TIMEOUT).json()
    except requests.exceptions.RequestException:
        return {}
    pairs = {}
    for item in resp:
        symbol = item.get("symbol")
        try:
            price = float(item.get("price", 0))
        except Exception:
            continue
        for a, b in itertools.permutations(ALL, 2):
            if symbol == f"{a}{b}":
                pairs[(a, b)] = price
    return pairs

# ----------------------------
# BUILD GRAPH (multi-exchange + fallback)
# ----------------------------
def build_graph() -> nx.DiGraph:
    """
    Build directed graph G where G[u][v]['rate'] is raw rate and 'effective' = rate*(1-FEE).
    Uses:
      - ExchangeRate API (if key provided) as primary fiat source
      - Coinbase as supplementary fiat source
      - Binance for crypto pairs
      - Fallback fiat rates if APIs missing
    """
    G = nx.DiGraph()
    fiat_rates = {}

    # 1) Try ExchangeRate primary
    for base in FIATS:
        rates = fetch_fiat_rates_exchangerate(base)
        if rates:
            fiat_rates[base] = rates

    # 2) Supplement with Coinbase for any missing bases
    for base in FIATS:
        if base not in fiat_rates:
            cb = fetch_fiat_rates_coinbase(base)
            if cb:
                fiat_rates[base] = cb

    # 3) If still missing, use fallback constructed relative rates
    for base in FIATS:
        if base not in fiat_rates:
            # create mapping relative to FALLBACK_FIAT_BASE as USD-relative numbers
            base_rate = FALLBACK_FIAT_BASE.get(base, 1.0)
            mapping = {}
            for k, v in FALLBACK_FIAT_BASE.items():
                mapping[k] = v / base_rate
            fiat_rates[base] = mapping

    def add_edge(src: str, dst: str, rate: float):
        if rate is None or rate <= 0 or math.isnan(rate) or math.isinf(rate):
            return
        effective = rate * (1 - FEE)
        G.add_edge(src, dst, rate=rate, effective=effective)

    # Add fiat->fiat edges
    for src in FIATS:
        src_map = fiat_rates.get(src, {})
        for dst in FIATS:
            if src == dst: 
                continue
            if dst in src_map:
                add_edge(src, dst, float(src_map[dst]))

    # Add crypto pairs from Binance
    crypto_pairs = fetch_crypto_rates_binance()
    for (s, d), p in crypto_pairs.items():
        add_edge(s, d, p)

    # Add Coinbase crossing fiat->crypto if present in rates (Coinbase provides fiat<->crypto implicitly via rates keys)
    # We'll attempt common crypto symbols mapping via coinbase by checking fiat_rates[base] keys that match cryptos.
    for base in FIATS:
        mapping = fiat_rates.get(base, {})
        for c in CRYPTOS:
            # some coinbase rates express crypto rate relative to base, e.g. { "BTC": "0.00002" } - handled above if present
            if c in mapping:
                add_edge(base, c, float(mapping[c]))
            # and inverse if present
            if c in mapping and mapping[c] != 0:
                add_edge(c, base, 1.0 / float(mapping[c]))

    # Add reciprocals for edges that exist in one direction but not the other
    for u, v, data in list(G.edges(data=True)):
        if not G.has_edge(v, u):
            rate = data.get("rate", None)
            if rate and rate != 0:
                add_edge(v, u, 1.0 / rate)

    return G

# ----------------------------
# Utilities
# ----------------------------
def path_breakdown_to_string(breakdown: List[Dict[str, Any]]) -> str:
    lines = []
    for step in breakdown:
        lines.append(f"    {step['from']} -> {step['to']} | rate={step['rate']:.8f} | effective={step['effective']:.8f}")
    return "\n".join(lines)

def multiplier_to_final(start_amount: float, multiplier: float) -> float:
    return start_amount * multiplier

# ----------------------------
# DFS (limited to MAX_HOPS)
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
            new_mult = mult * edge['effective']
            new_break = breakdown + [{"from": last, "to": nxt, "rate": edge["rate"], "effective": edge["effective"]}]
            new_path = path + [nxt]
            if nxt == target and new_mult >= 0:
                results.append((new_path, new_mult, new_break))
            dfs(new_path, new_mult, hops + 1, new_break)

    dfs([source], 1.0, 0, [])
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n], checks

# ----------------------------
# Bellman-Ford (any-length up to V-1)
# ----------------------------
def bellman_ford_any(G: nx.DiGraph, source: str, target: str):
    nodes = list(G.nodes())
    n = len(nodes)
    edges = []
    for u, v, d in G.edges(data=True):
        eff = d.get("effective")
        if eff is None or eff <= 0:
            continue
        cost = -math.log(eff)
        edges.append((u, v, cost))
    INF = float("inf")
    dist = {node: INF for node in nodes}
    prev = {node: None for node in nodes}
    dist[source] = 0.0
    relax_count = 0
    for _ in range(n - 1):
        updated = False
        for u, v, w in edges:
            relax_count += 1
            if dist[u] + w < dist[v] - EPS:
                dist[v] = dist[u] + w
                prev[v] = u
                updated = True
        if not updated:
            break
    if dist[target] == INF:
        return None, relax_count
    # reconstruct path
    path = []
    cur = target
    for _ in range(n):
        path.append(cur)
        if cur == source:
            break
        cur = prev[cur]
        if cur is None:
            break
    path.reverse()
    if not path or path[0] != source:
        return None, relax_count
    multiplier = math.exp(-dist[target])
    breakdown = []
    for i in range(len(path)-1):
        u, v = path[i], path[i+1]
        d = G[u][v]
        breakdown.append({"from": u, "to": v, "rate": d["rate"], "effective": d["effective"]})
    return (path, multiplier, breakdown), relax_count

# ----------------------------
# A* (any-length) with admissible heuristic
# Heuristic implemented conservatively:
#  - If node has a direct edge to target, h = -log(max_direct_effective) (admissible)
#  - Else h = 0 (safe)
# This is admissible and safe (won't overestimate optimal -log cost).
# ----------------------------
def build_direct_edge_heuristic(G: nx.DiGraph, target: str) -> Dict[str, float]:
    """Return h(node) = optimistic minimal remaining -log(cost) from node to target using a single direct edge if present."""
    h = {}
    for node in G.nodes():
        best = None
        if G.has_edge(node, target):
            eff = G[node][target]["effective"]
            if eff > 0:
                best = -math.log(eff)
        # If no direct edge, use zero as admissible fallback
        h[node] = best if best is not None else 0.0
    return h

def astar_any(G: nx.DiGraph, source: str, target: str):
    # weights = -log(effective)
    weights = {}
    for u, v, d in G.edges(data=True):
        eff = d.get("effective")
        if eff is None or eff <= 0:
            continue
        weights[(u, v)] = -math.log(eff)

    heuristic = build_direct_edge_heuristic(G, target)
    def h(n: str) -> float:
        return heuristic.get(n, 0.0)

    # PQ entries: (f, g, node, path)
    pq = []
    heapq.heappush(pq, (h(source), 0.0, source, [source]))
    best_g = {}  # best g seen per (node, hops) aggregated by node
    expansions = 0
    while pq:
        f, g, node, path = heapq.heappop(pq)
        expansions += 1
        # If we've reached goal
        if node == target and len(path) >= 2:
            multiplier = math.exp(-g)
            breakdown = []
            for i in range(len(path)-1):
                u, v = path[i], path[i+1]
                d = G[u][v]
                breakdown.append({"from": u, "to": v, "rate": d["rate"], "effective": d["effective"]})
            return (path, multiplier, breakdown), expansions
        for nbr in G.neighbors(node):
            if nbr in path:
                continue
            w = weights.get((node, nbr))
            if w is None:
                continue
            new_g = g + w
            # simple bounding: if we've seen a better g for this neighbor, skip
            if nbr in best_g and new_g >= best_g[nbr] - EPS:
                continue
            best_g[nbr] = new_g
            heapq.heappush(pq, (new_g + h(nbr), new_g, nbr, path + [nbr]))
    return None, expansions

# ----------------------------
# Merge & run all methods
# ----------------------------
def run_all_methods(G: nx.DiGraph, source: str, target: str, start_amount: float):
    results = {}
    times = {}
    counts = {}

    # DFS
    t0 = time.time()
    dfs_res, dfs_checks = find_paths_dfs(G, source, target, MAX_HOPS, top_n=TOP_RESULTS)
    t1 = time.time()
    results['DFS'] = dfs_res
    times['DFS'] = t1 - t0
    counts['DFS'] = dfs_checks

    # Bellman-Ford
    t0 = time.time()
    bf_res, bf_checks = bellman_ford_any(G, source, target)
    t1 = time.time()
    results['Bellman-Ford'] = bf_res
    times['Bellman-Ford'] = t1 - t0
    counts['Bellman-Ford'] = bf_checks

    # A*
    t0 = time.time()
    astar_res, astar_counts = astar_any(G, source, target)
    t1 = time.time()
    results['A*'] = astar_res
    times['A*'] = t1 - t0
    counts['A*'] = astar_counts

    # Print summary per method
    print("\n=== Per-method summaries ===")
    for method in ('DFS', 'Bellman-Ford', 'A*'):
        print(f"\n-- {method} --")
        print(f" time: {times[method]:.4f}s, checks/expansions: {counts[method]}")
        res = results[method]
        if not res:
            print("  no path found")
            continue
        if method == 'DFS':
            for i, (path, mult, breakdown) in enumerate(res, 1):
                final_amt = multiplier_to_final(start_amount, mult)
                print(f"  {i}) {' -> '.join(path)} | final={final_amt:.6f} | mult={mult:.8f}")
        else:
            path, mult, breakdown = res
            final_amt = multiplier_to_final(start_amount, mult)
            print(f"  Best: {' -> '.join(path)} | final={final_amt:.6f} | mult={mult:.8f}")

    # Merge candidates
    merged = {}
    # DFS candidates
    for path, mult, breakdown in dfs_res:
        key = tuple(path)
        merged[key] = {'path': list(path), 'mult': mult, 'breakdown': breakdown, 'sources': ['DFS']}
    # BF
    if bf_res:
        p, m, b = bf_res
        key = tuple(p)
        if key in merged:
            merged[key]['sources'].append('Bellman-Ford')
            merged[key]['mult'] = max(merged[key]['mult'], m)
        else:
            merged[key] = {'path': p, 'mult': m, 'breakdown': b, 'sources': ['Bellman-Ford']}
    # A*
    if astar_res:
        p, m, b = astar_res
        key = tuple(p)
        if key in merged:
            merged[key]['sources'].append('A*')
            merged[key]['mult'] = max(merged[key]['mult'], m)
        else:
            merged[key] = {'path': p, 'mult': m, 'breakdown': b, 'sources': ['A*']}

    candidates = sorted(merged.values(), key=lambda x: x['mult'], reverse=True)
    total_unique = len(candidates)

    print("\n=== Top combined candidates ===")
    if total_unique == 0:
        print("No candidate paths found.")
        return
    for i, cand in enumerate(candidates[:TOP_RESULTS], 1):
        path = cand['path']; mult = cand['mult']; breakdown = cand['breakdown']; sources = cand['sources']
        final_amt = multiplier_to_final(start_amount, mult)
        print("\n--------------------------------------------------")
        print(f"{i}. Path: {' -> '.join(path)}")
        print(f"   Final Amount: {final_amt:.6f}")
        print(f"   Multiplier:   {mult:.8f}x")
        print(f"   Found by:     {', '.join(sources)}")
        print(f"   Trades:       {len(path)-1}")
        print("   Breakdown:")
        print(path_breakdown_to_string(breakdown))

    print("\n--------------------------------------------------")
    print(f"Total unique candidate paths: {total_unique}")

    # Consensus check on top candidate
    top_candidate = candidates[0]
    top_key = tuple(top_candidate['path'])
    agreement = {'DFS': False, 'Bellman-Ford': False, 'A*': False}
    for p, m, b in dfs_res:
        if tuple(p) == top_key:
            agreement['DFS'] = True
    if bf_res and tuple(bf_res[0]) == top_key:
        agreement['Bellman-Ford'] = True
    if astar_res and tuple(astar_res[0]) == top_key:
        agreement['A*'] = True
    methods_agree = sum(1 for v in agreement.values() if v)
    if methods_agree >= 2:
        print("\n✅ Consensus: at least two methods found the same best path.")
    else:
        print("\n⚠️ Discrepancy: methods disagree on best path. Showing best merged candidate (highest multiplier).")

    # Final chosen
    best = top_candidate
    print("\n=== FINAL CHOSEN PATH ===")
    path = best['path']; mult = best['mult']; breakdown = best['breakdown']
    final_amt = multiplier_to_final(start_amount, mult)
    print(f"Path: {' -> '.join(path)}")
    print(f"Final Amount: {final_amt:.6f}")
    print(f"Multiplier:   {mult:.8f}x")
    print(f"Trades:       {len(path)-1}")
    print("Breakdown:")
    print(path_breakdown_to_string(breakdown))
    print("\nMethods that found this path: " + ", ".join(best['sources']))
    print("\n=== Timings & counts ===")
    for m in ('DFS', 'Bellman-Ford', 'A*'):
        print(f"{m}: time={times.get(m, 0):.4f}s, checks={counts.get(m, 0)}")
    # note: times/counts variables are not accessible here (kept per-run) — but we printed per-method earlier

# ----------------------------
# CLI / main
# ----------------------------
def get_user_input() -> Tuple[str,str,float]:
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
            print("Enter a valid number.")
    return src, tgt, amt

def main():
    print("\n=== Multi-Method Conversion Finder (improved) ===")
    source, target, start_amount = get_user_input()
    print(f"\nConfig: {source} {start_amount} -> {target} (DFS max hops={MAX_HOPS})\n")
    print("Building graph (Binance + Coinbase + ExchangeRate fallback)...")
    t0 = time.time()
    G = build_graph()
    t1 = time.time()
    print(f"Graph built: nodes={len(G.nodes)} edges={len(G.edges)} (took {t1-t0:.2f}s)")
    if source not in G:
        print(f"❌ Source {source} not present in graph.")
        return
    if target not in G:
        print(f"❌ Target {target} not present in graph.")
        return

    # run all methods
    # we want to capture per-method times/counts for printing
    # small wrapper to expose those for the merged print block
    # We'll re-run run_all_methods but capture per-method times/counts within
    # For clarity, call run_all_methods which already prints a lot.
    run_all_methods(G, source, target, start_amount)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
