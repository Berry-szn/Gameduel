"""
HalfIt — spatial-estimation slicing game for GameRoom.

The server generates a 2D polygon shape with a known "mass" (area × density),
sends it to all clients in a room, then receives each player's straight-line
cut and scores how close they came to the target (equal halves OR target grams).

Why server-authoritative? A cheating client could otherwise always claim a
perfect cut. The server is the source of truth for shape, mass, and score.
"""
import math
import random
from typing import List, Tuple, Dict, Any


# Shape unit: arbitrary "cm" units. Density is g/cm². Mass = area × density.
# Default scene fits inside a 400x300 viewport with some padding.
SCENE_W = 400
SCENE_H = 300
SCENE_CX = SCENE_W / 2
SCENE_CY = SCENE_H / 2

# Shape catalogues per difficulty. Each generator returns:
#   { 'name': str, 'vertices': [(x,y), ...], 'density': float }
# Mass is computed downstream from polygon area × density.

# ---------- POLYGON UTILITIES ----------

def polygon_area(vertices: List[Tuple[float, float]]) -> float:
    """Shoelace formula. Returns absolute area in scene units²."""
    n = len(vertices)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        s += (x1 * y2) - (x2 * y1)
    return abs(s) / 2.0


def slice_polygon(vertices: List[Tuple[float, float]],
                  p1: Tuple[float, float],
                  p2: Tuple[float, float]) -> Tuple[List, List]:
    """Cut a convex-ish polygon with the infinite line through p1→p2.
    Returns (left_polygon_vertices, right_polygon_vertices).
    'Left' = points where the signed cross product is positive.
    Either side may be empty if the line misses the polygon."""
    if len(vertices) < 3:
        return [], []
    # Direction of the cut line
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]

    def side(pt):
        # Positive = left of the line, negative = right, zero = on the line
        return dx * (pt[1] - p1[1]) - dy * (pt[0] - p1[0])

    def intersect(a, b):
        # Intersection of segment a-b with the infinite cut line p1-p2.
        # Parametrise a + t(b - a); solve for t where cross with line direction = 0.
        sa = side(a)
        sb = side(b)
        if abs(sa - sb) < 1e-9:
            return None
        t = sa / (sa - sb)
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    left, right = [], []
    n = len(vertices)
    for i in range(n):
        cur = vertices[i]
        nxt = vertices[(i + 1) % n]
        sc = side(cur)
        sn = side(nxt)
        # Current vertex goes to its side (vertices ON the line go to both)
        if sc >= 0:
            left.append(cur)
        if sc <= 0:
            right.append(cur)
        # If edge crosses the line, add the intersection to both sides
        if (sc > 0 and sn < 0) or (sc < 0 and sn > 0):
            xp = intersect(cur, nxt)
            if xp is not None:
                left.append(xp)
                right.append(xp)
    return left, right


def score_cut(vertices: List[Tuple[float, float]],
              density: float,
              p1: Tuple[float, float],
              p2: Tuple[float, float],
              mode: str,
              target_mass: float = None) -> Dict[str, Any]:
    """Score a cut.

    mode='equal':  goal is to split into two equal halves. Score = grams off
                   (i.e. |smaller_half - larger_half| / 2, since each gram
                   "off" the midpoint costs you on both sides equally —
                   we report the absolute deviation from a perfect 50/50).
    mode='target': goal is for one side to weigh exactly target_mass grams.
                   We pick whichever side is closer to the target and report
                   the grams off.
    """
    left, right = slice_polygon(vertices, p1, p2)
    left_area = polygon_area(left)
    right_area = polygon_area(right)
    left_mass = left_area * density
    right_mass = right_area * density
    total_mass = left_mass + right_mass

    if mode == 'equal':
        ideal = total_mass / 2.0
        # How far off is each side from the perfect midpoint?
        # Both sides are equally "off" by construction (symmetric problem).
        off = abs(left_mass - ideal)
        return {
            'left_mass_g': round(left_mass, 2),
            'right_mass_g': round(right_mass, 2),
            'total_mass_g': round(total_mass, 2),
            'ideal_g': round(ideal, 2),
            'grams_off': round(off, 2),
            'surgical': off <= 0.5
        }
    else:
        # target mode — which side did the player intend? Whichever's closer.
        off_left = abs(left_mass - target_mass)
        off_right = abs(right_mass - target_mass)
        off = min(off_left, off_right)
        chosen = 'left' if off_left <= off_right else 'right'
        return {
            'left_mass_g': round(left_mass, 2),
            'right_mass_g': round(right_mass, 2),
            'total_mass_g': round(total_mass, 2),
            'target_g': target_mass,
            'chosen_side': chosen,
            'chosen_mass_g': round(left_mass if chosen == 'left' else right_mass, 2),
            'grams_off': round(off, 2),
            'surgical': off <= 0.5
        }


