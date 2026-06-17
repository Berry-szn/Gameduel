# -*- coding: utf-8 -*-
"""
Squad logic for the football-manager game: formations, the random draft (the
"shuffle"), transfers in/out, budget + formation validation, and zone-strength
computation (attack / midfield / defence) that the match engine will use so
outcomes are driven by squad quality and tactics rather than luck.

Pure functions over the player pool in football_data.py — unit-testable.
"""

import random
import football_data as fd

BUDGET = 200.0          # $m total squad budget
BENCH = {"GK": 1, "DEF": 1, "MID": 1, "FWD": 1}   # 4 subs, one per line

# Starting-XI shape per formation (outfield + 1 GK = 11).
FORMATIONS = {
    "4-3-3":   {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3},
    "4-4-2":   {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2},
    "3-5-2":   {"GK": 1, "DEF": 3, "MID": 5, "FWD": 2},
    "4-2-3-1": {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1},
    "5-3-2":   {"GK": 1, "DEF": 5, "MID": 3, "FWD": 2},
    "4-5-1":   {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1},
}
DEFAULT_FORMATION = "4-3-3"


def squad_requirements(formation):
    """Total players needed per position (starting XI + bench)."""
    f = FORMATIONS[formation]
    return {pos: f[pos] + BENCH[pos] for pos in fd.POSITIONS}


# --------------------------------------------------------------------------
# Draft (the random shuffle)
# --------------------------------------------------------------------------

def _min_cost_for_remaining(left, pools, used):
    """Cheapest possible cost to fill the still-unfilled slots, so we never
    paint ourselves into a corner that can't complete the squad under budget."""
    total = 0.0
    # temp-track picks so two slots of the same pos don't both claim one player
    claimed = set()
    for pos, n in left.items():
        if n <= 0:
            continue
        avail = [p for p in pools[pos] if p["id"] not in used and p["id"] not in claimed]
        avail = avail[:n]            # pools are price-sorted ascending
        if len(avail) < n:
            return float("inf")      # not completable
        for p in avail:
            total += p["price"]
            claimed.add(p["id"])
    return total


def _weighted_pick(rng, players):
    """Lean toward better players so squads are viable, but keep enough
    randomness that shuffles vary in quality — some draws are strong, some
    need work, which is what makes re-shuffling and transfers compelling."""
    weights = [max(0.5, (p["rating"] - 70)) ** 1.25 + 0.6 for p in players]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for p, w in zip(players, weights):
        acc += w
        if r <= acc:
            return p
    return players[-1]


def draft_squad(formation=DEFAULT_FORMATION, budget=BUDGET, seed=None, spend_fraction=0.90):
    """Return a random, budget-valid squad for the formation.

    Drafts to ~spend_fraction of the budget so the manager keeps money in the
    bank to make upgrade transfers immediately (not only like-for-like swaps).
    Returns dict: {formation, starting, bench, players, cost}.
    The strongest player per position fills the starting XI; the rest bench.
    """
    if formation not in FORMATIONS:
        formation = DEFAULT_FORMATION
    rng = random.Random(seed)
    need = squad_requirements(formation)
    soft_cap = budget * spend_fraction

    pools = {pos: sorted(fd.by_position(pos), key=lambda p: p["price"]) for pos in fd.POSITIONS}

    slots = []
    for pos in fd.POSITIONS:
        slots.extend([pos] * need[pos])
    rng.shuffle(slots)

    left = dict(need)
    used = set()
    chosen = []
    remaining = float(soft_cap)

    for pos in slots:
        left[pos] -= 1
        min_rest = _min_cost_for_remaining(left, pools, used)
        max_now = remaining - min_rest
        affordable = [p for p in pools[pos]
                      if p["id"] not in used and p["price"] <= max_now + 1e-9]
        if not affordable:
            affordable = [p for p in pools[pos] if p["id"] not in used][:1]
        pick = _weighted_pick(rng, affordable)
        chosen.append(pick)
        used.add(pick["id"])
        remaining -= pick["price"]

    # Split into starting XI (best per position) and bench.
    f = FORMATIONS[formation]
    by_pos = {pos: [] for pos in fd.POSITIONS}
    for p in chosen:
        by_pos[p["pos"]].append(p)
    starting, bench = [], []
    for pos in fd.POSITIONS:
        ranked = sorted(by_pos[pos], key=lambda p: -p["rating"])
        starting.extend(ranked[:f[pos]])
        bench.extend(ranked[f[pos]:])

    players = {p["id"]: p for p in chosen}
    return {
        "formation": formation,
        "starting": [p["id"] for p in starting],
        "bench": [p["id"] for p in bench],
        "players": players,
        "cost": round(sum(p["price"] for p in chosen), 1),
    }


