# -*- coding: utf-8 -*-
"""
Player database for the football-manager game ("GaffaDuel").

Each player has a real name, a position (GK/DEF/MID/FWD), an overall rating,
a derived transfer PRICE, and derived engine ATTRIBUTES (att/mid/dfn/pac/gk).

Design goals (skill over luck):
  * price is a deterministic function of rating + a position premium, so
    higher-rated players genuinely cost more and the $200m cap forces real
    trade-offs (you cannot buy a full team of superstars).
  * a small, deterministic "value noise" makes some players bargains and some
    overpriced — that is the transfer-market skill layer (find undervalued
    rating-per-dollar to build a stronger XI within budget).
  * engine attributes are derived from rating + position archetype with
    deterministic per-player variation, so squads differ in character (a fast
    defender, a defensive midfielder, a poacher) and tactics matter.

Everything here is pure data + pure functions — no Flask, no sockets — so it
can be unit-tested in isolation.
"""

import hashlib

# (name, short, position, overall_rating, club)
_RAW = [
    # ---- Goalkeepers ----
    ("Alisson", "Alisson", "GK", 89, "Liverpool"),
    ("Ederson", "Ederson", "GK", 88, "Man City"),
    ("Thibaut Courtois", "Courtois", "GK", 89, "Real Madrid"),
    ("Gianluigi Donnarumma", "Donnarumma", "GK", 88, "PSG"),
    ("Jan Oblak", "Oblak", "GK", 87, "Atlético"),
    ("Marc-André ter Stegen", "Ter Stegen", "GK", 88, "Barcelona"),
    ("Mike Maignan", "Maignan", "GK", 87, "Milan"),
    ("André Onana", "Onana", "GK", 84, "Man Utd"),
    ("David Raya", "Raya", "GK", 84, "Arsenal"),
    ("Yann Sommer", "Sommer", "GK", 84, "Inter"),
    ("Emiliano Martínez", "E. Martínez", "GK", 86, "Aston Villa"),
    ("Manuel Neuer", "Neuer", "GK", 85, "Bayern"),

    # ---- Defenders ----
    ("Virgil van Dijk", "Van Dijk", "DEF", 89, "Liverpool"),
    ("William Saliba", "Saliba", "DEF", 86, "Arsenal"),
    ("Rúben Dias", "Dias", "DEF", 88, "Man City"),
    ("Achraf Hakimi", "Hakimi", "DEF", 85, "PSG"),
    ("Trent Alexander-Arnold", "Arnold", "DEF", 87, "Liverpool"),
    ("Alphonso Davies", "Davies", "DEF", 84, "Bayern"),
    ("Kyle Walker", "Walker", "DEF", 84, "Man City"),
    ("Alessandro Bastoni", "Bastoni", "DEF", 86, "Inter"),
    ("Marquinhos", "Marquinhos", "DEF", 87, "PSG"),
    ("Theo Hernández", "T. Hernández", "DEF", 85, "Milan"),
    ("Joško Gvardiol", "Gvardiol", "DEF", 84, "Man City"),
    ("Jules Koundé", "Koundé", "DEF", 84, "Barcelona"),
    ("Ronald Araújo", "Araújo", "DEF", 85, "Barcelona"),
    ("João Cancelo", "Cancelo", "DEF", 84, "Barcelona"),
    ("Antonio Rüdiger", "Rüdiger", "DEF", 86, "Real Madrid"),
    ("Matthijs de Ligt", "De Ligt", "DEF", 85, "Man Utd"),
    ("Andrew Robertson", "Robertson", "DEF", 85, "Liverpool"),
    ("Kieran Trippier", "Trippier", "DEF", 83, "Newcastle"),
    ("Ben White", "White", "DEF", 82, "Arsenal"),
    ("John Stones", "Stones", "DEF", 85, "Man City"),
    ("Éder Militão", "Militão", "DEF", 85, "Real Madrid"),
    ("Benjamin Pavard", "Pavard", "DEF", 83, "Inter"),
    ("Gabriel Magalhães", "Gabriel", "DEF", 85, "Arsenal"),
    ("Ibrahima Konaté", "Konaté", "DEF", 83, "Liverpool"),
    ("Fikayo Tomori", "Tomori", "DEF", 82, "Milan"),
    ("Sven Botman", "Botman", "DEF", 81, "Newcastle"),
    ("Federico Dimarco", "Dimarco", "DEF", 83, "Inter"),
    ("Dani Carvajal", "Carvajal", "DEF", 84, "Real Madrid"),
    ("Ferland Mendy", "Mendy", "DEF", 81, "Real Madrid"),
    ("Pervis Estupiñán", "Estupiñán", "DEF", 80, "Brighton"),
    ("James Tarkowski", "Tarkowski", "DEF", 79, "Everton"),

    # ---- Midfielders ----
    ("Kevin De Bruyne", "De Bruyne", "MID", 91, "Man City"),
    ("Jude Bellingham", "Bellingham", "MID", 88, "Real Madrid"),
    ("Rodri", "Rodri", "MID", 89, "Man City"),
    ("Luka Modrić", "Modrić", "MID", 85, "Real Madrid"),
    ("Toni Kroos", "Kroos", "MID", 86, "Real Madrid"),
    ("Pedri", "Pedri", "MID", 85, "Barcelona"),
    ("Gavi", "Gavi", "MID", 82, "Barcelona"),
    ("Bruno Fernandes", "B. Fernandes", "MID", 87, "Man Utd"),
    ("Martin Ødegaard", "Ødegaard", "MID", 87, "Arsenal"),
    ("Federico Valverde", "Valverde", "MID", 87, "Real Madrid"),
    ("Aurélien Tchouaméni", "Tchouaméni", "MID", 84, "Real Madrid"),
    ("Eduardo Camavinga", "Camavinga", "MID", 83, "Real Madrid"),
    ("Joshua Kimmich", "Kimmich", "MID", 87, "Bayern"),
    ("Leon Goretzka", "Goretzka", "MID", 84, "Bayern"),
    ("Declan Rice", "Rice", "MID", 86, "Arsenal"),
    ("Florian Wirtz", "Wirtz", "MID", 85, "Leverkusen"),
    ("Bernardo Silva", "B. Silva", "MID", 86, "Man City"),
    ("Mason Mount", "Mount", "MID", 81, "Man Utd"),
    ("Nicolò Barella", "Barella", "MID", 86, "Inter"),
    ("Hakan Çalhanoğlu", "Çalhanoğlu", "MID", 85, "Inter"),
    ("Moisés Caicedo", "Caicedo", "MID", 83, "Chelsea"),
    ("Enzo Fernández", "E. Fernández", "MID", 84, "Chelsea"),
    ("Alexis Mac Allister", "Mac Allister", "MID", 84, "Liverpool"),
    ("Dominik Szoboszlai", "Szoboszlai", "MID", 83, "Liverpool"),
    ("Martín Zubimendi", "Zubimendi", "MID", 83, "Real Sociedad"),
    ("Kobbie Mainoo", "Mainoo", "MID", 78, "Man Utd"),
    ("Christian Eriksen", "Eriksen", "MID", 80, "Man Utd"),
    ("Fabián Ruiz", "F. Ruiz", "MID", 84, "PSG"),
    ("Vitinha", "Vitinha", "MID", 84, "PSG"),
    ("Frenkie de Jong", "De Jong", "MID", 86, "Barcelona"),
    ("Casemiro", "Casemiro", "MID", 84, "Man Utd"),
    ("İlkay Gündoğan", "Gündoğan", "MID", 85, "Barcelona"),

    # ---- Forwards ----
    ("Erling Haaland", "Haaland", "FWD", 91, "Man City"),
    ("Kylian Mbappé", "Mbappé", "FWD", 91, "Real Madrid"),
    ("Mohamed Salah", "Salah", "FWD", 89, "Liverpool"),
    ("Harry Kane", "Kane", "FWD", 90, "Bayern"),
    ("Vinícius Júnior", "Vinícius", "FWD", 89, "Real Madrid"),
    ("Robert Lewandowski", "Lewandowski", "FWD", 89, "Barcelona"),
    ("Victor Osimhen", "Osimhen", "FWD", 88, "Napoli"),
    ("Lautaro Martínez", "L. Martínez", "FWD", 87, "Inter"),
    ("Darwin Núñez", "Núñez", "FWD", 82, "Liverpool"),
    ("Gabriel Jesus", "Jesus", "FWD", 82, "Arsenal"),
    ("Marcus Rashford", "Rashford", "FWD", 84, "Man Utd"),
    ("Son Heung-min", "Son", "FWD", 87, "Tottenham"),
    ("Raheem Sterling", "Sterling", "FWD", 82, "Chelsea"),
    ("Antoine Griezmann", "Griezmann", "FWD", 87, "Atlético"),
    ("Paulo Dybala", "Dybala", "FWD", 85, "Roma"),
    ("Rafael Leão", "Leão", "FWD", 85, "Milan"),
    ("Khvicha Kvaratskhelia", "Kvaratskhelia", "FWD", 86, "Napoli"),
    ("Cody Gakpo", "Gakpo", "FWD", 82, "Liverpool"),
    ("Christopher Nkunku", "Nkunku", "FWD", 83, "Chelsea"),
    ("Dušan Vlahović", "Vlahović", "FWD", 85, "Juventus"),
    ("Alexander Isak", "Isak", "FWD", 85, "Newcastle"),
    ("Ollie Watkins", "Watkins", "FWD", 84, "Aston Villa"),
    ("Kai Havertz", "Havertz", "FWD", 83, "Arsenal"),
    ("Phil Foden", "Foden", "FWD", 87, "Man City"),
    ("Bukayo Saka", "Saka", "FWD", 87, "Arsenal"),
    ("Jamal Musiala", "Musiala", "FWD", 86, "Bayern"),
    ("Leroy Sané", "Sané", "FWD", 84, "Bayern"),
    ("Dani Olmo", "Olmo", "FWD", 84, "Barcelona"),
]

