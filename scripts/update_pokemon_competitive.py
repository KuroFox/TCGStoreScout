#!/usr/bin/env python3
import argparse
import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://play.limitlesstcg.com/api"
UA = "TCGStoreScout/2.2 (+https://github.com/KuroFox/TCGStoreScout)"

def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def key2(value):
    compact = re.sub(r"[^a-z0-9]", "", norm(value))
    return (compact[:2] if len(compact) >= 2 else (compact + "_")[:2]) or "__"

def session():
    s = requests.Session()
    retry = Retry(total=4, connect=4, read=4, backoff_factor=1.0,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]))
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s

def fetch_json(s, url):
    r = s.get(url, timeout=(10, 60))
    if r.status_code == 429:
        wait = int(r.headers.get("retry-after", "30") or 30)
        time.sleep(min(90, max(10, wait)))
        r = s.get(url, timeout=(10, 60))
    r.raise_for_status()
    return r.json()

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

def pct_rank(values, value):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    below = sum(1 for v in vals if v <= value)
    return 100.0 * below / len(vals)

def confidence(total_decks, card_decks, events):
    if total_decks >= 500 and card_decks >= 20 and events >= 5:
        return "Alta"
    if total_decks >= 150 and card_decks >= 6 and events >= 3:
        return "Media"
    return "Baja"