# ---------- SHAPE GENERATORS ----------

def _ellipse(cx, cy, rx, ry, n=48, rot=0.0):
    """Generate ellipse vertices in CCW order."""
    cosR, sinR = math.cos(rot), math.sin(rot)
    verts = []
    for i in range(n):
        t = (i / n) * 2 * math.pi
        x = rx * math.cos(t)
        y = ry * math.sin(t)
        # rotate
        xr = x * cosR - y * sinR
        yr = x * sinR + y * cosR
        verts.append((cx + xr, cy + yr))
    return verts


def _banana(cx, cy, length=180, thickness=35, curvature=0.7, n=64):
    """Banana = thick curved arc. Generated as a centerline + offset."""
    verts_top, verts_bot = [], []
    arc_angle = curvature * math.pi   # 0 = straight, ~pi = full half circle
    for i in range(n):
        t = i / (n - 1)
        ang = (t - 0.5) * arc_angle
        # center curve
        cxp = math.sin(ang) * (length / arc_angle) if arc_angle > 0.01 else (t - 0.5) * length
        cyp = -math.cos(ang) * (length / arc_angle) if arc_angle > 0.01 else 0
        # tangent angle for thickness
        tang = ang + math.pi / 2
        # taper at ends
        taper = math.sin(t * math.pi) ** 0.7
        th = thickness * taper
        verts_top.append((cx + cxp + math.cos(tang) * th, cy + cyp + math.sin(tang) * th))
        verts_bot.append((cx + cxp - math.cos(tang) * th, cy + cyp - math.sin(tang) * th))
    return verts_top + list(reversed(verts_bot))


def _blob(cx, cy, base_r=80, harmonics=4, irregularity=0.3, n=72, seed=None):
    """Irregular blob via sum of harmonics on a polar radius."""
    rng = random.Random(seed)
    amps = [rng.uniform(-irregularity, irregularity) * base_r for _ in range(harmonics)]
    phases = [rng.uniform(0, 2 * math.pi) for _ in range(harmonics)]
    verts = []
    for i in range(n):
        t = (i / n) * 2 * math.pi
        r = base_r
        for h in range(harmonics):
            r += amps[h] * math.cos((h + 2) * t + phases[h])
        # Guard against negative radius from extreme harmonics
        r = max(r, base_r * 0.4)
        verts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return verts


def _heart(cx, cy, scale=60, n=64):
    """Parametric heart."""
    verts = []
    for i in range(n):
        t = (i / n) * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        verts.append((cx + (x / 16) * scale, cy + (y / 16) * scale))
    return verts


def _fish(cx, cy, length=160, height=70, n=48):
    """Fish silhouette = ellipse body + triangular tail."""
    # Body ellipse (right-leaning), tail vertex on the left
    verts = []
    for i in range(n):
        t = (i / n) * 2 * math.pi
        x = (length / 2) * math.cos(t)
        y = (height / 2) * math.sin(t)
        # taper the rear (left side, x < 0) to suggest a tail joint
        if x < 0:
            y *= 1.0 - 0.5 * (-x / (length / 2))
        verts.append((cx + x, cy + y))
    # Add the tail triangle as extra vertices on the left
    tail_x = cx - length / 2 - 40
    tail_top = (tail_x, cy - height / 2 - 5)
    tail_bot = (tail_x, cy + height / 2 + 5)
    # Insert tail vertices at the leftmost point of the ellipse
    leftmost_idx = min(range(n), key=lambda i: verts[i][0])
    verts = verts[:leftmost_idx] + [tail_top, tail_bot] + verts[leftmost_idx:]
    return verts


SHAPE_NAMES = {
    'easy': ['apple', 'orange', 'tomato', 'lemon', 'plum', 'peach'],
    'medium': ['banana', 'pear', 'fish', 'mango', 'eggplant', 'avocado'],
    'hard': ['gourd', 'potato', 'rock', 'pepper', 'cucumber', 'beetroot']
}


