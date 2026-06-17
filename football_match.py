# -*- coding: utf-8 -*-
"""
Match simulation engine for the football-manager game.

Philosophy (skill over luck):
  * The MIDFIELD battle decides territory/possession (more control = more
    chances).
  * ATTACK strength + possession decides how many chances you create.
  * Each chance converts with an xG-style probability driven by your attack
    vs the opponent's DEFENCE (which already folds in the keeper).
  * Randomness lives only at the per-chance level (Bernoulli trials), so the
    EXPECTED scoreline is set by squad quality + tactics, while variance lets
    an underdog occasionally nick a result. Over many games the better-built,
    better-shaped, better-managed team wins clearly more often.

Strategic levers that change the maths (not luck):
  * Formation / player choice -> flows in through zone strengths.
  * Tactic / mentality -> multiplies your attack vs defence trade-off.
  * Substitutions -> recompute a team's zones from the minute they happen.
  * Toss / home edge -> a small, explicit bump (never decisive on its own).

Pure functions over squads from football_game.zone_strengths — unit-testable,
no Flask, no sockets. The minute-stamped event list is what a live UI replays.
"""

import math
import random

import football_data as fd
import football_game as fg

# Tactic = zone multipliers. Attacking trades defensive solidity for threat;
# defensive does the reverse; pressing lifts midfield at a small defensive cost.
TACTICS = {
    "attacking": {"attack": 1.08, "midfield": 1.00, "defence": 0.92},
    "balanced":  {"attack": 1.00, "midfield": 1.00, "defence": 1.00},
    "defensive": {"attack": 0.90, "midfield": 1.00, "defence": 1.10},
    "press":     {"attack": 1.04, "midfield": 1.07, "defence": 0.95},
    "park-bus":  {"attack": 0.80, "midfield": 0.96, "defence": 1.20},
}
DEFAULT_TACTIC = "balanced"

HOME_EDGE = {"attack": 1.04, "midfield": 1.03, "defence": 1.02}  # modest, never decisive
HALF_MINUTES = 45


def _apply_tactic(zones, tactic, home=False):
    mult = TACTICS.get(tactic, TACTICS[DEFAULT_TACTIC])
    z = {
        "attack": zones["attack"] * mult["attack"],
        "midfield": zones["midfield"] * mult["midfield"],
        "defence": zones["defence"] * mult["defence"],
    }
    if home:
        z["attack"] *= HOME_EDGE["attack"]
        z["midfield"] *= HOME_EDGE["midfield"]
        z["defence"] *= HOME_EDGE["defence"]
    return z


def _chance_rate_per_min(attack, mid_share):
    """Expected shots over 90 -> per-minute chance probability. Midfield control
    (territory) strongly scales how many chances you get."""
    attack_factor = attack / 76.0
    shots_per_90 = 11.5 * attack_factor * (0.45 + 1.10 * mid_share)
    return max(0.015, shots_per_90 / 90.0)


def _conversion_prob(attack, opp_defence):
    """xG-style finish probability: your attack vs their defence (incl. keeper).

    Recentred by +6 because defensive zone ratings sit ~6 points above attacking
    ones on this scale, so an average attack vs an average defence converts at
    the base rate. The coefficient is tuned so a clear quality edge converts to a
    clear win rate, while a coin-flip match stays a coin flip."""
    q = 0.135 + 0.011 * (attack - opp_defence + 6.0)
    return max(0.03, min(0.55, q))


def _xi_players(squad):
    return [fd.get_player(pid) for pid in squad["starting"]]


def _pick_scorer(rng, xi):
    weights = []
    for p in xi:
        w = float(p["attrs"]["att"])
        if p["pos"] == "FWD":
            w *= 2.4
        elif p["pos"] == "MID":
            w *= 1.25
        elif p["pos"] == "DEF":
            w *= 0.22
        else:
            w *= 0.01
        weights.append(max(0.05, w))
    return _weighted(rng, xi, weights)