# --------------------------------------------------------------------------
# Cost / rating / validation
# --------------------------------------------------------------------------

def _all_ids(squad):
    return list(squad["starting"]) + list(squad["bench"])


def squad_cost(squad):
    return round(sum(fd.get_player(pid)["price"] for pid in _all_ids(squad)), 1)


def squad_overall(squad):
    """Average rating of the starting XI (the headline 'team rating')."""
    xi = [fd.get_player(pid) for pid in squad["starting"]]
    return round(sum(p["rating"] for p in xi) / max(1, len(xi)), 1)


def validate_squad(squad, budget=BUDGET):
    """Return (ok, reason). Checks positions match formation+bench, 15 unique
    players, and total cost within budget."""
    formation = squad.get("formation")
    if formation not in FORMATIONS:
        return False, "Unknown formation"
    ids = _all_ids(squad)
    if len(ids) != 15:
        return False, f"Squad must be 15 players (got {len(ids)})"
    if len(set(ids)) != 15:
        return False, "Duplicate player in squad"
    for pid in ids:
        if fd.get_player(pid) is None:
            return False, "Unknown player in squad"
    # starting XI position counts == formation
    f = FORMATIONS[formation]
    from collections import Counter
    start_counts = Counter(fd.get_player(pid)["pos"] for pid in squad["starting"])
    if len(squad["starting"]) != 11:
        return False, "Starting XI must be 11 players"
    for pos in fd.POSITIONS:
        if start_counts.get(pos, 0) != f[pos]:
            return False, f"Formation {formation} needs {f[pos]} {pos}, has {start_counts.get(pos,0)}"
    # full-squad position totals == requirements (so bench is one per line)
    need = squad_requirements(formation)
    total_counts = Counter(fd.get_player(pid)["pos"] for pid in ids)
    for pos in fd.POSITIONS:
        if total_counts.get(pos, 0) != need[pos]:
            return False, f"Squad needs {need[pos]} {pos} total, has {total_counts.get(pos,0)}"
    cost = squad_cost(squad)
    if cost > budget + 1e-6:
        return False, f"Over budget: ${cost}m of ${budget}m"
    return True, "ok"


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------

def transfer(squad, out_id, in_id, budget=BUDGET):
    """Swap out_id for in_id (must be the same position to keep the formation
    valid, must be affordable, must not already be in the squad).

    Returns (ok, reason, new_squad). new_squad is None on failure.
    """
    if out_id not in _all_ids(squad):
        return False, "That player isn't in your squad", None
    in_player = fd.get_player(in_id)
    out_player = fd.get_player(out_id)
    if in_player is None:
        return False, "Unknown incoming player", None
    if in_id in _all_ids(squad):
        return False, f"{in_player['short']} is already in your squad", None
    if in_player["pos"] != out_player["pos"]:
        return False, (f"Must swap like-for-like: {out_player['short']} is a "
                       f"{out_player['pos']}, {in_player['short']} is a {in_player['pos']}"), None
    new_cost = squad_cost(squad) - out_player["price"] + in_player["price"]
    if new_cost > budget + 1e-6:
        short = round(new_cost - budget, 1)
        return False, f"Can't afford {in_player['short']} — ${short}m over budget", None

    new = {
        "formation": squad["formation"],
        "starting": [in_id if pid == out_id else pid for pid in squad["starting"]],
        "bench": [in_id if pid == out_id else pid for pid in squad["bench"]],
    }
    new["players"] = {pid: fd.get_player(pid) for pid in _all_ids(new)}
    new["cost"] = round(new_cost, 1)
    return True, "ok", new