def generate_shape(difficulty: str = 'easy', seed: int = None) -> Dict[str, Any]:
    """Generate one shape with name, vertices, and density.

    difficulty: easy (symmetric, large), medium (curved), hard (irregular).
    seed: optional, for deterministic replay/testing.
    """
    rng = random.Random(seed)
    name = rng.choice(SHAPE_NAMES.get(difficulty, SHAPE_NAMES['easy']))

    if difficulty == 'easy':
        # Symmetric: ellipse or heart, large size, density 0.8-1.2
        kind = rng.choice(['ellipse', 'ellipse', 'heart'])    # ellipse weighted higher
        if kind == 'ellipse':
            rx = rng.uniform(70, 110)
            ry = rng.uniform(60, 100)
            rot = rng.uniform(-0.3, 0.3)
            verts = _ellipse(SCENE_CX, SCENE_CY, rx, ry, n=48, rot=rot)
        else:
            verts = _heart(SCENE_CX, SCENE_CY, scale=rng.uniform(55, 80))
        density = rng.uniform(0.8, 1.2)
    elif difficulty == 'medium':
        # Curved: banana, fish, pear (squashed asymmetric ellipse)
        kind = rng.choice(['banana', 'fish', 'pear'])
        if kind == 'banana':
            verts = _banana(SCENE_CX, SCENE_CY,
                           length=rng.uniform(160, 200),
                           thickness=rng.uniform(28, 38),
                           curvature=rng.uniform(0.5, 0.9))
        elif kind == 'fish':
            verts = _fish(SCENE_CX, SCENE_CY,
                         length=rng.uniform(140, 180),
                         height=rng.uniform(60, 80))
        else:
            # pear = stretched asymmetric ellipse — fake with thin/thick lobes
            verts = _blob(SCENE_CX, SCENE_CY, base_r=70, harmonics=2,
                         irregularity=0.4, seed=rng.randint(0, 1_000_000))
        density = rng.uniform(0.7, 1.3)
    else:
        # Hard: irregular blobs with multiple harmonics
        verts = _blob(SCENE_CX, SCENE_CY,
                     base_r=rng.uniform(65, 85),
                     harmonics=rng.randint(3, 5),
                     irregularity=rng.uniform(0.25, 0.40),
                     seed=rng.randint(0, 1_000_000))
        density = rng.uniform(0.6, 1.4)

    area = polygon_area(verts)
    mass_g = round(area * density / 100, 0)   # /100 keeps the numbers in the
                                              # 30-300g range we want
    if mass_g < 20:
        mass_g = 20
    return {
        'name': name,
        'difficulty': difficulty,
        'vertices': [(round(v[0], 2), round(v[1], 2)) for v in verts],
        'density_per_unit_area': density / 100,    # store the post-scaling density
        'total_mass_g': float(mass_g),
        'scene': {'w': SCENE_W, 'h': SCENE_H}
    }


def pick_target_mass(total_mass_g: float, difficulty: str,
                     rng: random.Random = None) -> float:
    """Pick a target mass for Mode B (Target Cut).

    Easy   = multiples of 10g, in range [20%, 80%] of total
    Medium = multiples of 5g, in range [15%, 85%] of total
    Hard   = any whole number, in range [10%, 90%] of total
    """
    if rng is None:
        rng = random.Random()
    if difficulty == 'easy':
        lo, hi = total_mass_g * 0.20, total_mass_g * 0.80
        # round to nearest 10
        choices = [v for v in range(10, int(total_mass_g), 10) if lo <= v <= hi]
        if not choices:
            return round(total_mass_g / 2 / 10) * 10
        return float(rng.choice(choices))
    elif difficulty == 'medium':
        lo, hi = total_mass_g * 0.15, total_mass_g * 0.85
        choices = [v for v in range(5, int(total_mass_g), 5) if lo <= v <= hi]
        if not choices:
            return round(total_mass_g / 2 / 5) * 5
        return float(rng.choice(choices))
    else:
        lo, hi = max(5, int(total_mass_g * 0.10)), int(total_mass_g * 0.90)
        if hi <= lo:
            return float(int(total_mass_g / 2))
        return float(rng.randint(lo, hi))