def _pick_assist(rng, xi, scorer):
    cands = [p for p in xi if p is not scorer and p["pos"] != "GK"]
    if not cands:
        return None
    weights = []
    for p in cands:
        w = float(p["attrs"]["mid"])
        if p["pos"] == "MID":
            w *= 1.5
        elif p["pos"] == "FWD":
            w *= 1.1
        else:
            w *= 0.6
        weights.append(max(0.05, w))
    # Not every goal has an assist.
    if rng.random() < 0.25:
        return None
    return _weighted(rng, cands, weights)


def _weighted(rng, items, weights):
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if r <= acc:
            return it
    return items[-1]


def _current_zones(squad, current_starting):
    """Recompute zones for a (possibly substituted) starting XI."""
    tmp = {"formation": squad["formation"], "starting": current_starting}
    return fg.zone_strengths(tmp)


# --- Adaptive AI manager: the CPU re-reads the game and reacts, like a real
# manager. It changes mentality by scoreline and makes upgrade substitutions,
# so there is no single fixed pattern a human can exploit to always win.
AI_REASSESS_MINUTES = (45, 68)


def _ai_decide_tactic(my_score, opp_score):
    diff = my_score - opp_score
    if diff <= -2:
        return "attacking"      # chasing the game hard
    if diff == -1:
        return "press"          # push for the equaliser
    if diff >= 2:
        return "defensive"      # protect a comfortable lead
    if diff == 1:
        return "balanced"       # manage a slender lead
    return "balanced"


def _ai_pick_sub(starting, bench_avail, score_diff):
    """Choose a like-for-like upgrade sub that fits the game state. Trailing ->
    refresh attacking areas first; protecting a lead -> shore up the defence.
    Returns (out_pid, in_pid) or None."""
    if not bench_avail:
        return None
    if score_diff < 0:
        pos_priority = ["FWD", "MID", "DEF"]
    elif score_diff >= 2:
        pos_priority = ["DEF", "MID", "FWD"]
    else:
        pos_priority = ["MID", "FWD", "DEF"]

    best = None  # (gain, out_pid, in_pid)
    for pos in pos_priority:
        bench_pos = [fd.get_player(pid) for pid in bench_avail if fd.get_player(pid)["pos"] == pos]
        start_pos = [fd.get_player(pid) for pid in starting if fd.get_player(pid)["pos"] == pos]
        if not bench_pos or not start_pos:
            continue
        in_p = max(bench_pos, key=lambda p: p["rating"])
        out_p = min(start_pos, key=lambda p: p["rating"])
        gain = in_p["rating"] - out_p["rating"]
        # Trailing managers gamble on attack even at a small rating loss.
        threshold = -2 if (score_diff < 0 and pos in ("FWD", "MID")) else 1
        if gain >= threshold and (best is None or gain > best[0]):
            best = (gain, out_p["id"], in_p["id"])
        if best is not None and pos == pos_priority[0]:
            break  # prefer acting in the highest-priority area
    if best is None:
        return None
    return best[1], best[2]


