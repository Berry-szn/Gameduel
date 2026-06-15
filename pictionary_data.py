"""
Pictionary — emoji-rebus guessing game for GameRoom.

The "picture" is an emoji rebus (e.g. "bee + leaf" = believe) plus a category
hint. The answer is a word or short phrase. Answer checking is FORGIVING:
plurals, verb tenses, spacing, accents, punctuation, and minor typos all pass,
so "walk on egg shell" matches "walking on eggshells".

No external dependencies. Unlimited non-repeating play is achieved by shuffling
the bank per match and tracking served indices; when the bank is exhausted the
server reshuffles. The bank is large enough that repeats are rare in a session.
"""
import difflib
import random
import re
import unicodedata
from typing import List, Dict, Any, Tuple


# Each puzzle: (emoji, answer, category, [accepted_alternates])
# category drives the first hint. emoji is the visual. answer is the target.
PUZZLES: List[Tuple[str, str, str, List[str]]] = [
    # --- compound / rebus words ---
    ("🐝🍃", "believe", "word", ["beleive"]),
    ("🌧️🏹", "rainbow", "word", ["rain bow"]),
    ("👁️🍵", "icy", "word", ["i see", "i sea"]),
    ("🐘📞", "elephone", "made-up word", []),
    ("☀️🌻", "sunflower", "plant", []),
    ("🔥🦊", "firefox", "thing", []),
    ("🌙💡", "moonlight", "word", []),
    ("⭐🐟", "starfish", "animal", []),
    ("🦶⚽", "football", "sport", ["soccer"]),
    ("🏀🥅", "basketball", "sport", []),
    ("🌊🏄", "surfing", "activity", ["surf"]),
    ("🐴🏇", "horse racing", "sport", ["horseracing"]),
    ("🍳🍴", "breakfast", "meal", []),
    ("🌽🍿", "popcorn", "food", []),
    ("🥞🥛", "pancakes", "food", ["pancake"]),
    ("🧀🐭", "cheese mouse", "phrase", ["mouse trap", "mousetrap"]),
    ("🐶🏠", "doghouse", "thing", ["dog house"]),
    ("🐦🏠", "birdhouse", "thing", ["bird house"]),
    ("🧱🏠", "brick house", "thing", ["brickhouse"]),
    ("💡🏠", "lighthouse", "building", ["light house"]),
    ("🚪🔔", "doorbell", "thing", ["door bell"]),
    ("🐝🏠", "beehive", "thing", ["bee hive"]),
    ("🦷🪥", "toothbrush", "object", ["tooth brush"]),
    ("👁️🥚", "eggplant", "vegetable", ["egg plant"]),    # eye+egg... loose, keep alternate
    ("🍓💧", "strawberry", "fruit", ["straw berry"]),
    ("🍌🍞", "banana bread", "food", ["bananabread"]),
    ("🦋💉", "butterfly", "insect", ["butter fly"]),
    ("⛄❄️", "snowman", "thing", ["snow man"]),
    ("🌧️🧥", "raincoat", "clothing", ["rain coat"]),
    ("🌧️☂️", "umbrella", "object", []),
    ("🏔️⛷️", "skiing", "sport", ["ski"]),
    ("🕷️🕸️", "spider web", "thing", ["spiderweb", "cobweb"]),
    ("🐢🚀", "slow start", "phrase", []),
    ("🐌📮", "snail mail", "phrase", ["snailmail"]),
    ("👑🐝", "queen bee", "phrase", ["queenbee"]),
    ("🌟🔫", "shooting star", "thing", ["shootingstar"]),
    ("🦁👑", "lion king", "movie-ish", ["the lion king", "lionking"]),
    ("🌍🕊️", "world peace", "phrase", ["worldpeace"]),
    ("💔😢", "heartbreak", "feeling", ["heart break", "broken heart"]),
    ("🧠🌧️", "brainstorm", "word", ["brain storm"]),
    ("🔑🍳", "keyboard", "object", []),
    ("🌭🐶", "hot dog", "food", ["hotdog"]),
    ("🥶🦵", "cold feet", "phrase", ["coldfeet"]),
    ("🍰🥇", "piece of cake", "phrase", ["pieceofcake", "easy"]),
    ("🐱🎒", "cat nap", "phrase", ["catnap"]),
    ("🦷😬", "tooth fairy", "thing", ["toothfairy"]),
    ("⏰🐛", "early bird", "phrase", ["earlybird"]),
    ("🍯🌙", "honeymoon", "thing", ["honey moon"]),
    ("🔴🥕", "red carpet", "thing", ["redcarpet"]),
    ("👻🏠", "haunted house", "thing", ["hauntedhouse"]),
    ("🌶️🔥", "spicy", "taste", ["hot"]),
    ("💰🐷", "piggy bank", "object", ["piggybank"]),
    ("🌊🐎", "seahorse", "animal", ["sea horse"]),
    ("🐯🍞", "tiger bread", "food", []),
    ("🚒👨", "firefighter", "job", ["fire fighter", "fireman"]),
    ("📚🐛", "bookworm", "phrase", ["book worm"]),
    ("🌞🍳", "sunny side up", "phrase", ["sunnyside up", "fried egg"]),
    ("🎣👨", "fisherman", "job", ["fisher man"]),
    ("🏃🥚🥚", "walking on eggshells", "phrase",
        ["walk on eggshells", "walking on egg shells", "walk on egg shell"]),
    ("🌧️🐱🐶", "raining cats and dogs", "phrase",
        ["rain cats and dogs", "raining cats dogs"]),
    ("🔨⏰", "hammer time", "phrase", ["hammertime"]),
    ("🌙🚶", "moonwalk", "dance move", ["moon walk"]),
    ("👀🍬", "eye candy", "phrase", ["eyecandy"]),
    ("🦴🍖", "dog bone", "thing", ["dogbone", "bone"]),
    ("🌊🌊🌊", "tsunami", "thing", ["big wave", "tidal wave"]),
    ("❄️⛷️", "snowboard", "sport", ["snow board"]),
    ("🎂🎉", "birthday", "event", ["birth day"]),
    ("🌃🦉", "night owl", "phrase", ["nightowl"]),
    ("🐔🥚", "chicken and egg", "phrase", ["chicken egg", "which came first"]),
    ("🍋🥤", "lemonade", "drink", ["lemon ade"]),
    ("🌶️🌭", "chili dog", "food", ["chilidog"]),
    ("🕰️✈️", "time flies", "phrase", ["timeflies"]),
    ("🦷🩸", "bloody tooth", "phrase", []),
    ("📦🐈", "cat in the box", "phrase", ["cat box", "litter box"]),
    ("🏖️⚽", "beach ball", "object", ["beachball"]),
    ("👨‍🍳🎩", "chef hat", "object", ["chefs hat", "chef's hat"]),
    ("🐍🪜", "snakes and ladders", "game", ["snake and ladder", "chutes and ladders"]),
    ("🌽🌾", "cornfield", "place", ["corn field"]),
    ("🦅👀", "eagle eye", "phrase", ["eagleeye"]),
    ("🌊🏝️", "desert island", "place", ["deserted island", "island"]),
    ("🎈🏠", "up house", "movie-ish", ["flying house", "balloon house"]),
    ("🔆🕶️", "sunglasses", "object", ["sun glasses", "shades"]),
    ("🧊🧊", "ice cube", "thing", ["icecube", "ice"]),
    ("🚗💨", "fast car", "phrase", ["speeding", "race car", "racecar"]),
    ("🎤⬇️", "mic drop", "phrase", ["micdrop"]),
    ("🐻🦶", "bear foot", "phrase", ["barefoot", "bare foot"]),
    ("🌙🐺", "werewolf", "creature", ["were wolf"]),
    ("☕☕", "coffee break", "phrase", ["coffeebreak", "coffee"]),
    ("🎯💯", "bullseye", "phrase", ["bulls eye", "perfect"]),
    ("🧂🌊", "salt water", "thing", ["saltwater", "sea water"]),
    ("🔥🦅", "phoenix", "creature", ["fire bird"]),
    ("📱🍎", "iphone", "device", ["apple phone"]),
    ("🎨🖌️", "painting", "activity", ["paint", "art"]),
    ("🌻🌻🌻", "garden", "place", ["flower garden", "flowers"]),
    ("🐙🎸", "octopus", "animal", ["8 arms"]),
    ("🌊🦈", "shark attack", "phrase", ["sharkattack", "jaws"]),
    ("🛌💭", "daydream", "word", ["day dream"]),
    ("🔋📉", "low battery", "phrase", ["lowbattery", "dead battery"]),
    ("🍀🤞", "good luck", "phrase", ["goodluck", "lucky"]),
    ("🐎🏠", "stable", "place", ["horse stable", "barn"]),
    ("🌡️📈", "heat wave", "phrase", ["heatwave", "hot weather"]),
    ("🪞🪞", "mirror image", "phrase", ["mirrorimage", "reflection"]),
    # --- extra hard-tier phrases (3+ words) so Hard mode has depth ---
    ("🐦✋✋", "bird in the hand", "phrase", ["a bird in the hand", "bird in hand"]),
    ("🌧️☀️🌈", "after the rain", "phrase", ["after rain comes sun"]),
    ("🔥🍳🥘", "out of the frying pan", "phrase", ["out of the frying pan into the fire"]),
    ("⏰💰", "time is money", "phrase", ["time is gold"]),
    ("🐱👅🤐", "cat got your tongue", "phrase", ["cat got my tongue"]),
    ("🧊🔝⛰️", "tip of the iceberg", "phrase", ["just the tip of the iceberg"]),
    ("🎵😀💔", "sing a sad song", "phrase", []),
    ("🍞🧈🫳", "bread and butter", "phrase", ["my bread and butter"]),
    ("🌙1️⃣6️⃣", "once in a blue moon", "phrase", ["blue moon"]),
    ("🐘🚪", "elephant in the room", "phrase", ["the elephant in the room"]),
    ("🔨🗣️", "hit the nail on the head", "phrase", ["nail on the head"]),
    ("🐎🍔", "hold your horses", "phrase", ["hold the horses"]),
    ("🧂👀", "take it with a grain of salt", "phrase", ["grain of salt", "pinch of salt"]),
    ("🌳🍎📉", "apple of my eye", "phrase", ["the apple of my eye"]),
    ("🐦🐦💎", "two birds one stone", "phrase", ["kill two birds with one stone", "two birds with one stone"]),
]


