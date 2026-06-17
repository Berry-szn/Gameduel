# -*- coding: utf-8 -*-
"""
Persistent global league for the football-manager game.

Every match a player finishes updates their row in one shared, never-resetting
table (stored in Upstash via storage.kv_*). The table is seeded once with a set
of CPU managers so it feels populated and competitive from the very first game,
and real managers climb through them as they rack up results.

Pure logic here (seed / apply a result / rank). The server owns the storage
read-write and the user identity.
"""

import random

# CPU managers that populate the global table from day one.
_SEED_NAMES = [
    "Thunder FC", "Red Devils 99", "Blue Moon City", "Samba Stars",
    "Catalan Kings", "Bavarian Blitz", "Mersey Reds", "North London",
    "Saints Alive", "Iron Wolves", "Old Lady Turin", "Rossoneri X",
    "Azzurri Napoli", "Parisian Elite", "Galactico Madrid", "Yorkshire Terriers",
    "Steel City", "Harbour United", "Desert Hawks", "River Kings",
    "Green Army", "Citizen Sky", "Toffee Blues", "Wolf Pack",
]

LEAGUE_KEY = "fb_global_league_v1"


def blank_row(name):
    return {"name": name or "Manager", "P": 0, "W": 0, "D": 0, "L": 0,
            "GF": 0, "GA": 0, "Pts": 0}


def seed_standings():
    """A deterministic, plausible populated table of CPU managers."""
    rng = random.Random(20260617)
    out = {}
    for i, nm in enumerate(_SEED_NAMES):
        played = rng.randint(20, 32)
        w = rng.randint(played // 5, max(played // 5, played - played // 3))
        w = min(w, played)
        d = rng.randint(0, played - w)
        l = played - w - d
        gf = w * rng.randint(1, 3) + d + rng.randint(0, 9)
        ga = l * rng.randint(1, 3) + d + rng.randint(0, 7)
        out["seed_%02d" % i] = {
            "name": nm, "P": played, "W": w, "D": d, "L": l,
            "GF": gf, "GA": ga, "Pts": w * 3 + d, "cpu": True,
        }
    return out


def apply_result(standings, uid, name, outcome, gf, ga):
    """Update (or create) a manager's row with one match result."""
    row = standings.get(uid) or blank_row(name)
    if name:
        row["name"] = name
    row["P"] = row.get("P", 0) + 1
    row["GF"] = row.get("GF", 0) + int(gf)
    row["GA"] = row.get("GA", 0) + int(ga)
    if outcome == "win":
        row["W"] = row.get("W", 0) + 1
        row["Pts"] = row.get("Pts", 0) + 3
    elif outcome == "draw":
        row["D"] = row.get("D", 0) + 1
        row["Pts"] = row.get("Pts", 0) + 1
    else:
        row["L"] = row.get("L", 0) + 1
    standings[uid] = row
    return standings


def ranked_table(standings):
    """Sorted standings (points, then goal difference, then goals scored)."""
    rows = []
    for uid, r in standings.items():
        gd = r.get("GF", 0) - r.get("GA", 0)
        rows.append({
            "uid": uid, "name": r.get("name", "Manager"),
            "P": r.get("P", 0), "W": r.get("W", 0), "D": r.get("D", 0),
            "L": r.get("L", 0), "GF": r.get("GF", 0), "GA": r.get("GA", 0),
            "GD": gd, "Pts": r.get("Pts", 0), "cpu": bool(r.get("cpu")),
        })
    rows.sort(key=lambda r: (-r["Pts"], -r["GD"], -r["GF"], r["name"]))
    for i, r in enumerate(rows):
        r["pos"] = i + 1
    return rows


if __name__ == "__main__":
    s = seed_standings()
    print(f"seeded {len(s)} CPU managers")
    # a new player wins a few, draws one, loses one
    uid = "u_test"
    for oc, gf, ga in [("win", 3, 1), ("win", 2, 0), ("draw", 1, 1), ("loss", 0, 2), ("win", 4, 2)]:
        apply_result(s, uid, "You", oc, gf, ga)
    table = ranked_table(s)
    me = next(r for r in table if r["uid"] == uid)
    print(f"after 5 games -> {me['name']}: P{me['P']} W{me['W']} D{me['D']} L{me['L']} "
          f"GF{me['GF']} GA{me['GA']} GD{me['GD']} Pts{me['Pts']} -> position {me['pos']}/{len(table)}")
    print("top 5:")
    for r in table[:5]:
        tag = " (you)" if r["uid"] == uid else ""
        print(f"  {r['pos']:>2}. {r['name']:<18} P{r['P']:>2} W{r['W']:>2} D{r['D']:>2} L{r['L']:>2} GD{r['GD']:>+3} Pts{r['Pts']:>2}{tag}")