POSITIONS = ("GK", "DEF", "MID", "FWD")

# Attacking forwards cost the most per rating point; keepers/defenders least.
_POS_PRICE_MULT = {"FWD": 1.00, "MID": 0.90, "DEF": 0.70, "GK": 0.60}


def _unit_noise(name, key):
    """Deterministic value in [-0.5, 0.5] from a name+key hash."""
    h = int(hashlib.md5((name + "|" + key).encode("utf-8")).hexdigest(), 16)
    return (h % 100000) / 100000.0 - 0.5


def _derive_price(name, pos, rating):
    # Convex in rating: a 91 costs far more than an 84, so a $200m budget
    # cannot field a superstar at every position — you must make trade-offs.
    d = rating - 70                              # 0..21
    base = 4.0 + 0.30 * d + 0.035 * d * d        # 70->4.0, 80->10.5, 87->19.2, 91->25.7
    mult = _POS_PRICE_MULT[pos]
    value_noise = 1.0 + _unit_noise(name, "price") * 0.14   # +/- 7% (bargains/traps)
    price = base * mult * value_noise
    price = max(4.0, price)
    return round(price * 2) / 2.0              # nearest 0.5


def _clamp(x):
    return max(40, min(99, int(round(x))))


def _derive_attrs(name, pos, rating):
    """att = attacking output, mid = control/passing, dfn = defending,
    pac = pace, gk = goalkeeping. Derived from a position archetype with
    deterministic per-player variation so squads differ in character."""
    n = lambda key, spread: _unit_noise(name, key) * 2 * spread
    if pos == "GK":
        return {"att": _clamp(rating * 0.20), "mid": _clamp(rating * 0.45),
                "dfn": _clamp(rating * 0.55), "pac": _clamp(rating * 0.50 + n("pac", 6)),
                "gk": _clamp(rating)}
    if pos == "DEF":
        return {"att": _clamp(rating * 0.55 + n("att", 9)), "mid": _clamp(rating * 0.72 + n("mid", 6)),
                "dfn": _clamp(rating * 0.98 + n("dfn", 4)), "pac": _clamp(rating * 0.86 + n("pac", 10)),
                "gk": 28}
    if pos == "MID":
        return {"att": _clamp(rating * 0.80 + n("att", 9)), "mid": _clamp(rating * 0.97 + n("mid", 4)),
                "dfn": _clamp(rating * 0.70 + n("dfn", 9)), "pac": _clamp(rating * 0.82 + n("pac", 8)),
                "gk": 24}
    # FWD
    return {"att": _clamp(rating * 0.98 + n("att", 4)), "mid": _clamp(rating * 0.70 + n("mid", 9)),
            "dfn": _clamp(rating * 0.42 + n("dfn", 8)), "pac": _clamp(rating * 0.90 + n("pac", 8)),
            "gk": 20}