# --------------------------------------------------------------------------
# Zone strengths — what the match engine reads (skill, not luck)
# --------------------------------------------------------------------------

def zone_strengths(squad):
    """Compute attack / midfield / defence ratings (0-100ish) for the STARTING
    XI. Tactics matter: more attackers raises attack but can thin midfield;
    a strong keeper and centre-backs anchor the defence.

    Returns {attack, midfield, defence, overall}.
    """
    xi = [fd.get_player(pid) for pid in squad["starting"]]
    gk = next((p for p in xi if p["pos"] == "GK"), None)
    defs = [p for p in xi if p["pos"] == "DEF"]
    mids = [p for p in xi if p["pos"] == "MID"]
    fwds = [p for p in xi if p["pos"] == "FWD"]

    def avg(vals, default=60.0):
        return sum(vals) / len(vals) if vals else default

    # Attack: forwards' finishing + midfield creativity + overlapping fullbacks.
    attack = (0.58 * avg([p["attrs"]["att"] for p in fwds]) +
              0.30 * avg([p["attrs"]["att"] for p in mids]) +
              0.12 * avg([p["attrs"]["att"] for p in defs]))
    # A lone striker is less potent than a front three — reward attacking numbers,
    # with diminishing returns.
    attack *= (0.86 + 0.05 * min(len(fwds), 3))

    # Midfield control: central midfielders, plus a little from creative forwards
    # and ball-playing defenders. Being out-numbered in midfield hurts.
    midfield = (0.74 * avg([p["attrs"]["mid"] for p in mids]) +
                0.14 * avg([p["attrs"]["mid"] for p in fwds]) +
                0.12 * avg([p["attrs"]["mid"] for p in defs]))
    midfield *= (0.84 + 0.05 * min(len(mids), 5))

    # Defence: centre-backs + the keeper + midfield screening.
    defence = (0.52 * avg([p["attrs"]["dfn"] for p in defs]) +
               0.28 * (gk["attrs"]["gk"] if gk else 70) +
               0.20 * avg([p["attrs"]["dfn"] for p in mids]))
    defence *= (0.88 + 0.04 * min(len(defs), 5))

    clamp = lambda x: round(max(1.0, min(100.0, x)), 1)
    attack, midfield, defence = clamp(attack), clamp(midfield), clamp(defence)
    overall = round((attack + midfield + defence) / 3, 1)
    return {"attack": attack, "midfield": midfield, "defence": defence, "overall": overall}


def validate_starting_xi(starting, formation):
    """Lighter check for a live (possibly substituted) XI: 11 valid, unique
    players matching the formation's position counts. Used for the second half,
    where subbed-off players have left and the full 15-man check no longer fits."""
    if formation not in FORMATIONS:
        return False, "Unknown formation"
    if len(starting) != 11:
        return False, f"Starting XI must be 11 players (got {len(starting)})"
    if len(set(starting)) != 11:
        return False, "Duplicate player in XI"
    from collections import Counter
    cnt = Counter()
    for pid in starting:
        p = fd.get_player(pid)
        if p is None:
            return False, "Unknown player in XI"
        cnt[p["pos"]] += 1
    f = FORMATIONS[formation]
    for pos in fd.POSITIONS:
        if cnt.get(pos, 0) != f[pos]:
            return False, f"Formation {formation} needs {f[pos]} {pos}, has {cnt.get(pos,0)}"
    return True, "ok"


