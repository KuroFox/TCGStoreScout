#!/usr/bin/env python3
import argparse
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://tcgcsv.com/tcgplayer"
GAMES = {
    1: "Magic: The Gathering",
    2: "Yu-Gi-Oh!",
    3: "Pokémon",
    63: "Digimon Card Game",
    68: "One Piece Card Game",
    71: "Disney Lorcana",
}
UA = "TCGStoreScout/2.1 (+https://github.com/KuroFox/TCGStoreScout)"

def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def key2(value):
    compact = re.sub(r"[^a-z0-9]", "", norm(value))
    return (compact[:2] if len(compact) >= 2 else (compact + "_")[:2]) or "__"

def extended(product, *names):
    wanted = {norm(x) for x in names}
    data = product.get("extendedData") or []
    if isinstance(data, dict):
        for k, v in data.items():
            if norm(k) in wanted:
                return v
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            label = item.get("name") or item.get("displayName") or item.get("key")
            if norm(label) in wanted:
                return item.get("value")
    return ""

def session():
    s = requests.Session()
    retry = Retry(
        total=4, connect=4, read=4, backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s

def get_json(s, url, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            r = s.get(url, timeout=(10, 60))
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError("; ".join(data.get("errors") or ["success=false"]))
            return data
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(10, 1.7 ** (attempt + 1)))
    raise RuntimeError(f"GET failed: {url}: {last}")

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="_site/data")
    ap.add_argument("--delay", type=float, default=0.11)
    ap.add_argument("--games", default=",".join(map(str, GAMES)))
    args = ap.parse_args()
    wanted = [int(x) for x in args.games.split(",") if x.strip()]
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    s = session()

    categories = get_json(s, f"{BASE}/categories").get("results", [])
    category_map = {int(x["categoryId"]): x for x in categories if x.get("categoryId") is not None}
    status = {
        "provider": "TCGplayer",
        "mirror": "TCGCSV",
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "schema": 2,
        "games": {},
    }

    total_priced = 0
    for category_id in wanted:
        game_name = GAMES.get(category_id, str(category_id))
        print(f"\n== {game_name} ({category_id}) ==", flush=True)
        groups = get_json(s, f"{BASE}/{category_id}/groups").get("results", [])
        name_shards = defaultdict(dict)
        code_shards = defaultdict(dict)
        product_count = priced_count = price_rows = 0
        failures = []

        for pos, group in enumerate(groups, 1):
            gid = int(group["groupId"])
            try:
                products = get_json(s, f"{BASE}/{category_id}/{gid}/products").get("results", [])
                time.sleep(args.delay)
                prices = get_json(s, f"{BASE}/{category_id}/{gid}/prices").get("results", [])
                time.sleep(args.delay)
            except Exception as exc:
                failures.append({"groupId": gid, "error": str(exc)[:260]})
                print(f"WARN group {gid}: {exc}", flush=True)
                continue

            price_map = defaultdict(list)
            for p in prices:
                pid = int(p.get("productId") or 0)
                if not pid:
                    continue
                price_map[pid].append([
                    p.get("subTypeName") or "Normal",
                    p.get("marketPrice"),
                    p.get("lowPrice"),
                    p.get("midPrice"),
                    p.get("highPrice"),
                    p.get("directLowPrice"),
                ])
                price_rows += 1

            set_name = group.get("name") or f"Group {gid}"
            set_abbr = group.get("abbreviation") or ""
            for p in products:
                pid = int(p.get("productId") or 0)
                if not pid:
                    continue
                name = p.get("name") or p.get("cleanName") or f"Product {pid}"
                code = extended(p, "Number", "Card Number", "Set Number", "Collector Number") or ""
                rarity = extended(p, "Rarity") or ""
                rec = {
                    "i": pid,
                    "g": gid,
                    "n": name,
                    "s": set_name,
                    "a": set_abbr,
                    "c": str(code),
                    "r": str(rarity),
                    "m": p.get("imageUrl") or "",
                    "u": p.get("url") or f"https://www.tcgplayer.com/product/{pid}",
                    "p": price_map.get(pid, []),
                }
                product_count += 1
                if rec["p"]:
                    priced_count += 1

                tokens = [t for t in norm(name).split() if t]
                keys = {"__"} if not tokens else {key2(tokens[0]), key2(tokens[-1])}
                for k in keys:
                    name_shards[k][pid] = rec
                if rec["c"]:
                    code_shards[key2(rec["c"])][pid] = rec

            if pos % 25 == 0 or pos == len(groups):
                print(f"  {pos}/{len(groups)} groups · {product_count} products · {priced_count} priced", flush=True)

        game_dir = out / "tcgplayer" / str(category_id)
        for k, records in name_shards.items():
            write_json(game_dir / "name" / f"{k}.json", list(records.values()))
        for k, records in code_shards.items():
            write_json(game_dir / "code" / f"{k}.json", list(records.values()))
        write_json(game_dir / "groups.json", [
            {"g": int(g["groupId"]), "n": g.get("name") or "", "a": g.get("abbreviation") or ""}
            for g in groups if g.get("groupId") is not None
        ])
        if failures:
            write_json(game_dir / "failures.json", failures)

        status["games"][str(category_id)] = {
            "name": game_name,
            "displayName": category_map.get(category_id, {}).get("displayName", game_name),
            "groups": len(groups),
            "products": product_count,
            "pricedProducts": priced_count,
            "priceRows": price_rows,
            "failedGroups": len(failures),
        }
        total_priced += priced_count

        if groups and priced_count == 0:
            raise RuntimeError(f"{game_name}: groups exist but zero priced products were built")

    if total_priced == 0:
        raise RuntimeError("Build produced zero priced products across all configured games")

    write_json(out / "status.json", status)
    print("\nBuild complete:", out, flush=True)

if __name__ == "__main__":
    main()