def _build():
    out = []
    seen = set()
    for (name, short, pos, rating, club) in _RAW:
        assert pos in POSITIONS, f"bad pos for {name}"
        assert name not in seen, f"duplicate player {name}"
        seen.add(name)
        out.append({
            "id": "p_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:10],
            "name": name,
            "short": short,
            "pos": pos,
            "rating": rating,
            "club": club,
            "price": _derive_price(name, pos, rating),
            "attrs": _derive_attrs(name, pos, rating),
        })
    return out


PLAYERS = _build()
PLAYERS_BY_ID = {p["id"]: p for p in PLAYERS}
PLAYERS_BY_NAME = {p["name"]: p for p in PLAYERS}


def get_pool():
    """All players (list of dicts). Treat as read-only."""
    return PLAYERS


def by_position(pos):
    return [p for p in PLAYERS if p["pos"] == pos]


def get_player(pid):
    return PLAYERS_BY_ID.get(pid)


def position_counts():
    from collections import Counter
    return dict(Counter(p["pos"] for p in PLAYERS))


if __name__ == "__main__":
    # Quick self-report when run directly.
    print(f"{len(PLAYERS)} players")
    print("by position:", position_counts())
    for pos in POSITIONS:
        ps = sorted(by_position(pos), key=lambda p: -p["rating"])
        print(f"\n{pos} ({len(ps)}):")
        for p in ps[:5]:
            a = p["attrs"]
            print(f"  {p['short']:<14} ovr {p['rating']}  ${p['price']:>5.1f}m  "
                  f"att{a['att']} mid{a['mid']} dfn{a['dfn']} pac{a['pac']} gk{a['gk']}")