def demand_label(score):
    if score >= 80: return "Muy alta"
    if score >= 65: return "Alta"
    if score >= 45: return "Media"
    if score >= 25: return "Baja"
    return "Muy baja"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="_site/data/competitive/pokemon")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--events", type=int, default=22)
    ap.add_argument("--min-players", type=int, default=32)
    ap.add_argument("--pace", type=float, default=6.3)
    args = ap.parse_args()

    out = Path(args.output)
    s = session()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    recent7 = now - timedelta(days=7)
    prior30 = now - timedelta(days=30)
    previous7 = now - timedelta(days=14)

    tournaments = fetch_json(s, f"{BASE}/tournaments?game=PTCG&format=STANDARD&limit=50&page=1")
    candidates = []
    for t in tournaments:
        try:
            dt = datetime.fromisoformat(str(t.get("date", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff:
            continue
        if int(t.get("players") or 0) < args.min_players:
            continue
        candidates.append((dt, t))
    candidates.sort(key=lambda x: x[0], reverse=True)
    candidates = candidates[:args.events]

    by_name = {}
    total = {
        "all": 0, "top32": 0, "top8": 0,
        "recent7": 0, "recent7Top32": 0, "recent7Top8": 0,
        "prev7": 0, "prior30": 0
    }
    event_summaries = []
    week_events = set()
    week_arch = defaultdict(lambda: {"decks": 0, "wins": 0, "losses": 0, "ties": 0, "top32": 0, "top8": 0, "best": 999999, "events": set()})
    prev_arch = Counter()
    week_exact = defaultdict(lambda: {"name": "", "set": "", "number": "", "category": "", "decks": 0, "copies": 0, "top32": 0, "top8": 0, "events": set(), "archetypes": Counter()})
    prev_exact = Counter()

    for idx, (dt, t) in enumerate(candidates, 1):
        if idx > 1:
            time.sleep(args.pace)
        tid = t["id"]
        try:
            standings = fetch_json(s, f"{BASE}/tournaments/{tid}/standings")
        except Exception as exc:
            print(f"WARN {tid}: {exc}", flush=True)
            continue

        event_decks = event_top32 = event_top8 = 0
        for row in standings:
            dl = row.get("decklist")
            if not isinstance(dl, dict):
                continue
            cards = []
            for cat in ("pokemon", "trainer", "energy"):
                for c in dl.get(cat) or []:
                    if isinstance(c, dict) and c.get("name"):
                        cards.append((cat, c))

            if not cards:
                continue

            event_decks += 1
            total["all"] += 1
            placing = int(row.get("placing") or 999999)
            if placing <= 32:
                total["top32"] += 1
                event_top32 += 1
            if placing <= 8:
                total["top8"] += 1
                event_top8 += 1
            if dt >= recent7:
                total["recent7"] += 1
                week_events.add(tid)
                if placing <= 32: total["recent7Top32"] += 1
                if placing <= 8: total["recent7Top8"] += 1
            if previous7 <= dt < recent7:
                total["prev7"] += 1
            if prior30 <= dt < recent7:
                total["prior30"] += 1

            archetype = ((row.get("deck") or {}).get("name") or "Sin clasificar").strip()
            if dt >= recent7 and archetype != "Sin clasificar":
                rec = row.get("record") or {}
                wa = week_arch[archetype]
                wa["decks"] += 1
                wa["wins"] += int(rec.get("wins") or 0)
                wa["losses"] += int(rec.get("losses") or 0)
                wa["ties"] += int(rec.get("ties") or 0)
                if placing <= 32: wa["top32"] += 1
                if placing <= 8: wa["top8"] += 1
                wa["best"] = min(wa["best"], placing)
                wa["events"].add(tid)
            elif previous7 <= dt < recent7 and archetype != "Sin clasificar":
                prev_arch[archetype] += 1

            # Two views: by functional name, and by exact set+number printing.
            per_list = {}
            exact_in_list = {}
            for cat, c in cards:
                name = str(c.get("name") or "").strip()
                set_code = str(c.get("set") or "").strip()
                number = str(c.get("number") or "").strip()
                copies = int(c.get("count") or 1)
                k = norm(name)
                if not k:
                    continue
                cur = per_list.get(k)
                if cur is None:
                    per_list[k] = {
                        "name": name, "set": set_code, "number": number,
                        "copies": copies, "category": cat
                    }
                else:
                    cur["copies"] += copies

                ek = (k, set_code, number)
                ecur = exact_in_list.get(ek)
                if ecur is None:
                    exact_in_list[ek] = {
                        "name": name, "set": set_code, "number": number,
                        "copies": copies, "category": cat
                    }
                else:
                    ecur["copies"] += copies

            if dt >= recent7:
                for ek, ec in exact_in_list.items():
                    ex = week_exact[ek]
                    ex["name"] = ec["name"]
                    ex["set"] = ec["set"]
                    ex["number"] = ec["number"]
                    ex["category"] = ec["category"]
                    ex["decks"] += 1
                    ex["copies"] += ec["copies"]
                    if placing <= 32: ex["top32"] += 1
                    if placing <= 8: ex["top8"] += 1
                    ex["events"].add(tid)
                    ex["archetypes"][archetype] += 1
            elif previous7 <= dt < recent7:
                for ek in exact_in_list:
                    prev_exact[ek] += 1

            for nk, c in per_list.items():
                agg = by_name.setdefault(nk, {
                    "name": c["name"], "category": c["category"],
                    "decks": 0, "copies": 0, "top32": 0, "top8": 0,
                    "recent7": 0, "prior30": 0,
                    "events": set(), "archetypes": Counter(), "best": 999999,
                    "variants": Counter(),
                })
                agg["decks"] += 1
                agg["copies"] += c["copies"]
                if placing <= 32: agg["top32"] += 1
                if placing <= 8: agg["top8"] += 1
                if dt >= recent7: agg["recent7"] += 1
                elif dt >= prior30: agg["prior30"] += 1
                agg["events"].add(tid)
                agg["archetypes"][archetype] += 1
                agg["best"] = min(agg["best"], placing)
                agg["variants"][(c["set"], c["number"])] += 1

        event_summaries.append({
            "id": tid, "name": t.get("name"), "date": dt.date().isoformat(),
            "players": int(t.get("players") or 0), "decklists": event_decks,
            "top32Decklists": event_top32, "top8Decklists": event_top8,
        })
        print(f"{idx}/{len(candidates)} {t.get('name')} · {event_decks} decklists", flush=True)

    if total["all"] == 0:
        raise RuntimeError("Limitless sync produced zero public Pokémon decklists")

    rows = []
    for nk, a in by_name.items():
        inclusion = a["decks"] / total["all"] if total["all"] else 0
        top_inclusion = a["top32"] / total["top32"] if total["top32"] else 0
        top8_inclusion = a["top8"] / total["top8"] if total["top8"] else 0
        inc7 = a["recent7"] / total["recent7"] if total["recent7"] else 0
        inc_prev = a["prior30"] / total["prior30"] if total["prior30"] else 0
        trend_pp = (inc7 - inc_prev) * 100
        avg_copies = a["copies"] / a["decks"] if a["decks"] else 0
        rows.append({
            "key": nk, "name": a["name"], "category": a["category"],
            "decks": a["decks"], "copies": a["copies"], "top32": a["top32"], "top8": a["top8"],
            "events": len(a["events"]), "best": a["best"] if a["best"] < 999999 else None,
            "inclusion": inclusion, "topInclusion": top_inclusion, "top8Inclusion": top8_inclusion,
            "inclusion7": inc7, "inclusionPrev": inc_prev, "trendPP": trend_pp,
            "avgCopies": avg_copies,
            "archetypesRaw": a["archetypes"],
            "variantsRaw": a["variants"],
        })

    inclusions = [r["inclusion"] for r in rows]
    topincs = [r["topInclusion"] for r in rows]
    breadths = [len(r["archetypesRaw"]) for r in rows]
    copies_list = [r["avgCopies"] for r in rows]

    shards = defaultdict(list)
    for r in rows:
        presence = pct_rank(inclusions, r["inclusion"])
        topcut = pct_rank(topincs, r["topInclusion"])
        breadth = pct_rank(breadths, len(r["archetypesRaw"]))
        copy_score = pct_rank(copies_list, r["avgCopies"])
        trend_score = max(0, min(100, 50 + r["trendPP"] * 6))
        score = round(0.30*presence + 0.25*topcut + 0.15*breadth + 0.15*copy_score + 0.15*trend_score)

        top_arch = [{"name": n, "decks": c} for n, c in r["archetypesRaw"].most_common(5)]
        variants = [{"set": s, "number": n, "decks": c}
                    for (s, n), c in r["variantsRaw"].most_common(12)]
        rec = {
            "n": r["name"], "k": r["key"], "cat": r["category"],
            "score": score, "label": demand_label(score),
            "confidence": confidence(total["all"], r["decks"], r["events"]),
            "decks": r["decks"], "events": r["events"], "best": r["best"],
            "usage30": round(r["inclusion"]*100, 2),
            "usage7": round(r["inclusion7"]*100, 2),
            "top32": round(r["topInclusion"]*100, 2),
            "top8": round(r["top8Inclusion"]*100, 2),
            "trendPP": round(r["trendPP"], 2),
            "avgCopies": round(r["avgCopies"], 2),
            "archetypes": top_arch, "variants": variants,
        }
        shards[key2(r["name"])].append(rec)

    for k, vals in shards.items():
        vals.sort(key=lambda x: (-x["score"], -x["decks"], x["n"]))
        write_json(out / "name" / f"{k}.json", vals)

    # Seven-day meta radar for the store: decks and exact card printings.
    weekly_decks = []
    for name, a in week_arch.items():
        share = (a["decks"] / total["recent7"] * 100) if total["recent7"] else 0
        prev_share = (prev_arch[name] / total["prev7"] * 100) if total["prev7"] else 0
        matches = a["wins"] + a["losses"] + a["ties"]
        win_rate = (a["wins"] / matches * 100) if matches else 0
        weekly_decks.append({
            "name": name,
            "decks": a["decks"],
            "share": round(share, 2),
            "prevShare": round(prev_share, 2),
            "trendPP": round(share - prev_share, 2) if total["prev7"] else None,
            "winRate": round(win_rate, 1),
            "top32": a["top32"],
            "top8": a["top8"],
            "best": a["best"] if a["best"] < 999999 else None,
            "events": len(a["events"]),
        })
    weekly_decks.sort(key=lambda x: (-x["share"], -x["winRate"], x["name"]))

    weekly_cards = []
    for ek, a in week_exact.items():
        if a["category"] == "energy":
            continue
        usage = (a["decks"] / total["recent7"] * 100) if total["recent7"] else 0
        prev_usage = (prev_exact[ek] / total["prev7"] * 100) if total["prev7"] else 0
        avg_copies = (a["copies"] / a["decks"]) if a["decks"] else 0
        copies_per_100 = (a["copies"] / total["recent7"] * 100) if total["recent7"] else 0
        top32_usage = (a["top32"] / total["recent7Top32"] * 100) if total["recent7Top32"] else 0
        weekly_cards.append({
            "name": a["name"],
            "set": a["set"],
            "number": a["number"],
            "category": a["category"],
            "decks": a["decks"],
            "usage": round(usage, 2),
            "prevUsage": round(prev_usage, 2),
            "trendPP": round(usage - prev_usage, 2) if total["prev7"] else None,
            "avgCopies": round(avg_copies, 2),
            "copiesPer100Decks": round(copies_per_100, 1),
            "top32Usage": round(top32_usage, 2),
            "top8": a["top8"],
            "events": len(a["events"]),
            "archetypes": [{"name": n, "decks": d} for n, d in a["archetypes"].most_common(4)],
        })
    # Copies per 100 meta decks is the best tournament proxy for physical demand.
    weekly_cards.sort(key=lambda x: (-x["copiesPer100Decks"], -x["top32Usage"], -x["trendPP"], x["name"]))

    weekly = {
        "builtAt": now.isoformat(),
        "source": "Limitless Tournament Platform",
        "game": "Pokémon TCG",
        "format": "STANDARD",
        "windowDays": 7,
        "eventsAnalyzed": len(week_events),
        "decklistsAnalyzed": total["recent7"],
        "previousWeekDecklists": total["prev7"],
        "topDecks": weekly_decks[:15],
        "topCards": weekly_cards[:40],
        "note": "Tournament usage is a competitive-demand proxy, not verified retail purchase volume."
    }
    write_json(out / "weekly.json", weekly)

    status = {
        "builtAt": now.isoformat(),
        "source": "Limitless Tournament Platform",
        "game": "Pokémon TCG",
        "format": "STANDARD",
        "windowDays": args.days,
        "eventsAnalyzed": len(event_summaries),
        "decklistsAnalyzed": total["all"],
        "top32Decklists": total["top32"],
        "top8Decklists": total["top8"],
        "recent7Decklists": total["recent7"],
        "prior30Decklists": total["prior30"],
        "minPlayers": args.min_players,
        "tournaments": event_summaries,
    }
    write_json(out / "status.json", status)
    print(f"Competitive build complete: {len(rows)} card names, {total['all']} decklists", flush=True)

if __name__ == "__main__":
    main()
