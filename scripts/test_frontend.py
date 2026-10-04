#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
html = (root / "index.html").read_text(encoding="utf-8")
js = (root / "app.js").read_text(encoding="utf-8")

def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)

# 1) JavaScript and data builders must parse before any network-heavy build starts.
subprocess.run(["node", "--check", str(root / "app.js")], check=True)
subprocess.run([
    sys.executable, "-m", "py_compile",
    str(root / "scripts" / "update_tcgplayer.py"),
    str(root / "scripts" / "update_pokemon_competitive.py"),
], check=True)

# 2) DOM ids must be unique and every $("id") reference must exist.
ids = re.findall(r'id="([^"]+)"', html)
if len(ids) != len(set(ids)):
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    fail(f"duplicate ids: {dupes}")
refs = re.findall(r'\$\("([^"]+)"\)', js)
missing = sorted(set(refs) - set(ids))
if missing:
    fail(f"missing DOM ids: {missing}")

# 3) Cache busting is mandatory on GitHub Pages.
if "app.js?v=3.0.0" not in html:
    fail("app.js is not versioned to 3.0.0")
if "style.css?v=3.0.0" not in html:
    fail("style.css is not versioned to 3.0.0")
if "no-cache, no-store" not in html:
    fail("no-cache meta is missing")

# 4) Trend regression guards.
required = [
    "loadTrendForCurrent()",
    "setTimeout(()=>ctrl.abort(),7000)",
    'label.textContent="Sin historial suficiente"',
    "renderTrend(state.trend)",
    "localTrendData(local)",
]
for marker in required:
    if marker not in js:
        fail(f"trend regression marker missing: {marker}")
if "Analizando…" in re.search(r'id="trendLabel"[^>]*>(.*?)</div>', html, re.S).group(1):
    fail("trend HTML must not boot in an endless analyzing state")

# 5) Weekly meta regression guards.
for marker in ["metaSection", "metaDecksList", "metaCardsList", "metaDecklists", "metaEvents"]:
    if f'id="{marker}"' not in html:
        fail(f"weekly meta DOM marker missing: {marker}")
for marker in ["loadWeeklyMeta", "weekly.json", "renderWeeklyMeta", "data-meta-q", "copiesPer100Decks"]:
    if marker not in js:
        fail(f"weekly meta JS marker missing: {marker}")

# 6) Visual selling workflow guards.
for marker in ["deckModal", "deckRetail", "deckResolved", "deckPriority", "deckPokemon", "deckTrainer", "deckEnergy"]:
    if f'id="{marker}"' not in html:
        fail(f"visual deck DOM marker missing: {marker}")
for marker in ["showMetaDeck", "hydrateDeck", "resolveMetaCard", "stockPriority", "copyCurrentDeck", "playableMarket"]:
    if marker not in js:
        fail(f"visual selling JS marker missing: {marker}")

# 7) Scanner regression guards.
for marker in ["Lectura del nombre", "Lectura del código", "Búsqueda de candidatos", 'btn.textContent="Identificar carta"']:
    if marker not in js:
        fail(f"scanner regression marker missing: {marker}")

print(f"PASS frontend regression checks: {len(ids)} ids, {len(set(refs))} DOM refs, JS syntax OK")