def simulate_match(home_squad, away_squad, *,
                   home_tactic=DEFAULT_TACTIC, away_tactic=DEFAULT_TACTIC,
                   home_subs=None, away_subs=None,
                   give_home_edge=True, seed=None,
                   home_name="Home", away_name="Away",
                   home_zones_override=None, away_zones_override=None,
                   away_ai=False,
                   minute_start=1, minute_end=90, init_hs=0, init_as=0,
                   away_start_init=None, away_tactic_init=None,
                   away_subs_made_init=0, away_bench_init=None,
                   init_shots=None, init_sot=None, init_poss=None):
    """Simulate a full match. Returns score, minute-stamped events, and stats.

    *_subs: optional list of (minute, out_pid, in_pid) applied live; the team's
    zones are recomputed from that minute (so a good sub genuinely helps).
    *_zones_override: feed effective zones directly (used for calibration).
    away_ai: the away side acts as an adaptive AI manager (reads the scoreline,
    changes mentality, makes upgrade subs)."""
    rng = random.Random(seed)

    home_start = list(home_squad["starting"])
    away_start = list(away_start_init) if away_start_init is not None else list(away_squad["starting"])
    home_subs = sorted(home_subs or [], key=lambda s: s[0])
    away_subs = sorted(away_subs or [], key=lambda s: s[0])
    hi = ai = 0  # sub pointers
    if away_tactic_init is not None:
        away_tactic = away_tactic_init

    def zones_for(squad, starting, tactic, home):
        return _apply_tactic(_current_zones(squad, starting), tactic, home)

    if home_zones_override is not None:
        hz = dict(home_zones_override)
    else:
        hz = zones_for(home_squad, home_start, home_tactic, give_home_edge)
    if away_zones_override is not None:
        az = dict(away_zones_override)
    else:
        az = zones_for(away_squad, away_start, away_tactic, False)

    events = []
    hs, as_ = init_hs, init_as
    shots = dict(init_shots) if init_shots else {"home": 0, "away": 0}
    sot = dict(init_sot) if init_sot else {"home": 0, "away": 0}
    poss_acc = dict(init_poss) if init_poss else {"home": 0.0, "away": 0.0}

    # Adaptive AI state (away side).
    away_bench_avail = list(away_bench_init) if away_bench_init is not None else list(away_squad.get("bench", []))
    away_subs_made = away_subs_made_init
    ai_done = set()

    def names(squad, starting):
        return {pid: fd.get_player(pid) for pid in starting}

    for minute in range(minute_start, minute_end + 1):
        # Apply any subs scheduled at/under this minute, then refresh zones.
        changed = False
        while hi < len(home_subs) and home_subs[hi][0] <= minute:
            _, out_pid, in_pid = home_subs[hi]
            if out_pid in home_start:
                home_start[home_start.index(out_pid)] = in_pid
                events.append({"minute": minute, "type": "sub", "team": "home",
                               "player": fd.get_player(in_pid)["short"],
                               "out": fd.get_player(out_pid)["short"]})
                changed = True
            hi += 1
        while ai < len(away_subs) and away_subs[ai][0] <= minute:
            _, out_pid, in_pid = away_subs[ai]
            if out_pid in away_start:
                away_start[away_start.index(out_pid)] = in_pid
                events.append({"minute": minute, "type": "sub", "team": "away",
                               "player": fd.get_player(in_pid)["short"],
                               "out": fd.get_player(out_pid)["short"]})
                changed = True
            ai += 1
        if changed:
            if home_zones_override is None:
                hz = zones_for(home_squad, home_start, home_tactic, give_home_edge)
            if away_zones_override is None:
                az = zones_for(away_squad, away_start, away_tactic, False)

        # Adaptive AI manager (away): re-read the game, adjust mentality, sub.
        if away_ai and minute in AI_REASSESS_MINUTES and minute not in ai_done:
            ai_done.add(minute)
            ai_changed = False
            new_tactic = _ai_decide_tactic(as_, hs)
            if new_tactic != away_tactic:
                away_tactic = new_tactic
                ai_changed = True
            if away_subs_made < 3 and away_bench_avail:
                pick = _ai_pick_sub(away_start, away_bench_avail, as_ - hs)
                if pick:
                    out_pid, in_pid = pick
                    away_start[away_start.index(out_pid)] = in_pid
                    away_bench_avail.remove(in_pid)
                    away_subs_made += 1
                    events.append({"minute": minute, "type": "sub", "team": "away",
                                   "player": fd.get_player(in_pid)["short"],
                                   "out": fd.get_player(out_pid)["short"]})
                    ai_changed = True
            if ai_changed and away_zones_override is None:
                az = zones_for(away_squad, away_start, away_tactic, False)

        mid_total = hz["midfield"] + az["midfield"]
        h_share = hz["midfield"] / mid_total if mid_total else 0.5
        a_share = 1.0 - h_share
        poss_acc["home"] += h_share
        poss_acc["away"] += a_share

        # Home chance?
        if rng.random() < _chance_rate_per_min(hz["attack"], h_share):
            shots["home"] += 1
            q = _conversion_prob(hz["attack"], az["defence"])
            on_target = rng.random() < 0.45 + q
            if on_target:
                sot["home"] += 1
            if rng.random() < q:
                hs += 1
                xi = _xi_players({"starting": home_start})
                scorer = _pick_scorer(rng, xi)
                assist = _pick_assist(rng, xi, scorer)
                events.append({"minute": minute, "type": "goal", "team": "home",
                               "player": scorer["short"],
                               "assist": assist["short"] if assist else None,
                               "score": None})
        # Away chance?
        if rng.random() < _chance_rate_per_min(az["attack"], a_share):
            shots["away"] += 1
            q = _conversion_prob(az["attack"], hz["defence"])
            on_target = rng.random() < 0.45 + q
            if on_target:
                sot["away"] += 1
            if rng.random() < q:
                as_ += 1
                xi = _xi_players({"starting": away_start})
                scorer = _pick_scorer(rng, xi)
                assist = _pick_assist(rng, xi, scorer)
                events.append({"minute": minute, "type": "goal", "team": "away",
                               "player": scorer["short"],
                               "assist": assist["short"] if assist else None,
                               "score": None})

        # Occasional booking (flavour; doesn't swing the result).
        if rng.random() < 0.010:
            team = "home" if rng.random() < 0.5 else "away"
            start = home_start if team == "home" else away_start
            outfield = [fd.get_player(pid) for pid in start if fd.get_player(pid)["pos"] != "GK"]
            if outfield:
                bp = rng.choice(outfield)
                events.append({"minute": minute, "type": "card", "team": team,
                               "card": "yellow", "player": bp["short"]})

        if minute == HALF_MINUTES:
            events.append({"minute": minute, "type": "ht", "home_score": hs, "away_score": as_})

    if minute_end >= 90:
        events.append({"minute": 90, "type": "ft", "home_score": hs, "away_score": as_})

    # Fill running score onto goal events (continuing from the starting score).
    rh, ra = init_hs, init_as
    for e in events:
        if e["type"] == "goal":
            if e["team"] == "home":
                rh += 1
            else:
                ra += 1
            e["score"] = f"{rh}-{ra}"

    if minute_end < 90:
        # Half-time (or any mid-match) break: hand back the state needed to
        # resume the second half after the manager makes changes.
        return {
            "home_score": hs, "away_score": as_,
            "home_name": home_name, "away_name": away_name,
            "events": events,
            "resume_state": {
                "away_start": list(away_start),
                "away_tactic": away_tactic,
                "away_subs_made": away_subs_made,
                "away_bench_avail": list(away_bench_avail),
                "hs": hs, "as": as_,
                "shots": dict(shots), "sot": dict(sot),
                "poss": {"home": poss_acc["home"], "away": poss_acc["away"]},
            },
        }

    total_min = 90.0
    poss_home = round(100 * poss_acc["home"] / total_min)
    poss_home = max(25, min(75, poss_home))   # clamp to believable range
    stats = {
        "possession_home": poss_home,
        "possession_away": 100 - poss_home,
        "shots_home": shots["home"], "shots_away": shots["away"],
        "sot_home": sot["home"], "sot_away": sot["away"],
    }
    return {
        "home_score": hs, "away_score": as_,
        "home_name": home_name, "away_name": away_name,
        "events": events, "stats": stats,
    }


