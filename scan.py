# scan_decoded.py
import re
from pathlib import Path

files = sorted(Path('.').glob('final_decoded_*.txt'))
domain_re = re.compile(r'\b([a-z0-9][-a-z0-9]*\.)+[a-z]{2,}\b', re.I)
nslookup_re = re.compile(r'nslookup\s+(-type=|-type\s+)?([A-Za-z]+)?\s*([\w\.-]+)', re.I)
ping_re = re.compile(r'\bping\s+([\w\.-]+)', re.I)
resolve_re = re.compile(r'Resolve-DnsName\s+-Name\s+["\']?([\w\.-]+)', re.I)

candidates = {}
for f in files:
    txt = f.read_text(encoding='utf-8', errors='ignore')
    doms = sorted({m.group(0).lower() for m in domain_re.finditer(txt)})
    nsls = nslookup_re.findall(txt)
    pings = ping_re.findall(txt)
    resolves = resolve_re.findall(txt)
    candidates[f.name] = {
        'domains': doms,
        'nslookups': nsls,
        'pings': pings,
        'resolves': resolves
    }

for name, info in candidates.items():
    print(f"\n== {name} ==")
    if info['nslookups']:
        print("nslookup-like lines (type,domain):")
        for t, typ, dom in info['nslookups']:
            # nslookup_re groups: full match parts; we want typ and domain
            print(" ", typ or "(none)", dom)
    if info['pings']:
        print("ping targets:")
        for p in sorted(set(info['pings'])):
            print(" ", p)
    if info['resolves']:
        print("Resolve-DnsName targets:")
        for r in sorted(set(info['resolves'])):
            print(" ", r)
    if info['domains']:
        print("domain-like tokens (sample 50):")
        for d in info['domains'][:50]:
            print(" ", d)
