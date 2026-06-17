# -*- coding: utf-8 -*-
"""
Persistent global Manager Rating for the football-manager game.

Every completed match updates a manager's chess-style rating (Elo): beating a
stronger opponent gains more, losing to a weaker one costs more, so the global
table measures skill rather than how many games you have played. Real entrants
only -- there are no synthetic managers.

Pure logic lives here (rate a result / tier / rank). The server owns storage and
identity, and supplies each opponent's rating: a 1v1 opponent's stored rating, or
a calibrated rating for the CPU.
"""

LEAGUE_KEY = "fb_global_league_v1"

START_RATING = 1000
RATING_FLOOR = 100
K_PROVISIONAL = 40        # first few games move fast (quick calibration)
K_STABLE = 24
PROVISIONAL_GAMES = 10

# Calibrated ratings for the CPU difficulties, so a result against the computer
# moves the manager rating by a sensible amount (beat the hard CPU and climb;
# lose to the easy CPU and it stings).
CPU_RATINGS = {"easy": 800, "medium": 1000, "hard": 1200}

# Rating tiers: status + a short key the client uses for badge styling.
_TIERS = [
    (1350, "World Class", "wc"),
    (1200, "Elite", "elite"),
    (1050, "Pro", "pro"),
    (900,  "Semi-Pro", "semipro"),
    (0,    "Sunday League", "sunday"),
]


def tier_for(rating):
    for floor, name, key in _TIERS:
        if rating >= floor:
            return {"name": name, "key": key}
    return {"name": "Sunday League", "key": "sunday"}


def blank_row(name):
    return {"name": name or "Manager", "rating": START_RATING, "games": 0,
            "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0,
            "best": START_RATING, "form": []}


def _expected(my_rating, opp_rating):
    return 1.0 / (1.0 + 10 ** ((opp_rating - my_rating) / 400.0))


def apply_result(standings, uid, name, outcome, opp_rating, gf, ga):
    """Update (or create) a manager's row with one match result, Elo-style.
       opp_rating is the rating of whoever they played (CPU or human)."""
    row = standings.get(uid) or blank_row(name)
    if name:
        row["name"] = name
    row.setdefault("rating", START_RATING)
    row.setdefault("games", 0)
    row.setdefault("best", row["rating"])
    row.setdefault("form", [])

    score = 1.0 if outcome == "win" else (0.5 if outcome == "draw" else 0.0)
    exp = _expected(row["rating"], float(opp_rating))
    k = K_PROVISIONAL if row["games"] < PROVISIONAL_GAMES else K_STABLE
    delta = round(k * (score - exp))
    row["rating"] = max(RATING_FLOOR, row["rating"] + delta)
    row["games"] += 1
    row["GF"] = row.get("GF", 0) + int(gf)
    row["GA"] = row.get("GA", 0) + int(ga)
    if outcome == "win":
        row["W"] = row.get("W", 0) + 1
    elif outcome == "draw":
        row["D"] = row.get("D", 0) + 1
    else:
        row["L"] = row.get("L", 0) + 1
    if row["rating"] > row.get("best", 0):
        row["best"] = row["rating"]
    f = list(row.get("form", []))
    f.append("W" if outcome == "win" else ("D" if outcome == "draw" else "L"))
    row["form"] = f[-5:]
    row["last_delta"] = delta
    standings[uid] = row
    return standings


def ranked_table(standings):
    """Sorted by rating (then games played, then name)."""
    rows = []
    for uid, r in standings.items():
        rating = r.get("rating", START_RATING)
        t = tier_for(rating)
        rows.append({
            "uid": uid, "name": r.get("name", "Manager"),
            "rating": rating, "games": r.get("games", 0),
            "W": r.get("W", 0), "D": r.get("D", 0), "L": r.get("L", 0),
            "GF": r.get("GF", 0), "GA": r.get("GA", 0),
            "best": r.get("best", rating),
            "form": list(r.get("form", []))[-5:],
            "tier": t["name"], "tier_key": t["key"],
            "last_delta": r.get("last_delta", 0),
        })
    rows.sort(key=lambda r: (-r["rating"], -r["games"], r["name"]))
    for i, r in enumerate(rows):
        r["pos"] = i + 1
    return rows


if __name__ == "__main__":
    s = {}
    uid = "u_test"
    seq = [("win", "medium", 3, 1), ("win", "hard", 2, 1), ("draw", "hard", 1, 1),
           ("loss", "easy", 0, 2), ("win", "medium", 4, 2)]
    for oc, lvl, gf, ga in seq:
        apply_result(s, uid, "You", oc, CPU_RATINGS[lvl], gf, ga)
    me = s[uid]
    print(f"after {me['games']} games -> rating {me['rating']} ({tier_for(me['rating'])['name']}) "
          f"W{me['W']} D{me['D']} L{me['L']} form {''.join(me['form'])}")
    for u, r in [("u_a", 1180), ("u_b", 980), ("u_c", 1320)]:
        s[u] = {"name": u, "rating": r, "games": 20, "W": 10, "D": 5, "L": 5,
                "GF": 30, "GA": 25, "best": r, "form": ["W", "W", "D", "L", "W"]}
    print("table:")
    for row in ranked_table(s):
        tag = " (you)" if row["uid"] == uid else ""
        print(f"  {row['pos']}. {row['name']:<8} {row['rating']:>4} {row['tier']:<12} {''.join(row['form'])}{tag}")