# ---------- ANSWER MATCHING (forgiving) ----------

def normalize_answer(s: str) -> str:
    """Lowercase, strip accents, remove punctuation, collapse whitespace."""
    s = (s or "").lower().strip()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _stem_word(w: str) -> str:
    """Strip common plural/tense suffixes so walking->walk, eggshells->eggshell."""
    for suf in ('ing', 'ed', 'es', 's'):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _stem_phrase(s: str) -> str:
    return " ".join(_stem_word(w) for w in s.split())


def check_answer(guess: str, answer: str, accept_list: List[str] = None) -> bool:
    """Forgiving comparison. Returns True if guess is acceptably close.

    Layers, in order:
      1. exact (after normalization)
      2. stemmed equality (plurals/tenses)
      3. fuzzy ratio (adaptive threshold; short words tolerate one typo)
      4. stemmed fuzzy
    """
    g = normalize_answer(guess)
    if not g:
        return False
    candidates = [normalize_answer(answer)]
    if accept_list:
        candidates += [normalize_answer(a) for a in accept_list]
    for cand in candidates:
        if not cand:
            continue
        if g == cand:
            return True
        if _stem_phrase(g) == _stem_phrase(cand):
            return True
        longest = max(len(g), len(cand))
        thresh = 0.82 if longest <= 8 else 0.88
        if difflib.SequenceMatcher(None, g, cand).ratio() >= thresh:
            return True
        if difflib.SequenceMatcher(None, _stem_phrase(g), _stem_phrase(cand)).ratio() >= max(thresh, 0.85):
            return True
    return False