if __name__ == "__main__":
    import statistics as st

    def fresh(seed):
        return fg.draft_squad("4-3-3", fg.BUDGET, seed=seed)

    def tiered(rank_start):
        """A squad built from the rank_start-th best players per position
        (0 = world-class). Ignores budget — used to test the ENGINE's response
        to genuine quality gaps, separately from the economy."""
        f = fg.FORMATIONS["4-3-3"]; need = fg.squad_requirements("4-3-3")
        starting, bench = [], []
        for pos in fd.POSITIONS:
            ranked = sorted(fd.by_position(pos), key=lambda p: -p["rating"])
            chosen = ranked[rank_start:rank_start + need[pos]]
            chosen = sorted(chosen, key=lambda p: -p["rating"])
            starting += [p["id"] for p in chosen[:f[pos]]]
            bench += [p["id"] for p in chosen[f[pos]:]]
        return {"formation": "4-3-3", "starting": starting, "bench": bench}

    def winrate(za, zb, n=4000, base=0):
        w = {"a": 0, "d": 0, "b": 0}
        a = b = fresh(7)  # squads only needed for scorer names
        for i in range(n):
            m = simulate_match(a, b, seed=base + i, give_home_edge=False,
                               home_zones_override=za, away_zones_override=zb)
            if m["home_score"] > m["away_score"]:
                w["a"] += 1
            elif m["home_score"] < m["away_score"]:
                w["b"] += 1
            else:
                w["d"] += 1
        return w["a"] * 100 // n, w["d"] * 100 // n, w["b"] * 100 // n

    print("=== realism: 5000 matches, two AVERAGE drafted squads ===")
    gh, ga, res = [], [], {"h": 0, "d": 0, "a": 0}
    for i in range(5000):
        m = simulate_match(fresh(1000 + i), fresh(9000 + i), seed=i, give_home_edge=False)
        gh.append(m["home_score"]); ga.append(m["away_score"])
        res["h" if m["home_score"] > m["away_score"] else "a" if m["home_score"] < m["away_score"] else "d"] += 1
    print(f"  avg goals/match {st.mean([h+a for h,a in zip(gh,ga)]):.2f}  "
          f"| home {res['h']*100//5000}%  draw {res['d']*100//5000}%  away {res['a']*100//5000}%")

    print("\n=== skill sensitivity: win rate vs quality gap (overall zone points) ===")
    avg = {"attack": 78.0, "midfield": 78.0, "defence": 84.0}
    for gap in (0, 2, 4, 7, 11, 16):
        stronger = {k: avg[k] + gap for k in avg}
        a_pct, d_pct, b_pct = winrate(stronger, avg, base=gap * 100000)
        print(f"  +{gap:>2} pts -> stronger wins {a_pct}%  draw {d_pct}%  weaker wins {b_pct}%")

    print("\n=== real tiers (engine response to genuinely different squads) ===")
    elite, good, weak = tiered(0), tiered(7), tiered(16)
    for nm, s in (("elite", elite), ("good", good), ("weak", weak)):
        print(f"  {nm:<6} zones {fg.zone_strengths(s)}")
    for label, A, B in (("elite vs weak", elite, weak), ("elite vs good", elite, good),
                        ("good vs weak", good, weak)):
        za, zb = fg.zone_strengths(A), fg.zone_strengths(B)
        a_pct, d_pct, b_pct = winrate(za, zb, base=hash(label) % 90000)
        print(f"  {label:<14}: {a_pct}% / {d_pct}% / {b_pct}%")

    print("\n=== tactics matter: identical squads, attacking vs park-the-bus ===")
    a = fresh(7)
    za = _apply_tactic(fg.zone_strengths(a), "attacking")
    zb = _apply_tactic(fg.zone_strengths(a), "park-bus")
    a_pct, d_pct, b_pct = winrate(za, zb, base=777000)
    print(f"  attacking {a_pct}%  draw {d_pct}%  park-bus {b_pct}%")

    print("\n=== sample live feed (elite vs weak) ===")
    m = simulate_match(elite, weak, seed=42, home_name="Your XI", away_name="Rivals")
    print(f"  FT {m['home_name']} {m['home_score']}-{m['away_score']} {m['away_name']}  "
          f"poss {m['stats']['possession_home']}/{m['stats']['possession_away']}  "
          f"shots {m['stats']['shots_home']}/{m['stats']['shots_away']}")
    for e in m["events"]:
        if e["type"] == "goal":
            asst = f", assist {e['assist']}" if e["assist"] else ""
            print(f"    {e['minute']}'  GOAL  {e['player']}{asst}  [{e['team']}]  {e['score']}")
        elif e["type"] == "ht":
            print(f"    -- HT {e['home_score']}-{e['away_score']} --")