# --------------------------------------------------------------------------
# CPU opponents (solo vs computer)
# --------------------------------------------------------------------------
# Difficulty = how strong a player pool the CPU draws from (lower tier = better
# players). A budget-bound human squad sits around the "medium" band, so easy is
# winnable, medium is a real contest, and hard demands a good squad + tactics.
CPU_META = {
    "easy":   {"name": "Sunday League XI", "tier": 13, "tactic": "balanced",  "formation": "4-4-2"},
    "medium": {"name": "City Rivals",       "tier": 7,  "tactic": "balanced",  "formation": "4-3-3"},
    "hard":   {"name": "The Galácticos",    "tier": 1,  "tactic": "press",     "formation": "4-3-3"},
}


def build_cpu_squad(level="medium", seed=None):
    """A computer squad at the given difficulty. Picks players from a quality
    band (with small per-game variety) so the CPU differs match to match."""
    meta = CPU_META.get(level, CPU_META["medium"])
    formation = meta["formation"]
    rng = random.Random(seed)
    f = FORMATIONS[formation]
    need = squad_requirements(formation)
    starting, bench = [], []
    for pos in fd.POSITIONS:
        ranked = sorted(fd.by_position(pos), key=lambda p: -p["rating"])
        start_idx = min(max(0, meta["tier"] + rng.randint(-1, 3)),
                        max(0, len(ranked) - need[pos]))
        chosen = ranked[start_idx:start_idx + need[pos]]
        if len(chosen) < need[pos]:
            chosen = ranked[-need[pos]:]
        chosen = sorted(chosen, key=lambda p: -p["rating"])
        starting += [p["id"] for p in chosen[:f[pos]]]
        bench += [p["id"] for p in chosen[f[pos]:]]
    return {"formation": formation, "starting": starting, "bench": bench,
            "name": meta["name"], "tactic": meta["tactic"]}


if __name__ == "__main__":
    print("=== draft sanity (1000 squads) ===")
    costs, ovrs, bad = [], [], 0
    for i in range(1000):
        s = draft_squad("4-3-3", BUDGET, seed=i)
        ok, why = validate_squad(s)
        if not ok:
            bad += 1
            if bad <= 3:
                print("  INVALID:", why)
        costs.append(squad_cost(s))
        ovrs.append(squad_overall(s))
    print(f"  invalid squads: {bad}/1000")
    print(f"  avg cost ${sum(costs)/len(costs):.1f}m  (min ${min(costs):.1f}, max ${max(costs):.1f})")
    print(f"  avg XI rating {sum(ovrs)/len(ovrs):.1f}  (min {min(ovrs)}, max {max(ovrs)})")

    print("\n=== does the budget cap bind? (can't buy all the best) ===")
    dream = sorted(fd.get_pool(), key=lambda p: -p["rating"])[:15]
    print(f"  top-15 by rating cost ${sum(p['price'] for p in dream):.1f}m vs ${BUDGET}m budget")
    # The meaningful test: the most EXPENSIVE valid 4-3-3 squad.
    need = squad_requirements("4-3-3")
    most = 0.0
    for pos, n in need.items():
        top = sorted(fd.by_position(pos), key=lambda p: -p["price"])[:n]
        most += sum(p["price"] for p in top)
    print(f"  most expensive valid squad costs ${most:.1f}m vs ${BUDGET}m  "
          f"-> over by ${most-BUDGET:.1f}m  ({'BINDS' if most>BUDGET else 'does NOT bind'})")
    print("\n=== sample premium prices ===")
    for nm in ["Haaland", "Mbappé", "Salah", "De Bruyne", "Van Dijk", "Alisson", "Saka", "Rice"]:
        p = next((x for x in fd.get_pool() if x["short"] == nm), None)
        if p:
            print(f"  {p['short']:<12} ovr {p['rating']}  ${p['price']:.1f}m")