# ---------- HINTS ----------

def build_hints(answer: str, category: str) -> List[str]:
    """Three progressive hints for a puzzle.
      hint 1 = category + number of words + letter counts
      hint 2 = first letter of each word
      hint 3 = first half of the answer revealed (letters), rest as underscores
    """
    words = answer.split()
    lengths = " ".join(str(len(w)) for w in words)
    hint1 = f"Category: {category} · {len(words)} word{'s' if len(words) != 1 else ''} ({lengths} letters)"
    hint2 = "Starts with: " + " ".join(w[0].upper() for w in words)
    # Reveal first ~half of each word
    revealed = []
    for w in words:
        keep = max(1, len(w) // 2)
        revealed.append(w[:keep] + "·" * (len(w) - keep))
    hint3 = "Pattern: " + " ".join(revealed)
    return [hint1, hint2, hint3]


# ---------- PUZZLE SERVING ----------

def puzzle_difficulty(answer: str) -> str:
    """Derive a difficulty tier from the answer.
      easy   = single word
      medium = two words
      hard   = three or more words (full phrases / idioms)
    """
    n = len(answer.split())
    if n <= 1:
        return 'easy'
    if n == 2:
        return 'medium'
    return 'hard'


def _indices_for_difficulty(difficulty: str) -> List[int]:
    """Bank indices whose puzzles match the requested difficulty.
    'mixed' (or unknown) returns everything."""
    if difficulty not in ('easy', 'medium', 'hard'):
        return list(range(len(PUZZLES)))
    out = []
    for i, (emoji, answer, cat, alt) in enumerate(PUZZLES):
        if puzzle_difficulty(answer) == difficulty:
            out.append(i)
    # Safety: never return an empty pool
    return out if out else list(range(len(PUZZLES)))


def make_shuffled_order(seed: int = None, difficulty: str = 'mixed') -> List[int]:
    """Return a shuffled list of puzzle indices for non-repeating play.
    Filtered to the requested difficulty tier (or all if 'mixed')."""
    rng = random.Random(seed)
    order = _indices_for_difficulty(difficulty)
    rng.shuffle(order)
    return order


def get_puzzle(index: int) -> Dict[str, Any]:
    """Return puzzle data for a given bank index (caller manages the order)."""
    emoji, answer, category, alternates = PUZZLES[index % len(PUZZLES)]
    return {
        'emoji': emoji,
        'answer': answer,
        'category': category,
        'alternates': alternates,
        'hints': build_hints(answer, category),
        'word_count': len(answer.split()),
    }


PUZZLE_COUNT = len(PUZZLES)
_BUILTIN_PUZZLE_COUNT = len(PUZZLES)


def refresh_admin_content():
    """Re-sync PUZZLES = builtin + current admin items. Safe to call often."""
    global PUZZLES, PUZZLE_COUNT
    try:
        import admin_content
        builtin = PUZZLES[:_BUILTIN_PUZZLE_COUNT]
        PUZZLES = admin_content.merged_pictionary(builtin)
        PUZZLE_COUNT = len(PUZZLES)
    except Exception as e:
        print(f"[pictionary] refresh_admin_content failed: {e}")
