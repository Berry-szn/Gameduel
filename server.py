"""
GameRoom server (online edition).

Multi-room architecture. Each game lives in its own room with a short code.
Players join via /r/<code>. Rooms are cleaned up when nobody has been
connected for 30 minutes.

Group variants supported:
  - chain        : current chain elimination
  - pick_target  : each round players choose who they attack
  - bracket      : 4 or 8 player single elimination tournament
  - koth         : king of the hill, first to X round wins

Run locally (dev):
    pip install -r requirements.txt
    python server.py

Production (Render uses this):
    gunicorn -k eventlet -w 1 server:app --bind 0.0.0.0:$PORT
"""

# IMPORTANT: eventlet.monkey_patch() MUST run before any other imports that
# touch sockets, threads, or time — otherwise eventlet can't replace them
# with its cooperative versions and the server will block on first request.
# In dev (when EVENTLET_DISABLE=1) we skip patching and run threaded.
import os
if os.environ.get('EVENTLET_DISABLE') != '1':
    try:
        import eventlet
        eventlet.monkey_patch()
        _ASYNC_MODE = 'eventlet'
    except ImportError:
        _ASYNC_MODE = 'threading'
else:
    _ASYNC_MODE = 'threading'

import hashlib
import json
import random
import socket
import string
import threading
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import storage as _storage

from flask import Flask, jsonify, render_template, request, make_response
from flask_socketio import SocketIO, emit, join_room as sio_join_room, leave_room as sio_leave_room


app = Flask(__name__)
app.config['SECRET_KEY'] = 'guessduel-server-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=_ASYNC_MODE)
print(f"[boot] socketio async_mode={_ASYNC_MODE}")


# =========================================================================
# WORDLIST (for WordChain)
# =========================================================================

WORDLIST: set = set()
WORDLIST_BY_LETTER: Dict[str, List[str]] = {}     # letter -> list of words starting with it
RARE_LETTERS = ['j', 'k', 'q', 'v', 'x', 'y', 'z']
COMMON_LETTERS = list('abcdefghilmnoprstuw')


def load_wordlist():
    global WORDLIST, WORDLIST_BY_LETTER
    try:
        from english_words import get_english_words_set
        raw = get_english_words_set(['web2'], lower=True)
    except Exception as e:
        print(f"[wordlist] english_words not available ({e}); WordChain disabled")
        return
    # Keep only alphabetic words length 3-15. Drop very obscure long ones for sanity.
    WORDLIST = {w for w in raw if w.isalpha() and 3 <= len(w) <= 15}
    by_letter: Dict[str, List[str]] = {c: [] for c in string.ascii_lowercase}
    for w in WORDLIST:
        by_letter[w[0]].append(w)
    WORDLIST_BY_LETTER = by_letter
    print(f"[wordlist] loaded {len(WORDLIST)} words")


def pick_letter_for_round(difficulty: str, round_number: int) -> str:
    """Easy/Medium use mostly common letters with occasional rare.
       Hard biases toward rare letters."""
    if difficulty == 'hard':
        # 50% rare, 50% common
        if random.random() < 0.5:
            return random.choice(RARE_LETTERS)
        return random.choice(COMMON_LETTERS)
    elif difficulty == 'medium':
        # 15% rare, 85% common
        if random.random() < 0.15:
            return random.choice(RARE_LETTERS)
        return random.choice(COMMON_LETTERS)
    else:
        # easy: 5% rare, 95% common
        if random.random() < 0.05:
            return random.choice(RARE_LETTERS)
        return random.choice(COMMON_LETTERS)


def wordchain_min_length(difficulty: str, round_number: int) -> int:
    """Round 1 length depends on difficulty, +1 each round."""
    base = {'easy': 3, 'medium': 4, 'hard': 5}.get(difficulty, 3)
    return base + (round_number - 1)


def validate_wordchain_submission(word: str, letter: str, min_length: int,
                                   used_words: set) -> Optional[str]:
    w = (word or '').strip().lower()
    if not w or not w.isalpha():
        return 'Letters only, no spaces'
    if not w.startswith(letter.lower()):
        return f'Word must start with "{letter.upper()}"'
    if len(w) < min_length:
        return f'Word must be at least {min_length} letters'
    if w in used_words:
        return 'That word was already used'
    if w not in WORDLIST:
        return f'"{w}" is not in the dictionary'
    return None  # valid


def bot_wordchain_word(letter: str, min_length: int, used_words: set,
                       difficulty: str) -> Optional[str]:
    """Pick a word for the bot. Bot may fail in easy/medium to give humans a chance."""
    candidates = WORDLIST_BY_LETTER.get(letter, [])
    valid = [w for w in candidates if len(w) >= min_length and w not in used_words]
    if not valid:
        return None
    # Bot difficulty: easy gives bot ~20% chance of failing
    if difficulty == 'easy' and random.random() < 0.2:
        return None
    if difficulty == 'medium' and random.random() < 0.05:
        return None
    return random.choice(valid)


# =========================================================================
# PROFILE PERSISTENCE
# =========================================================================
# Profiles are stored in a single JSON file, keyed by lowercased name.
# Same name on different devices = same profile. Name collisions across
# the wider internet are a known limitation; real accounts come later.

PROFILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profiles.json')
PROFILES_LOCK = threading.Lock()
PROFILES_CACHE: Dict[str, dict] = {}
PROFILES_DIRTY = False


def profile_key(name: str) -> str:
    return (name or '').strip().lower()


def fresh_profile(name: str) -> dict:
    return {
        'name': name,
        'created_at': time.time(),
        'xp': 0,
        'level': 1,
        'coins': 0,                 # earned from wins; spend in future cosmetic shop
        'games_played': 0,
        'wins': 0,
        'losses': 0,
        'cracks': 0,                # total successful cracks lifetime
        'fastest_crack': None,      # fewest guesses to a single crack
        'current_streak': 0,
        'best_streak': 0,
        'achievements': [],
        'daily_completed': {},      # date_str -> {guesses, time_sec, secret, won}
        'last_played_at': None,
        'xp_by_game': {},           # 'guessduel': 320, 'wordchain': 180 ...
        'email': None,              # set when signed in with Google
        'auth_provider': None       # 'google' for signed-in users, else None
    }


# Title progression — overall rank, gets harder as level rises
LEVEL_TITLES = [
    (1,  'Newcomer'),
    (2,  'Rookie'),
    (3,  'Player'),
    (4,  'Regular'),
    (5,  'Sharp'),
    (6,  'Tactician'),
    (7,  'Strategist'),
    (8,  'Veteran'),
    (9,  'Champion'),
    (10, 'Elite'),
    (12, 'Master'),
    (15, 'Grandmaster'),
    (18, 'Legend'),
    (22, 'Mythic'),
    (28, 'Apex'),
]


def title_for_level(level: int) -> str:
    """Return the current title for a given level (highest threshold met)."""
    title = 'Newcomer'
    for threshold, t in LEVEL_TITLES:
        if level >= threshold:
            title = t
    return title


def load_profiles():
    global PROFILES_CACHE
    try:
        PROFILES_CACHE = _storage.load_profiles() or {}
        print(f"[profiles] loaded {len(PROFILES_CACHE)} profiles from {_storage.backend_name()}")
    except Exception as e:
        print(f"[profiles] Failed to load: {e}. Starting fresh.")
        PROFILES_CACHE = {}


def save_profiles():
    global PROFILES_DIRTY
    with PROFILES_LOCK:
        snapshot = dict(PROFILES_CACHE)
    try:
        _storage.save_profiles(snapshot)
        PROFILES_DIRTY = False
    except Exception as e:
        print(f"[profiles] Failed to save: {e}")


def get_profile(name: str, user_id: str = None) -> dict:
    """Look up or create the player's profile.

    Keys: prefer user_id (so two players with the same display name have
    separate progress). Fall back to lowercased name for legacy and HTTP
    contexts that only have a name. Migrates a name-keyed profile to a
    user_id key the first time we see the user_id for that name.
    """
    with PROFILES_LOCK:
        if user_id and user_id.startswith(('u_', 'g_')):
            uid_key = user_id
            if uid_key in PROFILES_CACHE:
                p = PROFILES_CACHE[uid_key]
                # Backfill name (renames write through here)
                if name:
                    p['name'] = name
                # Ensure all default fields exist
                for k, v in fresh_profile(name or p.get('name', '')).items():
                    if k not in p:
                        p[k] = v
                return p
            # No user_id-keyed entry yet — check for a legacy name-keyed one
            name_key = (name or '').strip().lower()
            if name_key and name_key in PROFILES_CACHE:
                # Migrate: move the legacy name-keyed profile to a user_id key
                PROFILES_CACHE[uid_key] = PROFILES_CACHE.pop(name_key)
                PROFILES_CACHE[uid_key]['user_id'] = user_id
                if name:
                    PROFILES_CACHE[uid_key]['name'] = name
                for k, v in fresh_profile(name or '').items():
                    if k not in PROFILES_CACHE[uid_key]:
                        PROFILES_CACHE[uid_key][k] = v
                return PROFILES_CACHE[uid_key]
            # Fresh profile under user_id key
            PROFILES_CACHE[uid_key] = fresh_profile(name or '')
            PROFILES_CACHE[uid_key]['user_id'] = user_id
            return PROFILES_CACHE[uid_key]

        # Legacy / no-user_id path: lowercased name as the key
        key = (name or '').strip().lower()
        if not key:
            return fresh_profile(name or '')
        if key not in PROFILES_CACHE:
            PROFILES_CACHE[key] = fresh_profile(name)
        for k, v in fresh_profile(name).items():
            if k not in PROFILES_CACHE[key]:
                PROFILES_CACHE[key][k] = v
        return PROFILES_CACHE[key]


def mark_profiles_dirty():
    global PROFILES_DIRTY
    PROFILES_DIRTY = True


def record_forfeit_loss(name: str, user_id: str = None):
    """Increment losses + games_played on the forfeiter's profile and reset
    their current win streak. Called by all forfeit paths (solo, 1v1, group)
    so that quitting always counts against you in stats."""
    if not name and not user_id:
        return
    try:
        p = get_profile(name, user_id=user_id)
        p['losses'] = (p.get('losses', 0) or 0) + 1
        p['games_played'] = (p.get('games_played', 0) or 0) + 1
        p['current_streak'] = 0
        mark_profiles_dirty()
    except Exception as e:
        print(f"[record_forfeit_loss] failed for {name}: {e}")


def xp_for_level(level: int) -> int:
    """Cumulative XP required to *reach* `level`.

    Curve is gentle for the first few levels (so new players feel progress
    quickly) then ramps hard — high levels are a real status grind.

      L1: 0       L2: 100      L3: 300      L4: 700
      L5: 1.5k    L6: 3k       L7: 6k       L8: 12k
      L9: 24k     L10: 50k     L11: 100k    L12: 200k
      L13: 400k   L14: 800k    L15: 1.5M ...

    Each level past L4 roughly doubles the requirement.
    """
    if level <= 1:
        return 0
    table = {2: 100, 3: 300, 4: 700, 5: 1500, 6: 3000, 7: 6000, 8: 12000,
             9: 24000, 10: 50000, 11: 100000, 12: 200000, 13: 400000,
             14: 800000, 15: 1500000}
    if level in table:
        return table[level]
    # Beyond 15: ~1.8x per level
    base = 1500000
    for L in range(16, level + 1):
        base = int(base * 1.8)
    return base


def level_for_xp(xp: int) -> int:
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
        if level > 100: break
    return level


def grant_xp(profile: dict, amount: int, game_type: str = None,
             coins: int = 0) -> dict:
    """Award XP (and optionally coins) to a profile.

    Returns a payload the client can use to render a 'You earned 50 XP'
    style banner plus a level-up celebration if applicable.
    """
    old_level = profile['level']
    old_title = title_for_level(old_level)
    profile['xp'] = (profile.get('xp', 0) or 0) + amount
    if game_type:
        by_game = profile.setdefault('xp_by_game', {})
        by_game[game_type] = (by_game.get(game_type, 0) or 0) + amount
    if coins:
        profile['coins'] = (profile.get('coins', 0) or 0) + coins
    new_level = level_for_xp(profile['xp'])
    profile['level'] = new_level
    new_title = title_for_level(new_level)
    mark_profiles_dirty()
    return {
        'gained': amount,
        'coins_gained': coins,
        'coins_total': profile.get('coins', 0),
        'old_level': old_level,
        'new_level': new_level,
        'leveled_up': new_level > old_level,
        'title_changed': new_title != old_title,
        'old_title': old_title,
        'new_title': new_title,
        'xp_total': profile['xp'],
        'xp_for_current': xp_for_level(new_level),
        'xp_for_next': xp_for_level(new_level + 1)
    }


# =========================================================================
# ACHIEVEMENTS
# =========================================================================

ACHIEVEMENTS = {
    'first_blood':       {'name': 'First Blood',         'desc': 'Win your first game',                       'icon': '🩸'},
    'sharpshooter':      {'name': 'Sharpshooter',        'desc': 'Crack an opponent in under 4 guesses',      'icon': '🎯'},
    'speed_demon':       {'name': 'Speed Demon',         'desc': 'Win in under 3 guesses total',              'icon': '⚡'},
    'streak_starter':    {'name': 'Streak Starter',      'desc': 'Win 3 games in a row',                      'icon': '🔥'},
    'on_fire':           {'name': 'On Fire',             'desc': 'Win 5 games in a row',                      'icon': '🔥🔥'},
    'unstoppable':       {'name': 'Unstoppable',         'desc': 'Win 10 games in a row',                     'icon': '👑'},
    'veteran':           {'name': 'Veteran',             'desc': 'Play 25 games',                             'icon': '🎖️'},
    'centurion':         {'name': 'Centurion',           'desc': 'Play 100 games',                            'icon': '💯'},
    'cracksman':         {'name': 'Cracksman',           'desc': 'Crack 50 opponents lifetime',               'icon': '🔨'},
    'bot_slayer':        {'name': 'Bot Slayer',          'desc': 'Beat the hard computer',                    'icon': '🤖'},
    'chain_breaker':     {'name': 'Chain Breaker',       'desc': 'Win a chain elimination game',              'icon': '⛓️'},
    'strategist':        {'name': 'Strategist',          'desc': 'Win a pick-your-target game',               'icon': '🎯'},
    'tournament_king':   {'name': 'Tournament King',     'desc': 'Win a bracket tournament',                  'icon': '🏆'},
    'long_live_king':    {'name': 'Long Live the King',  'desc': 'Win a king-of-the-hill game',               'icon': '♛'},
    'daily_visitor':     {'name': 'Daily Visitor',       'desc': 'Complete a daily challenge',                'icon': '📅'},
    'daily_streak_3':    {'name': 'Three Day Habit',     'desc': 'Daily challenge 3 days in a row',           'icon': '📅'},
    'daily_streak_7':    {'name': 'Weekly Ritual',       'desc': 'Daily challenge 7 days in a row',           'icon': '🗓️'},
    'comeback':          {'name': 'Comeback Kid',        'desc': 'Win a series after losing the first match', 'icon': '↩️'}
}


def award_achievement(profile: dict, ach_id: str, sid: Optional[str] = None) -> bool:
    """Returns True if newly awarded."""
    if ach_id not in ACHIEVEMENTS:
        return False
    if ach_id in profile['achievements']:
        return False
    profile['achievements'].append(ach_id)
    mark_profiles_dirty()
    if sid:
        ach = ACHIEVEMENTS[ach_id]
        socketio.emit('achievement_unlocked', {
            'id': ach_id, 'name': ach['name'], 'desc': ach['desc'], 'icon': ach['icon']
        }, room=sid)
    return True


def check_post_game_achievements(profile: dict, sid: str, context: dict):
    """context: {won, mode, group_variant, total_guesses, opponent_was_hard_bot, series_came_back}"""
    if context.get('won'):
        if profile['wins'] == 1:
            award_achievement(profile, 'first_blood', sid)
        if context.get('total_guesses') is not None and context['total_guesses'] < 3:
            award_achievement(profile, 'speed_demon', sid)
        if profile['current_streak'] >= 3:
            award_achievement(profile, 'streak_starter', sid)
        if profile['current_streak'] >= 5:
            award_achievement(profile, 'on_fire', sid)
        if profile['current_streak'] >= 10:
            award_achievement(profile, 'unstoppable', sid)
        if context.get('opponent_was_hard_bot'):
            award_achievement(profile, 'bot_slayer', sid)
        if context.get('mode') == 'group':
            gv = context.get('group_variant')
            if gv == 'chain':   award_achievement(profile, 'chain_breaker',   sid)
            if gv == 'pick_target': award_achievement(profile, 'strategist',  sid)
            if gv == 'bracket': award_achievement(profile, 'tournament_king', sid)
            if gv == 'koth':    award_achievement(profile, 'long_live_king',  sid)
        if context.get('series_came_back'):
            award_achievement(profile, 'comeback', sid)
    if profile['games_played'] >= 25:
        award_achievement(profile, 'veteran', sid)
    if profile['games_played'] >= 100:
        award_achievement(profile, 'centurion', sid)
    if profile['cracks'] >= 50:
        award_achievement(profile, 'cracksman', sid)


# =========================================================================
# DAILY CHALLENGE
# =========================================================================

def today_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def daily_secret_for(date_str: str) -> dict:
    """Deterministic secret for a given date. Everyone gets the same target.
       Range 1-100 keeps the puzzle solvable in 6 guesses with smart play."""
    seed = int(hashlib.sha256(date_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return {
        'date': date_str,
        'secret': rng.randint(1, 100),
        'range_min': 1,
        'range_max': 100
    }


# =========================================================================
# ROOM REGISTRY
# =========================================================================

ROOMS: Dict[str, Dict[str, Any]] = {}     # code -> room dict
ROOMS_DICT_LOCK = threading.Lock()         # only for adding/removing rooms
SID_TO_ROOM: Dict[str, str] = {}           # socket id -> room code
SID_TO_ROOM_LOCK = threading.Lock()

# Stable browser identity. Survives SID changes from reconnects. Foundation
# for online presence / direct challenges (Turn 3).
SID_TO_USER: Dict[str, dict] = {}          # sid -> {user_id, name, status, game}
SID_TO_USER_LOCK = threading.Lock()

# Reverse lookup for direct-challenge: stable user_id -> latest connected sid
USER_TO_SID: Dict[str, str] = {}
# Active pending challenges: challenge_id -> {from_user, from_name, to_user, game, mode, created_at, room_code?}
PENDING_CHALLENGES: Dict[str, dict] = {}
CHALLENGE_LOCK = threading.Lock()
CHALLENGE_TTL = 30   # seconds before a challenge auto-expires


def get_user_status(sid: str) -> dict:
    """Best-effort: figure out what this user is currently doing."""
    with SID_TO_ROOM_LOCK:
        room_code = SID_TO_ROOM.get(sid)
    if not room_code:
        return {'status': 'idle', 'game': None}
    room = ROOMS.get(room_code)
    if not room:
        return {'status': 'idle', 'game': None}
    state = room['state']
    hint = state.get('mode_hint', 'group')
    phase = state.get('phase', 'lobby')
    game = state.get('game_type', 'guessduel')
    if hint == 'solo':
        return {'status': 'in_solo', 'game': game}
    if phase == 'lobby' or phase == 'wc_lobby':
        return {'status': 'in_lobby', 'game': game}
    if hint == 'faceoff':
        return {'status': 'in_1v1', 'game': game}
    return {'status': 'in_group', 'game': game}


def broadcast_presence_change():
    """Notify all connected clients that the online list changed."""
    socketio.emit('presence_update', {'count': len(SID_TO_USER)})

ROOM_CODE_ALPHABET = string.ascii_uppercase + string.digits
ROOM_CODE_LENGTH = 6
ROOM_INACTIVITY_TTL = 30 * 60   # 30 minutes


def fresh_game_state() -> dict:
    """Brand-new game state inside a room."""
    return {
        'game_type': 'guessduel',     # 'guessduel' | 'wordchain'
        'phase': 'lobby',
        # phases for guessduel: lobby, cointoss, setup, secrets, pick_target, playing,
        # round_end, match_end, bracket_match_end, koth_round_end, bracket_intro, game_over
        # phases for wordchain: lobby, wc_round_intro, wc_playing, wc_round_end, wc_eliminated, game_over

        'players': {},
        'sidelined': {},
        'chain': [],

        'settings': {
            'mode': 'group',
            'group_variant': 'chain',
            'difficulty': 'easy',
            'range_min': 1,
            'range_max': 1000,
            'turn_timer': 20,
            'first_to': 1,
            'bot_difficulty': 'medium',
            'bracket_size': 4,
            'koth_target': 3,
            # WordChain settings
            'wc_turn_timer': 30,
            'wc_difficulty': 'easy'
        },

        'current_turn_sid': None,
        'turn_started_at': None,
        'host_sid': None,
        'round_number': 0,
        'winner_sid': None,

        'series': {'active': False, 'target': 1, 'match_number': 0, 'scores': {}},

        'paused': False,
        'paused_at': None,
        'paused_by_sid': None,
        'pause_total_elapsed': 0.0,

        'activity': [],
        'leaderboard': {},

        'bracket': None,
        'koth': None,
        'match_history': [],
        'last_start_args': None,
        'last_round_crackers': [],

        # WordChain state
        'wordchain': None
    }


def fresh_wordchain_state() -> dict:
    return {
        'letter': '',
        'min_length': 3,
        'round_number': 0,
        'used_words': [],          # ordered list of {word, name, sid}
        'turn_order': [],          # list of sids in turn order
        'current_idx': 0,
        'last_word': None,
        'last_word_by': None,
        'difficulty': 'easy'
    }


def gen_room_code(length: int = None) -> str:
    """Generate a unique room code. Default length is 6 (group play);
    face-off uses 4 chars to be visually distinct and easier to share."""
    if length is None:
        length = ROOM_CODE_LENGTH
    while True:
        code = ''.join(random.choices(ROOM_CODE_ALPHABET, k=length))
        # Avoid ambiguous chars at generation time
        if any(c in code for c in '0O1IL'):
            continue
        with ROOMS_DICT_LOCK:
            if code not in ROOMS:
                return code


def create_room(game_type: str = 'guessduel', mode_hint: str = 'group') -> str:
    """Create a fresh room and return its code.
       mode_hint='faceoff' produces a 4-char code; 'group' produces a 6-char code.
       The hint is purely visual — the room itself supports any mode."""
    length = 4 if mode_hint == 'faceoff' else ROOM_CODE_LENGTH
    code = gen_room_code(length)
    initial_state = fresh_game_state()
    initial_state['game_type'] = game_type
    initial_state['mode_hint'] = mode_hint     # used to build the invite URL
    with ROOMS_DICT_LOCK:
        ROOMS[code] = {
            'code': code,
            'state': initial_state,
            'lock': threading.Lock(),
            'last_activity_at': time.time(),
            'created_at': time.time()
        }
    return code


def get_room(code: str) -> Optional[dict]:
    if not code:
        return None
    with ROOMS_DICT_LOCK:
        return ROOMS.get(code)


def delete_room(code: str):
    with ROOMS_DICT_LOCK:
        ROOMS.pop(code, None)


def touch_room(room: dict):
    room['last_activity_at'] = time.time()


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# =========================================================================
# UTILITIES (operate on a passed-in state)
# =========================================================================

def validate_number(value, settings: dict) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < settings['range_min'] or num > settings['range_max']:
        return None
    if settings['difficulty'] == 'easy':
        if num != int(num):
            return None
        return int(num)
    if settings['difficulty'] in ('medium', 'hard'):
        rounded = round(num, 2)
        if abs(rounded - num) > 1e-6:
            return None
        return rounded
    return None


def add_activity(state: dict, kind: str, **kwargs):
    event = {'kind': kind, 'at': time.time(), **kwargs}
    state['activity'].append(event)
    state['activity'] = state['activity'][-30:]


def public_player_view(state: dict, p: dict) -> dict:
    return {
        'sid': p['sid'],
        'name': p['name'],
        'user_id': p.get('user_id'),
        # Avatar fields are populated on the player record at join time,
        # so we don't acquire PROFILES_LOCK on every state broadcast.
        'avatar_color': p.get('avatar_color'),
        'avatar_image': p.get('avatar_image'),
        'eliminated': p['eliminated'],
        'safe_this_round': p['safe_this_round'],
        'has_secret': p['secret'] is not None,
        'guess_count': len(p['guesses']),
        'disconnected': p.get('disconnected_at') is not None,
        'is_bot': p.get('is_bot', False),
        'is_spectator': p.get('is_spectator', False),
        'series_wins': state['series']['scores'].get(p['sid'], 0),
        'pick_locked': p.get('pick_locked', False),
        'picked_target_sid': p.get('picked_target_sid'),
        'koth_score': (state['koth']['scores'].get(p['sid'], 0)
                       if state.get('koth') else 0),
        'stats': p.get('stats', {})
    }


def active_players(state: dict) -> List[dict]:
    return [p for p in state['players'].values() if not p['eliminated']]


def in_round_players(state: dict) -> List[dict]:
    return [p for p in active_players(state) if not p['safe_this_round']]


def fresh_player(sid: str, name: str, user_id: str = None) -> dict:
    return {
        'sid': sid, 'name': name, 'user_id': user_id,
        'secret': None, 'target_sid': None,
        'guesses': [], 'eliminated': False, 'safe_this_round': False,
        'disconnected_at': None,
        'pick_locked': False, 'picked_target_sid': None,
        'koth_guesses_used': 0,
        'is_spectator': False,
        'stats': {
            'cracks': 0,
            'first_try_cracks': 0,
            'forfeits': 0,
            'rounds_survived': 0,
            'guess_count': 0,
            'consecutive_round_cracks': 0,
            'best_consecutive_cracks': 0,
            'closest_miss': None,
            'closest_miss_value': None
        }
    }


def real_players(state: dict) -> List[dict]:
    """Players who are participating (not spectators)."""
    return [p for p in state['players'].values() if not p.get('is_spectator')]


def build_state_snapshot(state: dict, code: str, for_sid: str) -> dict:
    me = state['players'].get(for_sid)
    target_name = None
    if me and me['target_sid'] and me['target_sid'] in state['players']:
        target_name = state['players'][me['target_sid']]['name']

    if not me and for_sid in state['sidelined']:
        sidelined = state['sidelined'][for_sid]
        solo_player = next((p for p in state['players'].values()
                            if not p.get('is_bot')), None)
        return {
            'room_code': code,
            'phase': 'sidelined',
            'sidelined_by': solo_player['name'] if solo_player else 'Someone',
            'me': {'sid': for_sid, 'name': sidelined['name'], 'is_sidelined': True},
            'leaderboard': sorted(
                [{'name': n, **stats} for n, stats in state['leaderboard'].items()],
                key=lambda x: (-x['wins'], x['games'])
            )
        }

    snapshot = {
        'room_code': code,
        'game_type': state.get('game_type', 'guessduel'),
        'mode_hint': state.get('mode_hint', 'group'),
        'phase': state['phase'],
        'settings': state['settings'],
        'round_number': state['round_number'],
        'host_sid': state['host_sid'],
        'current_turn_sid': state['current_turn_sid'],
        'turn_started_at': state['turn_started_at'],
        'chain': state['chain'],
        'players': [public_player_view(state, p) for p in state['players'].values()],
        'activity': state['activity'][-12:],
        'winner_sid': state['winner_sid'],
        'series': {
            'active': state['series']['active'],
            'target': state['series']['target'],
            'match_number': state['series']['match_number'],
            'scores': dict(state['series']['scores'])
        },
        'pause': {
            'paused': state['paused'],
            'paused_at': state['paused_at'],
            'paused_by_sid': state['paused_by_sid'],
            'paused_by_name': (state['players'][state['paused_by_sid']]['name']
                               if state['paused'] and state['paused_by_sid'] in state['players']
                               else None)
        },
        'leaderboard': sorted(
            [{'name': n, **stats} for n, stats in state['leaderboard'].items()],
            key=lambda x: (-x['wins'], x['games'])
        ),
        'bracket': state.get('bracket'),
        'koth': state.get('koth'),
        'wordchain': state.get('wordchain'),
        'timeshot': state.get('timeshot'),
        'geo': state.get('geo'),
        'halfit': state.get('halfit'),
        'angle': state.get('angle'),
        'pict': pict_public_state(state.get('pict')) if state.get('pict') else None,
        'trivia': trivia_public_state(state.get('trivia'), state['phase']) if state.get('trivia') else None,
        'footy': footy_public_state(state.get('footy'), state['phase']) if state.get('footy') else None,
        'football_mp': fbmp_public_state(state.get('football_mp')) if state.get('football_mp') else None,
        'match_history': state.get('match_history', [])[-10:],
        'me': {
            'sid': for_sid,
            'name': me['name'] if me else None,
            'secret': me['secret'] if me else None,
            'target_sid': me['target_sid'] if me else None,
            'target_name': target_name,
            'picked_target_sid': me.get('picked_target_sid') if me else None,
            'pick_locked': me.get('pick_locked', False) if me else False,
            'guesses': me['guesses'] if me else [],
            'eliminated': me['eliminated'] if me else False,
            'safe_this_round': me['safe_this_round'] if me else False,
            'is_spectator': me.get('is_spectator', False) if me else False,
            'is_host': for_sid == state['host_sid']
        } if me else None
    }
    return snapshot


def broadcast_state(state: dict, code: str):
    """Send each connected human in this room their snapshot."""
    for sid in list(state['players'].keys()):
        if state['players'][sid].get('is_bot'):
            continue
        socketio.emit('state', build_state_snapshot(state, code, sid), room=sid)
    for sid in list(state['sidelined'].keys()):
        socketio.emit('state', build_state_snapshot(state, code, sid), room=sid)


# =========================================================================
# BOT
# =========================================================================

def make_bot(difficulty: str) -> dict:
    return {
        'sid': 'bot_' + str(random.randint(10000, 99999)),
        'name': 'Computer',
        'secret': None,
        'target_sid': None,
        'guesses': [],
        'eliminated': False,
        'safe_this_round': False,
        'disconnected_at': None,
        'is_bot': True,
        'bot_difficulty': difficulty,
        'bot_low': None,
        'bot_high': None,
        'pick_locked': False,
        'picked_target_sid': None,
        'koth_guesses_used': 0
    }


def bot_pick_secret(bot: dict, settings: dict):
    lo, hi = settings['range_min'], settings['range_max']
    if settings['difficulty'] == 'easy':
        bot['secret'] = random.randint(int(lo), int(hi))
    else:
        bot['secret'] = round(random.uniform(lo, hi), 2)


def bot_compute_guess(bot: dict, settings: dict) -> float:
    lo = bot['bot_low'] if bot['bot_low'] is not None else settings['range_min']
    hi = bot['bot_high'] if bot['bot_high'] is not None else settings['range_max']
    if lo > hi:
        lo, hi = settings['range_min'], settings['range_max']
    bd = bot['bot_difficulty']
    if bd == 'easy':
        if random.random() < 0.6:
            choice = random.uniform(lo, hi)
        else:
            mid = (lo + hi) / 2
            spread = (hi - lo) * 0.4
            choice = random.uniform(mid - spread, mid + spread)
    elif bd == 'medium':
        mid = (lo + hi) / 2
        noise = (hi - lo) * 0.25 * (random.random() - 0.5) * 2
        choice = mid + noise
    else:
        choice = (lo + hi) / 2
    choice = max(lo, min(hi, choice))
    if settings['difficulty'] == 'easy':
        choice = int(round(choice))
    else:
        choice = round(choice, 2)
    return choice


def bot_update_bounds(bot: dict, guess: float, feedback: str, settings: dict):
    step = 1 if settings['difficulty'] == 'easy' else 0.01
    if feedback == 'higher':
        new_low = guess + step
        bot['bot_low'] = new_low if bot['bot_low'] is None else max(bot['bot_low'], new_low)
    elif feedback == 'lower':
        new_high = guess - step
        bot['bot_high'] = new_high if bot['bot_high'] is None else min(bot['bot_high'], new_high)


def schedule_bot_turn(room: dict, bot_sid: str):
    state = room['state']
    started_at = state['turn_started_at']

    def bot_thread():
        delay = 1.0 + random.random() * 1.2
        socketio.sleep(delay)
        with room['lock']:
            state = room['state']
            if (state['phase'] != 'playing' or
                state['current_turn_sid'] != bot_sid or
                state['turn_started_at'] != started_at or
                state['paused']):
                return
            bot = state['players'].get(bot_sid)
            if not bot:
                return
            target = state['players'].get(bot['target_sid'])
            if not target or target['secret'] is None:
                return
            guess = bot_compute_guess(bot, state['settings'])
            secret = target['secret']
            if abs(guess - secret) < 1e-9:
                feedback = 'correct'
            elif guess < secret:
                feedback = 'higher'
            else:
                feedback = 'lower'
            bot['guesses'].append({'value': guess, 'feedback': feedback, 'at': time.time()})
            bot_update_bounds(bot, guess, feedback, state['settings'])
            if feedback == 'correct':
                bot['safe_this_round'] = True
                add_activity(state, 'crack', name=bot['name'], target=target['name'])
                socketio.emit('crack', {'name': bot['name'], 'target': target['name']},
                              room=room['code'])
                if state['settings']['mode'] == 'solo':
                    end_match(room, explicit_winner_sid=bot_sid)
                    return
            else:
                add_activity(state, 'guess', name=bot['name'], value=guess, feedback=feedback)
            advance_turn(room, bot_sid)

    socketio.start_background_task(bot_thread)


# =========================================================================
# GAME FLOW - common
# =========================================================================

def start_new_round(room: dict):
    state = room['state']
    state['round_number'] += 1
    state['paused'] = False
    state['paused_at'] = None
    state['paused_by_sid'] = None
    state['pause_total_elapsed'] = 0.0

    for p in state['players'].values():
        if not p['eliminated']:
            p['secret'] = None
            p['target_sid'] = None
            p['guesses'] = []
            p['safe_this_round'] = False
            p['pick_locked'] = False
            p['picked_target_sid'] = None
            if p.get('is_bot'):
                p['bot_low'] = None
                p['bot_high'] = None

    alive = [p['sid'] for p in active_players(state)]
    random.shuffle(alive)
    state['chain'] = alive

    variant = state['settings'].get('group_variant', 'chain')
    is_group = state['settings']['mode'] == 'group'

    # Chain-mode: targets follow the shuffled chain.
    # Pick-target: targets are chosen by players in a 'pick_target' phase.
    # Face-off / solo / others use chain assignment too.
    if not (is_group and variant == 'pick_target'):
        for i, sid in enumerate(alive):
            state['players'][sid]['target_sid'] = alive[(i + 1) % len(alive)]

    # Host selection. In solo mode, the human always wins so they set the rules
    # (the bot has nothing to decide). In multiplayer, it's random.
    if state['settings']['mode'] == 'solo':
        humans_alive = [sid for sid in alive
                        if not state['players'][sid].get('is_bot')]
        state['host_sid'] = humans_alive[0] if humans_alive else random.choice(alive)
    else:
        state['host_sid'] = random.choice(alive)
    host_is_bot = state['players'][state['host_sid']].get('is_bot', False)
    host_name = state['players'][state['host_sid']]['name']

    state['current_turn_sid'] = None
    state['turn_started_at'] = None

    is_series_match_1 = (state['series']['active']
                         and state['series']['match_number'] == 1
                         and state['round_number'] == 1)
    is_first_round_overall = (state['round_number'] == 1 and not state['series']['active'])

    code = room['code']

    if is_series_match_1 or is_first_round_overall:
        state['phase'] = 'cointoss'
        add_activity(state, 'cointoss', winner_name=host_name)
        broadcast_state(state, code)

        def after_cointoss():
            socketio.sleep(3)
            with room['lock']:
                s = room['state']
                if s['phase'] != 'cointoss':
                    return
                if host_is_bot:
                    add_activity(s, 'rules_set_by_bot', host=host_name,
                                 difficulty=s['settings']['difficulty'],
                                 range_min=s['settings']['range_min'],
                                 range_max=s['settings']['range_max'])
                    proceed_to_secrets_phase(room)
                else:
                    s['phase'] = 'setup'
                broadcast_state(s, code)
        socketio.start_background_task(after_cointoss)

    elif state['series']['active'] and state['round_number'] == 1:
        state['phase'] = 'cointoss'
        add_activity(state, 'cointoss', winner_name=host_name)
        broadcast_state(state, code)

        def after_cointoss():
            socketio.sleep(3)
            with room['lock']:
                s = room['state']
                if s['phase'] == 'cointoss':
                    proceed_to_secrets_phase(room)
                    broadcast_state(s, code)
        socketio.start_background_task(after_cointoss)
    else:
        proceed_to_secrets_phase(room)
        add_activity(state, 'round_start', round=state['round_number'])
        broadcast_state(state, code)


def proceed_to_secrets_phase(room: dict):
    state = room['state']
    state['phase'] = 'secrets'
    for p in state['players'].values():
        if p.get('is_bot') and not p['eliminated'] and p['secret'] is None:
            bot_pick_secret(p, state['settings'])


def all_secrets_in(state: dict) -> bool:
    return all(p['secret'] is not None for p in active_players(state))


def begin_pick_target_phase(room: dict):
    """Pick-your-target variant: everyone picks a target before playing."""
    state = room['state']
    state['phase'] = 'pick_target'
    for p in state['players'].values():
        if not p['eliminated']:
            p['pick_locked'] = False
            p['picked_target_sid'] = None
    # Bots auto-pick after a beat.
    code = room['code']
    bot_sids = [p['sid'] for p in state['players'].values()
                if p.get('is_bot') and not p['eliminated']]
    if bot_sids:
        def bot_pick():
            socketio.sleep(1.0 + random.random())
            with room['lock']:
                s = room['state']
                if s['phase'] != 'pick_target':
                    return
                for sid in bot_sids:
                    bot = s['players'].get(sid)
                    if not bot or bot['pick_locked']:
                        continue
                    others = [p['sid'] for p in active_players(s) if p['sid'] != sid]
                    if others:
                        bot['picked_target_sid'] = random.choice(others)
                        bot['pick_locked'] = True
                if all_picks_in(s):
                    apply_picks_and_begin_turns(room)
                broadcast_state(s, code)
        socketio.start_background_task(bot_pick)


def all_picks_in(state: dict) -> bool:
    return all(p['pick_locked'] for p in active_players(state))


def apply_picks_and_begin_turns(room: dict):
    state = room['state']
    for p in active_players(state):
        if p['picked_target_sid'] and p['picked_target_sid'] in state['players']:
            p['target_sid'] = p['picked_target_sid']
        else:
            others = [pp['sid'] for pp in active_players(state) if pp['sid'] != p['sid']]
            p['target_sid'] = random.choice(others) if others else None
    begin_turns(room)


def begin_turns(room: dict):
    state = room['state']
    state['phase'] = 'playing'
    if not state['chain']:
        alive = [p['sid'] for p in active_players(state)]
        random.shuffle(alive)
        state['chain'] = alive
    state['current_turn_sid'] = state['chain'][0]
    state['turn_started_at'] = time.time()
    state['pause_total_elapsed'] = 0.0
    add_activity(state, 'round_play_start', round=state['round_number'])
    broadcast_state(state, room['code'])
    _maybe_start_turn(room, state['current_turn_sid'])


def _maybe_start_turn(room: dict, turn_sid: str):
    start_turn_timer(room, turn_sid)
    p = room['state']['players'].get(turn_sid)
    if p and p.get('is_bot'):
        schedule_bot_turn(room, turn_sid)


def advance_turn(room: dict, after_sid: str):
    state = room['state']
    in_round = in_round_players(state)
    active = active_players(state)
    if len(active) > 2 and len(in_round) <= 1:
        end_round(room)
        return
    if len(active) == 2 and len(in_round) == 0:
        end_round(room)
        return

    chain = state['chain']
    if after_sid not in chain:
        state['current_turn_sid'] = in_round[0]['sid'] if in_round else None
    else:
        idx = chain.index(after_sid)
        for offset in range(1, len(chain) + 1):
            cand_sid = chain[(idx + offset) % len(chain)]
            cand = state['players'].get(cand_sid)
            if cand and not cand['eliminated'] and not cand['safe_this_round']:
                state['current_turn_sid'] = cand_sid
                break

    state['turn_started_at'] = time.time()
    state['pause_total_elapsed'] = 0.0
    broadcast_state(state, room['code'])
    _maybe_start_turn(room, state['current_turn_sid'])


def start_turn_timer(room: dict, turn_sid: str):
    state = room['state']
    timer_sid = turn_sid
    started_at = state['turn_started_at']
    duration = state['settings']['turn_timer']

    def timer_thread():
        while True:
            socketio.sleep(0.25)
            with room['lock']:
                s = room['state']
                if (s['current_turn_sid'] != timer_sid or
                    s['turn_started_at'] != started_at or
                    s['phase'] != 'playing'):
                    return
                if s['paused']:
                    continue
                elapsed = time.time() - s['turn_started_at'] - s['pause_total_elapsed']
                if elapsed >= duration:
                    p = s['players'].get(timer_sid)
                    if p:
                        p['guesses'].append({'value': None, 'feedback': 'forfeit', 'at': time.time()})
                        p.setdefault('stats', {})['forfeits'] = p.get('stats', {}).get('forfeits', 0) + 1
                        add_activity(s, 'forfeit', name=p['name'])
                    advance_turn(room, timer_sid)
                    return

    socketio.start_background_task(timer_thread)


def end_round(room: dict):
    state = room['state']
    in_round = in_round_players(state)
    eliminated_this_round_sids = {p['sid'] for p in in_round}
    for p in in_round:
        p['eliminated'] = True
    eliminated_names = [p['name'] for p in in_round]

    # Per-player round stats: only update those who participated in this round
    double_tap_names = []
    for p in state['players'].values():
        if p.get('is_bot'):
            continue
        stats = p.setdefault('stats', {})
        if p['safe_this_round']:
            # Cracked their target -> survived this round
            stats['rounds_survived'] = stats.get('rounds_survived', 0) + 1
            stats['consecutive_round_cracks'] = stats.get('consecutive_round_cracks', 0) + 1
            best = stats.get('best_consecutive_cracks', 0)
            if stats['consecutive_round_cracks'] > best:
                stats['best_consecutive_cracks'] = stats['consecutive_round_cracks']
            if stats['consecutive_round_cracks'] >= 2:
                double_tap_names.append(p['name'])
        elif p['sid'] in eliminated_this_round_sids:
            # Eliminated this round -> reset streak
            stats['consecutive_round_cracks'] = 0

    if double_tap_names:
        socketio.emit('double_tap', {'names': double_tap_names}, room=room['code'])

    state['phase'] = 'round_end'
    state['current_turn_sid'] = None
    state['turn_started_at'] = None

    reveal = {p['sid']: {
        'name': p['name'], 'secret': p['secret'],
        'guess_count': len(p['guesses']),
        'eliminated_this_round': p in in_round
    } for p in state['players'].values()}
    if eliminated_names:
        add_activity(state, 'eliminated', names=eliminated_names, round=state['round_number'])
    socketio.emit('round_reveal', reveal, room=room['code'])
    broadcast_state(state, room['code'])

    def continue_after_reveal():
        socketio.sleep(6)
        with room['lock']:
            s = room['state']
            if len(active_players(s)) <= 1:
                end_match(room)
            else:
                start_new_round(room)
    socketio.start_background_task(continue_after_reveal)


def end_match(room: dict, explicit_winner_sid: Optional[str] = None):
    state = room['state']
    if explicit_winner_sid and explicit_winner_sid in state['players']:
        winner = state['players'][explicit_winner_sid]
        for p in state['players'].values():
            if p['sid'] != explicit_winner_sid:
                p['eliminated'] = True
    else:
        survivors = active_players(state)
        winner = survivors[0] if survivors else None

    if winner:
        add_activity(state, 'match_won', name=winner['name'],
                     match=state['series']['match_number'] if state['series']['active'] else 1)

    if winner and state['series']['active']:
        sid = winner['sid']
        state['series']['scores'][sid] = state['series']['scores'].get(sid, 0) + 1

    # Bracket mode: advance the bracket
    if state['settings']['mode'] == 'group' and state['settings'].get('group_variant') == 'bracket':
        bracket_match_done(room, winner['sid'] if winner else None)
        return

    target = state['series']['target']
    series_winner_sid = None
    if state['series']['active']:
        for sid, wins in state['series']['scores'].items():
            if wins >= target:
                series_winner_sid = sid
                break

    if not state['series']['active']:
        end_game(room, explicit_winner_sid=winner['sid'] if winner else None)
        return
    if series_winner_sid:
        end_game(room, explicit_winner_sid=series_winner_sid)
        return

    state['phase'] = 'match_end'
    state['current_turn_sid'] = None
    state['turn_started_at'] = None
    state['winner_sid'] = winner['sid'] if winner else None
    broadcast_state(state, room['code'])

    def continue_after_match():
        socketio.sleep(5)
        with room['lock']:
            start_next_match(room)
    socketio.start_background_task(continue_after_match)


def start_next_match(room: dict):
    state = room['state']
    state['series']['match_number'] += 1
    state['round_number'] = 0
    for p in state['players'].values():
        p['eliminated'] = False
        p['safe_this_round'] = False
        p['secret'] = None
        p['target_sid'] = None
        p['guesses'] = []
        if p.get('is_bot'):
            p['bot_low'] = None
            p['bot_high'] = None
    start_new_round(room)


def end_game(room: dict, explicit_winner_sid: Optional[str] = None):
    state = room['state']
    if explicit_winner_sid and explicit_winner_sid in state['players']:
        winner = state['players'][explicit_winner_sid]
    else:
        survivors = active_players(state)
        winner = survivors[0] if survivors else None

    state['phase'] = 'game_over'
    state['winner_sid'] = winner['sid'] if winner else None

    for p in state['players'].values():
        if p.get('is_bot'):
            continue
        name = p['name']
        if name not in state['leaderboard']:
            state['leaderboard'][name] = {'wins': 0, 'games': 0}
        state['leaderboard'][name]['games'] += 1
        if winner and p['sid'] == winner['sid']:
            state['leaderboard'][name]['wins'] += 1

    if winner:
        add_activity(state, 'game_won', name=winner['name'])

    final_secrets = [
        {'name': p['name'], 'secret': p['secret'],
         'is_bot': p.get('is_bot', False), 'sid': p['sid']}
        for p in state['players'].values()
        if p['secret'] is not None
    ]

    # MVP = human player with most cracks this game
    humans = [p for p in state['players'].values() if not p.get('is_bot')]
    mvp = None
    if humans:
        mvp_p = max(humans, key=lambda p: p.get('stats', {}).get('cracks', 0))
        if mvp_p.get('stats', {}).get('cracks', 0) > 0:
            mvp = {'name': mvp_p['name'], 'sid': mvp_p['sid'],
                   'cracks': mvp_p['stats']['cracks']}

    # Per-player stats summary
    player_stats = []
    for p in humans:
        s = p.get('stats', {})
        guess_count = s.get('guess_count', 0)
        forfeits = s.get('forfeits', 0)
        useful = guess_count - forfeits
        accuracy = (useful / guess_count * 100) if guess_count > 0 else 100
        player_stats.append({
            'sid': p['sid'],
            'name': p['name'],
            'cracks': s.get('cracks', 0),
            'first_try_cracks': s.get('first_try_cracks', 0),
            'forfeits': forfeits,
            'rounds_survived': s.get('rounds_survived', 0),
            'guess_count': guess_count,
            'accuracy': round(accuracy, 1),
            'best_consecutive_cracks': s.get('best_consecutive_cracks', 0),
            'closest_miss': s.get('closest_miss'),
            'closest_miss_value': s.get('closest_miss_value')
        })

    # Append to room match history (last 10)
    history_entry = {
        'at': time.time(),
        'winner_name': winner['name'] if winner else None,
        'winner_sid': winner['sid'] if winner else None,
        'mode': state['settings'].get('mode'),
        'group_variant': state['settings'].get('group_variant'),
        'player_names': [p['name'] for p in humans],
        'series_scores': dict(state['series']['scores']) if state['series']['active'] else None,
        'series_target': state['series']['target'] if state['series']['active'] else None,
    }
    state.setdefault('match_history', []).append(history_entry)
    state['match_history'] = state['match_history'][-10:]

    socketio.emit('game_over', {
        'winner_name': winner['name'] if winner else None,
        'winner_sid': winner['sid'] if winner else None,
        'secrets': final_secrets,
        'mvp': mvp,
        'player_stats': player_stats,
        'mode': state['settings'].get('mode'),
        'group_variant': state['settings'].get('group_variant'),
    }, room=room['code'])
    broadcast_state(state, room['code'])


# =========================================================================
# BRACKET MODE
# =========================================================================

def build_bracket(player_sids: List[str], size: int) -> dict:
    """Build empty bracket structure for `size` players (4 or 8)."""
    players = list(player_sids)
    random.shuffle(players)
    while len(players) < size:
        players.append(None)   # bye spots (shouldn't happen if we validate)
    stages = []
    current = players
    while len(current) > 1:
        stage = []
        for i in range(0, len(current), 2):
            stage.append({'p1_sid': current[i], 'p2_sid': current[i + 1],
                          'winner_sid': None, 'played': False})
        stages.append(stage)
        current = [None] * len(stage)
    return {
        'size': size, 'stages': stages,
        'current_stage': 0, 'current_match': 0,
        'seeds': players
    }


def start_bracket_game(room: dict):
    state = room['state']
    players = [p['sid'] for p in state['players'].values() if not p.get('is_bot')]
    size = state['settings']['bracket_size']
    if len(players) != size:
        return False
    state['bracket'] = build_bracket(players, size)
    state['series'] = {'active': False, 'target': 1, 'match_number': 0, 'scores': {}}
    state['phase'] = 'bracket_intro'
    add_activity(state, 'bracket_intro', size=size)
    broadcast_state(state, room['code'])

    def after_intro():
        socketio.sleep(4)
        with room['lock']:
            start_next_bracket_match(room)
    socketio.start_background_task(after_intro)
    return True


def start_next_bracket_match(room: dict):
    state = room['state']
    br = state['bracket']
    if not br:
        return
    stage = br['stages'][br['current_stage']]
    match = stage[br['current_match']]
    p1_sid, p2_sid = match['p1_sid'], match['p2_sid']

    # Reset every player; non-participants in this match are sidelined as spectators
    for p in state['players'].values():
        p['secret'] = None
        p['target_sid'] = None
        p['guesses'] = []
        p['eliminated'] = False
        p['safe_this_round'] = False

    # Mark non-participants eliminated so they don't act
    for p in state['players'].values():
        if p['sid'] not in (p1_sid, p2_sid):
            p['eliminated'] = True

    # Chain just between the two participants
    state['chain'] = [p1_sid, p2_sid]
    random.shuffle(state['chain'])
    state['players'][state['chain'][0]]['target_sid'] = state['chain'][1]
    state['players'][state['chain'][1]]['target_sid'] = state['chain'][0]
    state['host_sid'] = state['chain'][0]
    state['round_number'] = 1
    state['phase'] = 'secrets'
    add_activity(state, 'bracket_match_start',
                 stage=br['current_stage'], match=br['current_match'],
                 p1=state['players'][p1_sid]['name'],
                 p2=state['players'][p2_sid]['name'])
    broadcast_state(state, room['code'])


def bracket_match_done(room: dict, winner_sid: Optional[str]):
    """Called when end_match fires inside a bracket. Advance the bracket."""
    state = room['state']
    br = state['bracket']
    if not br:
        return
    stage = br['stages'][br['current_stage']]
    match = stage[br['current_match']]
    match['winner_sid'] = winner_sid
    match['played'] = True

    # Show match-end screen
    state['phase'] = 'bracket_match_end'
    state['winner_sid'] = winner_sid
    state['current_turn_sid'] = None
    state['turn_started_at'] = None
    broadcast_state(state, room['code'])

    # Are we done with this stage?
    if br['current_match'] + 1 < len(stage):
        # More matches in this stage
        def after_pause():
            socketio.sleep(5)
            with room['lock']:
                s = room['state']
                if not s['bracket']:
                    return
                s['bracket']['current_match'] += 1
                start_next_bracket_match(room)
        socketio.start_background_task(after_pause)
    else:
        # Stage done. If this was the final, game over.
        if br['current_stage'] + 1 >= len(br['stages']):
            def after_pause_final():
                socketio.sleep(5)
                with room['lock']:
                    end_game(room, explicit_winner_sid=winner_sid)
            socketio.start_background_task(after_pause_final)
            return
        # Build next stage from this stage's winners
        winners = [m['winner_sid'] for m in stage]
        next_stage = br['stages'][br['current_stage'] + 1]
        for i in range(0, len(winners), 2):
            next_stage[i // 2]['p1_sid'] = winners[i]
            next_stage[i // 2]['p2_sid'] = winners[i + 1] if i + 1 < len(winners) else None
        br['current_stage'] += 1
        br['current_match'] = 0

        def after_pause_stage():
            socketio.sleep(5)
            with room['lock']:
                start_next_bracket_match(room)
        socketio.start_background_task(after_pause_stage)


# =========================================================================
# KING OF THE HILL
# =========================================================================

def start_koth_game(room: dict):
    state = room['state']
    players = [p['sid'] for p in state['players'].values() if not p.get('is_bot')]
    if len(players) < 3:
        return False
    random.shuffle(players)
    target = state['settings'].get('koth_target', 3)
    state['koth'] = {
        'king_sid': players[0],
        'target_wins': target,
        'scores': {sid: 0 for sid in players},
        'challenger_order': [],
        'current_challenger_idx': 0,
        'round_number': 1,
        'round_guesses': [],
        'last_outcome': None,
        'last_revealed_secret': None,
        'last_outgoing_king_sid': None,
        'last_new_king_sid': None
    }
    state['series'] = {'active': False, 'target': 1, 'match_number': 0, 'scores': {}}
    start_koth_round(room)
    return True


def start_koth_round(room: dict):
    """King sets a secret; challengers take ONE guess each."""
    state = room['state']
    koth = state['koth']
    state['round_number'] = koth['round_number']
    state['paused'] = False
    state['paused_at'] = None
    state['paused_by_sid'] = None
    state['pause_total_elapsed'] = 0.0
    koth['round_guesses'] = []
    koth['last_outcome'] = None
    koth['last_revealed_secret'] = None
    koth['last_outgoing_king_sid'] = None
    koth['last_new_king_sid'] = None

    for p in state['players'].values():
        p['secret'] = None
        p['target_sid'] = None
        p['guesses'] = []
        p['eliminated'] = False
        p['safe_this_round'] = False
        p['koth_guesses_used'] = 0

    king = state['players'].get(koth['king_sid'])
    if not king:
        end_game(room)
        return

    # Challenger order = everyone except king, shuffled
    challenger_sids = [sid for sid in state['players'].keys() if sid != koth['king_sid']]
    random.shuffle(challenger_sids)
    koth['challenger_order'] = challenger_sids
    koth['current_challenger_idx'] = 0

    # Everyone targets the king for their guesses
    for sid in challenger_sids:
        state['players'][sid]['target_sid'] = koth['king_sid']

    # King picks the secret; phase = secrets but with only king needing to act
    state['phase'] = 'secrets'
    state['chain'] = [koth['king_sid']] + challenger_sids
    state['host_sid'] = koth['king_sid']

    if king.get('is_bot'):
        bot_pick_secret(king, state['settings'])
        # Move immediately to playing
        koth_begin_playing(room)
    add_activity(state, 'koth_round_start',
                 round=koth['round_number'], king=king['name'])
    broadcast_state(state, room['code'])


def koth_begin_playing(room: dict):
    state = room['state']
    state['phase'] = 'playing'
    koth = state['koth']
    state['current_turn_sid'] = koth['challenger_order'][0]
    state['turn_started_at'] = time.time()
    state['pause_total_elapsed'] = 0.0
    broadcast_state(state, room['code'])
    _maybe_start_koth_turn(room, state['current_turn_sid'])


def _maybe_start_koth_turn(room: dict, turn_sid: str):
    start_turn_timer(room, turn_sid)   # same timer logic; forfeit on timeout
    p = room['state']['players'].get(turn_sid)
    if p and p.get('is_bot'):
        schedule_bot_turn(room, turn_sid)   # bot will guess once


def koth_after_guess(room: dict, guesser_sid: str, feedback: str):
    """After a challenger guesses in KOTH, either advance or end the round."""
    state = room['state']
    koth = state['koth']

    if feedback == 'correct':
        # Challenger cracks the king. Challenger scores, becomes new king.
        koth['scores'][guesser_sid] = koth['scores'].get(guesser_sid, 0) + 1
        cracker_name = state['players'][guesser_sid]['name']
        king_name = state['players'][koth['king_sid']]['name']
        add_activity(state, 'koth_cracked', cracker=cracker_name, king=king_name)
        check_koth_end_or_next(room, new_king_sid=guesser_sid)
        return

    # Not correct: advance to next challenger
    koth['current_challenger_idx'] += 1
    if koth['current_challenger_idx'] >= len(koth['challenger_order']):
        # All challengers tried, none cracked. King defends.
        king_sid = koth['king_sid']
        koth['scores'][king_sid] = koth['scores'].get(king_sid, 0) + 1
        king_name = state['players'][king_sid]['name']
        add_activity(state, 'koth_defended', king=king_name)
        check_koth_end_or_next(room, new_king_sid=king_sid)
        return

    # Otherwise next challenger
    state['current_turn_sid'] = koth['challenger_order'][koth['current_challenger_idx']]
    state['turn_started_at'] = time.time()
    state['pause_total_elapsed'] = 0.0
    broadcast_state(state, room['code'])
    _maybe_start_koth_turn(room, state['current_turn_sid'])


def check_koth_end_or_next(room: dict, new_king_sid: str):
    state = room['state']
    koth = state['koth']

    # Stash reveal info for clients on the round-end screen
    outgoing_king = state['players'].get(koth['king_sid'])
    koth['last_outgoing_king_sid'] = koth['king_sid']
    koth['last_new_king_sid'] = new_king_sid
    koth['last_outcome'] = 'defended' if new_king_sid == koth['king_sid'] else 'cracked'
    koth['last_revealed_secret'] = outgoing_king['secret'] if outgoing_king else None

    # Show round-end screen with king's revealed secret
    state['phase'] = 'koth_round_end'
    state['current_turn_sid'] = None
    state['turn_started_at'] = None
    broadcast_state(state, room['code'])

    # Winner?
    if koth['scores'].get(new_king_sid, 0) >= koth['target_wins']:
        def end_after_pause():
            socketio.sleep(5)
            with room['lock']:
                end_game(room, explicit_winner_sid=new_king_sid)
        socketio.start_background_task(end_after_pause)
        return

    # Otherwise advance to next round with new king
    def next_round():
        socketio.sleep(5)
        with room['lock']:
            s = room['state']
            if not s.get('koth'):
                return
            s['koth']['king_sid'] = new_king_sid
            s['koth']['round_number'] += 1
            start_koth_round(room)
    socketio.start_background_task(next_round)


# =========================================================================
# RESET / CLEANUP
# =========================================================================

def reset_to_lobby(room: dict):
    state = room['state']
    saved_humans = {}
    for sid, p in state['players'].items():
        if not p.get('is_bot') and p.get('disconnected_at') is None:
            saved_humans[sid] = fresh_player(sid, p['name'])
    for sid, p in state['sidelined'].items():
        if p.get('disconnected_at') is None and sid not in saved_humans:
            saved_humans[sid] = fresh_player(sid, p['name'])

    saved_leaderboard = dict(state['leaderboard'])
    saved_history = list(state.get('match_history', []))
    saved_last_args = state.get('last_start_args')
    saved_game_type = state.get('game_type', 'guessduel')

    new_state = fresh_game_state()
    new_state['game_type'] = saved_game_type
    new_state['players'] = saved_humans
    new_state['leaderboard'] = saved_leaderboard
    new_state['match_history'] = saved_history
    new_state['last_start_args'] = saved_last_args
    add_activity(new_state, 'new_lobby')

    room['state'] = new_state


# =========================================================================
# WORDCHAIN GAME FLOW
# =========================================================================

def start_wordchain_game(room: dict, difficulty: str, turn_timer: int,
                         include_bot: bool, bot_difficulty: str,
                         first_to: int = 1, mode_hint: str = 'group') -> bool:
    state = room['state']
    if not WORDLIST:
        return False
    state['game_type'] = 'wordchain'
    state['settings']['wc_difficulty'] = difficulty
    state['settings']['wc_turn_timer'] = turn_timer
    state['settings']['mode'] = 'solo' if include_bot else 'group'
    state['settings']['bot_difficulty'] = bot_difficulty
    state['settings']['wc_first_to'] = max(1, min(15, int(first_to)))

    # In solo: sideline other humans, add a bot
    if include_bot:
        host_sid = None
        for sid, p in list(state['players'].items()):
            if not p.get('is_bot'):
                host_sid = sid
                break
        if not host_sid:
            return False
        sidelined = {}
        for other_sid, p in list(state['players'].items()):
            if other_sid != host_sid and not p.get('is_bot'):
                sidelined[other_sid] = p
                del state['players'][other_sid]
        state['sidelined'] = sidelined
        bot = make_bot(bot_difficulty)
        bot['name'] = 'Computer'
        state['players'][bot['sid']] = bot

    real = [p['sid'] for p in state['players'].values()
            if not p.get('is_spectator')]
    if len(real) < 2:
        return False

    wc = fresh_wordchain_state()
    wc['difficulty'] = difficulty
    wc['turn_order'] = list(real)
    random.shuffle(wc['turn_order'])
    state['wordchain'] = wc
    # Series only meaningful for face-off (1v1). Solo and group always single match.
    series_target = state['settings']['wc_first_to'] if mode_hint == 'faceoff' else 1
    # Initialize series scores for all real players to 0 — preserve if rematching
    if not state.get('series', {}).get('scores'):
        state['series'] = {'active': series_target > 1, 'target': series_target,
                           'match_number': 1, 'scores': {sid: 0 for sid in real}}
    else:
        # Continuing a series — bump match_number, keep scores
        state['series']['match_number'] = state['series'].get('match_number', 0) + 1
        state['series']['active'] = series_target > 1
        state['series']['target'] = series_target
    state['round_number'] = 0
    state['paused'] = False
    add_activity(state, 'wc_game_start', difficulty=difficulty)

    start_wordchain_round(room)
    return True


def start_wordchain_round(room: dict):
    state = room['state']
    wc = state['wordchain']
    if not wc: return
    wc['round_number'] += 1
    state['round_number'] = wc['round_number']
    wc['letter'] = pick_letter_for_round(wc['difficulty'], wc['round_number'])
    wc['min_length'] = wordchain_min_length(wc['difficulty'], wc['round_number'])

    # Per-player letters: in face-off (2 humans) AND group (3+ humans),
    # each player gets their OWN letter for the round, at the shared length.
    # This reduces cheating (you can't just copy your neighbor's word) and
    # is what the user storyline specifies.
    # Solo (1 human + bot) keeps the shared letter.
    wc['player_letters'] = {}
    human_sids = [sid for sid, p in state['players'].items()
                  if not p.get('is_bot') and not p.get('eliminated')]
    if len(human_sids) >= 2:
        used = set()
        for hsid in human_sids:
            chosen = None
            for _ in range(30):
                candidate = pick_letter_for_round(wc['difficulty'], wc['round_number'])
                if candidate not in used:
                    chosen = candidate
                    break
            if not chosen:
                # Pool exhausted (e.g. easy mode has few letters and many players)
                # — fall back to allowing duplicates rather than crashing
                chosen = pick_letter_for_round(wc['difficulty'], wc['round_number'])
            used.add(chosen)
            wc['player_letters'][hsid] = chosen
    # Reset turn order to only non-eliminated players, keep order
    alive_sids = [sid for sid in wc['turn_order']
                  if sid in state['players']
                  and not state['players'][sid].get('eliminated')]
    if not alive_sids:
        # Everyone gone - end game with no winner
        end_wordchain_game(room, winner_sid=None)
        return
    if len(alive_sids) == 1:
        end_wordchain_game(room, winner_sid=alive_sids[0])
        return
    wc['turn_order'] = alive_sids
    wc['current_idx'] = 0

    state['phase'] = 'wc_round_intro'
    state['current_turn_sid'] = None
    state['turn_started_at'] = None
    add_activity(state, 'wc_round_start', round=wc['round_number'],
                 letter=wc['letter'], min_length=wc['min_length'])
    broadcast_state(state, room['code'])

    # Give players 3 seconds to see the round intro, then start the first turn
    def after_intro():
        socketio.sleep(3)
        with room['lock']:
            s = room['state']
            if s.get('phase') == 'wc_round_intro':
                start_wordchain_turn(room)
    socketio.start_background_task(after_intro)


def start_wordchain_turn(room: dict):
    state = room['state']
    wc = state['wordchain']
    if not wc: return
    if wc['current_idx'] >= len(wc['turn_order']):
        # All players in this round have taken their turn -> next round
        start_wordchain_round(room)
        return
    current_sid = wc['turn_order'][wc['current_idx']]
    state['current_turn_sid'] = current_sid
    state['turn_started_at'] = time.time()
    state['pause_total_elapsed'] = 0.0
    state['phase'] = 'wc_playing'
    broadcast_state(state, room['code'])
    start_wordchain_timer(room, current_sid)
    # If current player is a bot, schedule their move
    p = state['players'].get(current_sid)
    if p and p.get('is_bot'):
        schedule_bot_wordchain_turn(room, current_sid)


def start_wordchain_timer(room: dict, turn_sid: str):
    state = room['state']
    timer_sid = turn_sid
    started_at = state['turn_started_at']
    duration = state['settings']['wc_turn_timer']

    def timer_thread():
        while True:
            socketio.sleep(0.25)
            with room['lock']:
                s = room['state']
                if (s.get('phase') != 'wc_playing'
                    or s.get('current_turn_sid') != timer_sid
                    or s.get('turn_started_at') != started_at):
                    return
                if s.get('paused'):
                    continue
                elapsed = time.time() - s['turn_started_at'] - s['pause_total_elapsed']
                if elapsed >= duration:
                    # Time's up - eliminate this player
                    eliminate_wordchain_player(room, timer_sid)
                    return
    socketio.start_background_task(timer_thread)


def eliminate_wordchain_player(room: dict, sid: str):
    state = room['state']
    wc = state['wordchain']
    if not wc: return
    p = state['players'].get(sid)
    if not p: return
    p['eliminated'] = True
    add_activity(state, 'wc_eliminated', name=p['name'],
                 letter=wc['letter'], min_length=wc['min_length'])

    # Remove from turn_order and advance idx if needed
    if sid in wc['turn_order']:
        idx = wc['turn_order'].index(sid)
        wc['turn_order'].remove(sid)
        if idx < wc['current_idx']:
            wc['current_idx'] -= 1
        # current_idx now points at the next player

    alive = [s for s in wc['turn_order']
             if s in state['players']
             and not state['players'][s].get('eliminated')]
    if len(alive) <= 1:
        end_wordchain_game(room, winner_sid=alive[0] if alive else None)
        return

    broadcast_state(state, room['code'])
    socketio.sleep(0.1)
    start_wordchain_turn(room)


def schedule_bot_wordchain_turn(room: dict, bot_sid: str):
    state = room['state']
    started_at = state['turn_started_at']
    wc = state['wordchain']
    if not wc: return

    def bot_thread():
        # Bot "thinks" 1.5-3.5 seconds
        delay = 1.5 + random.random() * 2.0
        socketio.sleep(delay)
        with room['lock']:
            s = room['state']
            if (s.get('phase') != 'wc_playing'
                or s.get('current_turn_sid') != bot_sid
                or s.get('turn_started_at') != started_at):
                return
            cur_wc = s.get('wordchain')
            if not cur_wc: return
            used = {entry['word'] for entry in cur_wc['used_words']}
            bot = s['players'].get(bot_sid)
            if not bot: return
            word = bot_wordchain_word(cur_wc['letter'], cur_wc['min_length'],
                                      used, bot.get('bot_difficulty', 'medium'))
            if word is None:
                # Bot fails this turn - it gets eliminated
                eliminate_wordchain_player(room, bot_sid)
                return
            cur_wc['used_words'].append({
                'word': word, 'name': bot['name'], 'sid': bot_sid
            })
            cur_wc['last_word'] = word
            cur_wc['last_word_by'] = bot['name']
            add_activity(s, 'wc_word', name=bot['name'], word=word)
            socketio.emit('wc_word_accepted',
                          {'name': bot['name'], 'word': word}, room=room['code'])
            cur_wc['current_idx'] += 1
            broadcast_state(s, room['code'])
            socketio.sleep(0.5)
            start_wordchain_turn(room)
    socketio.start_background_task(bot_thread)


def end_wordchain_game(room: dict, winner_sid: Optional[str]):
    state = room['state']
    # Award match win to series scores (if series active)
    if winner_sid and state.get('series', {}).get('active'):
        cur = state['series']['scores'].get(winner_sid, 0)
        state['series']['scores'][winner_sid] = cur + 1

    if winner_sid:
        winner = state['players'].get(winner_sid)
        if winner:
            add_activity(state, 'wc_match_won', name=winner['name'])

    # Check whether the series is now decided
    series_winner_sid = None
    if state.get('series', {}).get('active'):
        target = state['series']['target']
        for sid, wins in state['series']['scores'].items():
            if wins >= target:
                series_winner_sid = sid
                break

    # If we're in an active series and nobody has hit target yet, start
    # the next match instead of ending the game.
    if state.get('series', {}).get('active') and not series_winner_sid:
        state['phase'] = 'wc_match_end'
        # Tell clients the match ended so the UI can show interim results
        socketio.emit('wc_match_end', {
            'match_winner_sid': winner_sid,
            'match_winner_name': state['players'][winner_sid]['name'] if winner_sid else None,
            'series_scores': dict(state['series']['scores']),
            'series_target': state['series']['target'],
            'match_number': state['series']['match_number']
        }, room=room['code'])
        broadcast_state(state, room['code'])

        def _next_match():
            socketio.sleep(5)
            with room['lock']:
                # Re-set up the next match: keep series scores, start a new WC
                start_wordchain_game(
                    room,
                    state['settings'].get('wc_difficulty', 'easy'),
                    state['settings'].get('wc_turn_timer', 30),
                    False,  # series only fires in faceoff which is not solo
                    state['settings'].get('bot_difficulty', 'medium'),
                    first_to=state['series']['target'],
                    mode_hint='faceoff'
                )
        socketio.start_background_task(_next_match)
        return

    # Otherwise: the series is decided (or never was a series). End the game.
    state['phase'] = 'game_over'
    final_winner_sid = series_winner_sid or winner_sid
    state['winner_sid'] = final_winner_sid
    if final_winner_sid:
        winner = state['players'].get(final_winner_sid)
        if winner:
            add_activity(state, 'wc_game_won', name=winner['name'])
            name = winner['name']
            if not winner.get('is_bot'):
                if name not in state['leaderboard']:
                    state['leaderboard'][name] = {'wins': 0, 'games': 0}
                state['leaderboard'][name]['wins'] += 1
        for p in state['players'].values():
            if p.get('is_bot') or p.get('is_spectator'): continue
            if p['name'] not in state['leaderboard']:
                state['leaderboard'][p['name']] = {'wins': 0, 'games': 0}
            if p['sid'] != final_winner_sid:
                state['leaderboard'][p['name']]['games'] += 1
        if winner and not winner.get('is_bot'):
            state['leaderboard'][winner['name']]['games'] += 1

    final_words = list(state['wordchain']['used_words']) if state.get('wordchain') else []
    socketio.emit('game_over', {
        'winner_name': state['players'][final_winner_sid]['name'] if final_winner_sid else None,
        'winner_sid': final_winner_sid,
        'game_type': 'wordchain',
        'words': final_words,
        'rounds': state['wordchain']['round_number'] if state.get('wordchain') else 0,
        'series_scores': dict(state['series']['scores']) if state.get('series') else None,
        'series_target': state.get('series', {}).get('target', 1)
    }, room=room['code'])
    broadcast_state(state, room['code'])





# =========================================================================
# SOCKETIO HANDLERS
# =========================================================================

@socketio.on('connect')
def on_connect():
    sid = request.sid
    # Log connections so the host can diagnose Cloudflare / multiplayer issues
    try:
        addr = request.remote_addr or '?'
        fwd = request.headers.get('X-Forwarded-For', '')
        transport = request.args.get('transport', '?')
        print(f"[connect] sid={sid[:8]} from={addr} fwd={fwd} transport={transport}")
    except Exception:
        pass
    emit('connected', {'sid': request.sid})


@socketio.on('hello')
def on_hello(data=None):
    """Client identifies itself with a stable per-browser user_id."""
    sid = request.sid
    if not isinstance(data, dict):
        return
    user_id = (data.get('user_id') or '').strip()[:64]
    name = (data.get('name') or '').strip()[:20]
    if not user_id:
        return
    with SID_TO_USER_LOCK:
        # If this user_id was previously connected with a different sid, drop the old sid
        old_sid = USER_TO_SID.get(user_id)
        if old_sid and old_sid != sid:
            SID_TO_USER.pop(old_sid, None)
        SID_TO_USER[sid] = {'user_id': user_id, 'name': name}
        USER_TO_SID[user_id] = sid
    print(f"[hello] sid={sid[:8]} user_id={user_id[:10]}... name={name!r}")
    broadcast_presence_change()


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    print(f"[disconnect] sid={sid[:8]}")
    # Clean up identity map and reverse lookup
    with SID_TO_USER_LOCK:
        u = SID_TO_USER.pop(sid, None)
        if u:
            uid = u.get('user_id')
            if uid and USER_TO_SID.get(uid) == sid:
                USER_TO_SID.pop(uid, None)
    broadcast_presence_change()
    # Check if they're in a match first
    with SID_TO_ROOM_LOCK:
        match_code = SID_TO_MATCH.get(sid)
        room_code = SID_TO_ROOM.get(sid)
    if match_code:
        m = get_match(match_code)
        if m:
            with m['lock']:
                if sid in m['players']:
                    m['players'][sid]['connected'] = False
                    broadcast_match_state(m)
    code = room_code
    if not code:
        return
    room = get_room(code)
    if not room:
        return
    with room['lock']:
        state = room['state']
        p = state['players'].get(sid) or state['sidelined'].get(sid)
        if not p:
            return
        p['disconnected_at'] = time.time()
        name = p['name']

        if state['current_turn_sid'] == sid and state['phase'] == 'playing':
            advance_turn(room, sid)
        else:
            broadcast_state(state, code)
        touch_room(room)

        # For LIVE real-time faceoff games, a disconnect shouldn't strand the
        # opponent for 5 minutes. Schedule a SHORT grace; if the player hasn't
        # reconnected, award the opponent the win. Captured here so the closure
        # has the right game_type/phase even if state changes later.
        rt_games = ('ts_round', 'ts_round_end', 'halfit_round', 'halfit_round_end',
                    'angle_round', 'angle_round_end', 'pict_round', 'pict_round_end',
                    'geo_round', 'geo_round_end')
        is_rt_faceoff = (state.get('mode_hint') == 'faceoff'
                         and state.get('phase') in rt_games)
        is_fb_faceoff = (state.get('mode_hint') == 'faceoff'
                         and state.get('game_type') == 'football'
                         and state.get('phase') in ('fb_draft', 'fb_match'))

    if is_rt_faceoff:
        def rt_forfeit_check():
            socketio.sleep(25)   # ~25s to survive a brief wifi blip / reconnect
            with room['lock']:
                state = room['state']
                gone = state['players'].get(sid)
                # Only forfeit if they're still here AND still disconnected
                if not gone or not gone.get('disconnected_at'):
                    return
                # Has the same user_id reconnected on a new sid? If so, abort.
                leaver_uid = gone.get('user_id')
                if leaver_uid:
                    for osid, op in state['players'].items():
                        if (osid != sid and op.get('user_id') == leaver_uid
                                and op.get('disconnected_at') is None):
                            return  # reconnected as a new sid; don't forfeit
                # Still a live faceoff with exactly one connected opponent?
                opponents = [pp for pp in state['players'].values()
                             if not pp.get('is_bot') and pp.get('sid') != sid
                             and pp.get('disconnected_at') is None]
                gt = state.get('game_type', 'guessduel')
                live_now = state.get('phase') in rt_games
                if not (live_now and len(opponents) == 1):
                    return
                leaver_name = gone.get('name')
                # Record the loss for the disconnected player
                try:
                    lp = get_profile(leaver_name, user_id=leaver_uid)
                    lp['losses'] = (lp.get('losses', 0) or 0) + 1
                    lp['games_played'] = (lp.get('games_played', 0) or 0) + 1
                    lp['current_streak'] = 0
                    mark_profiles_dirty()
                except Exception as e:
                    print(f"[rt-disconnect-forfeit] loss record failed: {e}")
                # Award the win to the opponent using the right path per game.
                if gt in ('angle', 'halfit', 'pictionary'):
                    _generic_forfeit_win(room, state, code, sid, leaver_name,
                                         opponents[0], gt)
                else:
                    # timeshot / geography: reuse their winner-population shape
                    _generic_forfeit_win(room, state, code, sid, leaver_name,
                                         opponents[0], gt)
                print(f"[rt-disconnect-forfeit] {leaver_name} d/c'd in {code}; "
                      f"{opponents[0]['name']} wins ({gt})")
        socketio.start_background_task(rt_forfeit_check)

    if is_fb_faceoff:
        def fb_forfeit_check():
            socketio.sleep(25)   # survive a brief blip; reconnect re-maps instead
            with room['lock']:
                st = room['state']
                gone = st['players'].get(sid)
                if not gone or not gone.get('disconnected_at'):
                    return
                leaver_uid = gone.get('user_id')
                if leaver_uid:
                    for osid, op in st['players'].items():
                        if (osid != sid and op.get('user_id') == leaver_uid
                                and op.get('disconnected_at') is None):
                            return  # same manager reconnected on a new sid
                opponents = [pp for pp in st['players'].values()
                             if not pp.get('is_bot') and pp.get('sid') != sid
                             and pp.get('disconnected_at') is None]
                if (st.get('phase') not in ('fb_draft', 'fb_match')
                        or len(opponents) != 1):
                    return
                leaver_name = gone.get('name')
                res = _fb_award_forfeit(st, sid, leaver_name, opponents[0])
                try:
                    lp = get_profile(leaver_name, user_id=leaver_uid)
                    lp['losses'] = (lp.get('losses', 0) or 0) + 1
                    lp['games_played'] = (lp.get('games_played', 0) or 0) + 1
                    lp['current_streak'] = 0
                    mark_profiles_dirty()
                except Exception as e:
                    print('[fb-dc-forfeit] loss record failed:', e)
                if res:
                    st['phase'] = 'fb_match'
                if sid in st['players']:
                    del st['players'][sid]
                fbmp = st.get('football_mp')
                if fbmp and isinstance(fbmp.get('sids'), list):
                    fbmp['sids'] = [s for s in fbmp['sids'] if s != sid]
                add_activity(st, 'opponent_forfeited', name=leaver_name,
                             winner=opponents[0]['name'])
                broadcast_state(st, code)
                print(f"[fb-dc-forfeit] {leaver_name} d/c'd in {code}; "
                      f"{opponents[0]['name']} wins 3-0")
        socketio.start_background_task(fb_forfeit_check)

    def grace_check():
        # 5 minutes — enough for the host to switch to Telegram/WhatsApp to
        # share the invite link without losing their room.
        socketio.sleep(300)
        with room['lock']:
            state = room['state']
            still_active = state['players'].get(sid)
            still_sidelined = state['sidelined'].get(sid)
            still = still_active or still_sidelined
            if still and still.get('disconnected_at'):
                if still_active:
                    del state['players'][sid]
                if still_sidelined:
                    del state['sidelined'][sid]
                if sid in state['chain']:
                    state['chain'].remove(sid)
                add_activity(state, 'left', name=name)

                active_humans = [p for p in state['players'].values()
                                 if not p.get('is_bot') and p.get('disconnected_at') is None]
                if len(active_humans) == 0:
                    reset_to_lobby(room)
                broadcast_state(state, code)
        with SID_TO_ROOM_LOCK:
            SID_TO_ROOM.pop(sid, None)

    socketio.start_background_task(grace_check)


@socketio.on('create_room')
def on_create_room(data=None):
    game_type = 'guessduel'
    mode_hint = 'group'
    if data and isinstance(data, dict):
        gt = data.get('game_type')
        if gt in ('guessduel', 'wordchain', 'timeshot', 'geography', 'halfit', 'angle', 'pictionary', 'trivia', 'footymind', 'football'):
            game_type = gt
        mh = data.get('mode_hint')
        if mh in ('faceoff', 'group', 'solo'):
            mode_hint = mh
    # Respect admin "disabled games" — refuse to create a room for a game the
    # owner has turned off (defense in depth; the client also hides it).
    try:
        if game_type in _admin.get_settings().get('disabled_games', []):
            emit('error_msg', {'msg': 'This game is currently unavailable.'})
            return
    except Exception:
        pass
    code = create_room(game_type, mode_hint)
    print(f"[create_room] sid={request.sid[:8]} code={code} game={game_type} hint={mode_hint}")
    emit('room_created', {
        'code': code,
        'game_type': game_type,
        'mode_hint': mode_hint
    })


@socketio.on('join_room')
def on_join_room(data):
    sid = request.sid
    code = (data.get('code') or '').strip().upper()
    name = (data.get('name') or '').strip()[:20]
    print(f"[join_room] sid={sid[:8]} code={code} name={name!r}")
    if not name:
        emit('error_msg', {'msg': 'Please enter a name'})
        return
    # Respect admin name bans
    try:
        if _admin.is_name_banned(name):
            emit('error_msg', {'msg': 'That name is not allowed. Please choose another.'})
            return
    except Exception:
        pass
    if not code:
        emit('error_msg', {'msg': 'No room code given'})
        return
    room = get_room(code)
    if not room:
        print(f"[join_room] FAIL: room {code} not found")
        emit('error_msg', {'msg': f'Room {code} not found'})
        return

    with room['lock']:
        state = room['state']

        # Reconnection (active player)
        for old_sid, p in list(state['players'].items()):
            if p['name'] == name and p.get('disconnected_at') is not None:
                p['sid'] = sid
                p['disconnected_at'] = None
                state['players'][sid] = p
                del state['players'][old_sid]
                state['chain'] = [sid if x == old_sid else x for x in state['chain']]
                for other in state['players'].values():
                    if other.get('target_sid') == old_sid:
                        other['target_sid'] = sid
                if state['current_turn_sid'] == old_sid:
                    state['current_turn_sid'] = sid
                if state['host_sid'] == old_sid:
                    state['host_sid'] = sid
                if state['winner_sid'] == old_sid:
                    state['winner_sid'] = sid
                # KOTH/bracket reconnect re-mapping
                if state.get('koth') and state['koth'].get('king_sid') == old_sid:
                    state['koth']['king_sid'] = sid
                if state.get('koth') and state['koth'].get('challenger_order'):
                    state['koth']['challenger_order'] = [
                        sid if x == old_sid else x
                        for x in state['koth']['challenger_order']
                    ]
                    state['koth']['scores'] = {
                        (sid if k == old_sid else k): v
                        for k, v in state['koth']['scores'].items()
                    }
                if state.get('bracket'):
                    for stage in state['bracket']['stages']:
                        for m in stage:
                            if m['p1_sid'] == old_sid: m['p1_sid'] = sid
                            if m['p2_sid'] == old_sid: m['p2_sid'] = sid
                            if m['winner_sid'] == old_sid: m['winner_sid'] = sid
                # Football MP reconnect re-mapping: keep this manager's squad and
                # readiness attached to their NEW sid so a blip doesn't leave the
                # opponent stuck on "waiting for opponent".
                fbmp = state.get('football_mp')
                if fbmp:
                    if isinstance(fbmp.get('sids'), list):
                        fbmp['sids'] = [sid if x == old_sid else x for x in fbmp['sids']]
                    if fbmp.get('home_sid') == old_sid:
                        fbmp['home_sid'] = sid
                    if fbmp.get('away_sid') == old_sid:
                        fbmp['away_sid'] = sid
                    for _k in ('submissions', 'names', 'uids', 'ht'):
                        _d = fbmp.get(_k)
                        if isinstance(_d, dict) and old_sid in _d:
                            _d[sid] = _d.pop(old_sid)
                    _r = fbmp.get('result')
                    if isinstance(_r, dict):
                        if _r.get('home_sid') == old_sid:
                            _r['home_sid'] = sid
                        if _r.get('away_sid') == old_sid:
                            _r['away_sid'] = sid
                    # If everyone is ready now (this manager readied just before
                    # the blip), run the match that was waiting on them.
                    if state.get('phase') == 'fb_draft':
                        _sids = fbmp.get('sids') or list(fbmp.get('names', {}).keys())
                        if _sids and all((fbmp['submissions'].get(s) or {}).get('ready')
                                         for s in _sids):
                            try:
                                if fbmp.get('mode') == 'group':
                                    _fb_run_group(fbmp)
                                else:
                                    _fb_run_faceoff_h1(fbmp)
                                state['phase'] = 'fb_match'
                            except Exception as e:
                                print('[fbmp reconnect] resume failed:', e)
                add_activity(state, 'rejoined', name=name)
                with SID_TO_ROOM_LOCK:
                    SID_TO_ROOM[sid] = code
                sio_join_room(code)
                touch_room(room)
                emit('joined_room', {'code': code})
                broadcast_state(state, code)
                return

        # Reconnection (sidelined)
        for old_sid, p in list(state['sidelined'].items()):
            if p['name'] == name and p.get('disconnected_at') is not None:
                p['sid'] = sid
                p['disconnected_at'] = None
                state['sidelined'][sid] = p
                del state['sidelined'][old_sid]
                with SID_TO_ROOM_LOCK:
                    SID_TO_ROOM[sid] = code
                sio_join_room(code)
                touch_room(room)
                emit('joined_room', {'code': code})
                broadcast_state(state, code)
                return

        # Auto-reset to lobby if game is over or nobody's actively playing
        active_humans = [p for p in state['players'].values()
                         if not p.get('is_bot') and p.get('disconnected_at') is None]
        if state['phase'] != 'lobby' and (len(active_humans) == 0 or state['phase'] == 'game_over'):
            reset_to_lobby(room)
            state = room['state']

        # Look up the joining user's user_id (set via 'hello')
        with SID_TO_USER_LOCK:
            user_info = SID_TO_USER.get(sid) or {}
            joiner_uid = user_info.get('user_id')

        # Look up avatar from profile ONCE at join time and store on player
        joiner_avatar_color = None
        joiner_avatar_image = None
        if joiner_uid:
            try:
                prof = get_profile(name, user_id=joiner_uid)
                joiner_avatar_color = prof.get('avatar_color')
                joiner_avatar_image = prof.get('avatar_image')
            except Exception:
                pass

        # If a game is in progress, join as spectator instead of rejecting.
        if state['phase'] != 'lobby':
            if joiner_uid and any(p.get('user_id') == joiner_uid
                                  for p in state['players'].values()
                                  if p.get('user_id')):
                pass
            spec = fresh_player(sid, name, user_id=joiner_uid)
            spec['avatar_color'] = joiner_avatar_color
            spec['avatar_image'] = joiner_avatar_image
            spec['is_spectator'] = True
            spec['eliminated'] = True
            state['players'][sid] = spec
            add_activity(state, 'spectator_joined', name=name)
            with SID_TO_ROOM_LOCK:
                SID_TO_ROOM[sid] = code
            sio_join_room(code)
            touch_room(room)
            emit('joined_room', {'code': code, 'as_spectator': True})
            broadcast_state(state, code)
            return

        # Same display name OK between different users (different user_ids).
        if joiner_uid and any(p.get('user_id') == joiner_uid
                              for p in state['players'].values()
                              if p.get('user_id')):
            emit('error_msg', {'msg': "You're already in this room"})
            return

        new_p = fresh_player(sid, name, user_id=joiner_uid)
        new_p['avatar_color'] = joiner_avatar_color
        new_p['avatar_image'] = joiner_avatar_image
        state['players'][sid] = new_p
        add_activity(state, 'joined', name=name)
        with SID_TO_ROOM_LOCK:
            SID_TO_ROOM[sid] = code
        sio_join_room(code)
        touch_room(room)
        emit('joined_room', {'code': code, 'as_spectator': False})
        broadcast_state(state, code)


def _get_room_for_sid(sid: str):
    with SID_TO_ROOM_LOCK:
        code = SID_TO_ROOM.get(sid)
    if not code:
        return None, None
    room = get_room(code)
    return room, code


@socketio.on('start_game')
def on_start_game(data):
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'lobby':
            return

        # TimeShot dispatch
        if state.get('game_type') == 'timeshot':
            difficulty = data.get('ts_difficulty', 'medium')
            if difficulty not in ('easy', 'medium', 'hard'):
                difficulty = 'medium'
            first_to = int(data.get('first_to', 3))
            first_to = max(1, min(15, first_to))
            mode = data.get('mode', 'solo')
            humans = [p for p in state['players'].values() if not p.get('is_bot')]
            if mode == 'solo':
                has_bot = any(p.get('is_bot') for p in state['players'].values())
                if not has_bot:
                    bot_sid = f"BOT_{random.randint(10000, 99999)}"
                    bot_p = fresh_player(bot_sid, 'Computer')
                    bot_p['is_bot'] = True
                    state['players'][bot_sid] = bot_p
            elif len(humans) < 2:
                emit('error_msg', {'msg': 'TimeShot needs at least 2 players or solo mode'})
                return
            state['settings']['mode'] = mode
            # Stash for rematch
            state['last_start_args'] = {
                'game_type': 'timeshot', 'mode': mode,
                'ts_difficulty': difficulty, 'first_to': first_to
            }
            ts_init_room(state, difficulty, first_to)
            touch_room(room)
            broadcast_state(state, code)
            return

        # Football manager dispatch (faceoff 1v1 or group mini-league)
        if state.get('game_type') == 'football':
            humans = [p for p in state['players'].values() if not p.get('is_bot')]
            if len(humans) < 2:
                emit('error_msg', {'msg': 'Football needs at least two players'})
                return
            fb_mode = 'group' if state.get('mode_hint') == 'group' else 'faceoff'
            if fb_mode == 'faceoff':
                humans = humans[:2]              # 1v1 only
            else:
                humans = humans[:8]              # cap the mini-league
            sids = [p['sid'] for p in humans]
            names, uids = {}, {}
            with SID_TO_USER_LOCK:
                for p in humans:
                    names[p['sid']] = p['name']
                    uids[p['sid']] = dict(SID_TO_USER.get(p['sid']) or {}).get('user_id')
            state['football_mp'] = {
                'phase': 'draft',
                'mode': fb_mode,
                'budget': _fbgame.BUDGET,
                'sids': sids,
                'home_sid': sids[0],
                'away_sid': sids[1] if len(sids) > 1 else sids[0],
                'names': names,
                'uids': uids,
                'submissions': {},
                'result': None,
            }
            state['host_sid'] = sids[0]
            state['phase'] = 'fb_draft'
            state['last_start_args'] = {'game_type': 'football', 'mode': fb_mode}
            touch_room(room)
            broadcast_state(state, code)
            return

        # WordChain dispatch
        if state.get('game_type') == 'wordchain':
            difficulty = data.get('wc_difficulty', 'easy')
            if difficulty not in ('easy', 'medium', 'hard'): difficulty = 'easy'
            turn_timer = int(data.get('wc_turn_timer', 30))
            turn_timer = max(10, min(120, turn_timer))
            mode = data.get('mode', 'group')
            bot_difficulty = data.get('bot_difficulty', 'medium')
            first_to = int(data.get('first_to', 1))
            first_to = max(1, min(15, first_to))
            include_bot = (mode == 'solo')
            humans = [p for p in state['players'].values()
                      if not p.get('is_bot') and not p.get('is_spectator')]
            if not include_bot and len(humans) < 2:
                emit('error_msg', {'msg': 'WordChain needs at least 2 players or solo mode'})
                return
            mode_hint = state.get('mode_hint', 'group')
            ok = start_wordchain_game(room, difficulty, turn_timer, include_bot,
                                       bot_difficulty, first_to=first_to,
                                       mode_hint=mode_hint)
            if not ok:
                emit('error_msg', {'msg': 'Could not start WordChain (dictionary missing?)'})
                return
            # Stash for rematch
            state['last_start_args'] = {
                'game_type': 'wordchain', 'mode': mode,
                'wc_difficulty': difficulty, 'wc_turn_timer': turn_timer,
                'bot_difficulty': bot_difficulty, 'first_to': first_to
            }
            touch_room(room)
            return

        # Geography multiplayer dispatch
        if state.get('game_type') == 'geography':
            mode = data.get('geo_mode', 'flags')
            if mode not in ('flags', 'capitals', 'continents', 'landmarks'):
                mode = 'flags'
            difficulty = data.get('geo_difficulty', 'mixed')
            if difficulty not in ('easy', 'medium', 'hard', 'mixed'):
                difficulty = 'mixed'
            total_rounds = int(data.get('total_rounds', GEO_DEFAULT_ROUNDS))
            total_rounds = max(3, min(15, total_rounds))
            humans = [p for p in state['players'].values()
                      if not p.get('is_bot') and not p.get('is_spectator')]
            if len(humans) < 2:
                emit('error_msg', {'msg': 'Geography multiplayer needs at least 2 players'})
                return
            state['settings']['mode'] = state.get('mode_hint', 'faceoff')
            state['last_start_args'] = {
                'game_type': 'geography', 'mode': state['settings']['mode'],
                'geo_mode': mode, 'geo_difficulty': difficulty,
                'total_rounds': total_rounds
            }
            geo_init_match(state, mode, total_rounds, difficulty)
            touch_room(room)
            geo_start_round(room)
            return

        # TriviaRush multiplayer dispatch (faceoff / group; solo uses HTTP)
        if state.get('game_type') == 'trivia':
            cats = data.get('categories') or []
            if not isinstance(cats, list):
                cats = []
            cats = [c for c in cats if isinstance(c, str)][:10]
            total_rounds = int(data.get('total_rounds', 10))
            if total_rounds not in (10, 20):
                total_rounds = 10 if total_rounds < 15 else 20
            humans = [p for p in state['players'].values()
                      if not p.get('is_bot') and not p.get('is_spectator')]
            if len(humans) < 2:
                emit('error_msg', {'msg': 'TriviaRush multiplayer needs at least 2 players'})
                return
            # Make sure the chosen categories actually have enough mc/tf questions
            test_q = trivia_mp_pick_question(cats, set())
            if not test_q:
                emit('error_msg', {'msg': 'Not enough questions in those categories. Pick more.'})
                return
            state['settings']['mode'] = state.get('mode_hint', 'group')
            state['last_start_args'] = {
                'game_type': 'trivia', 'mode': state['settings']['mode'],
                'categories': cats, 'total_rounds': total_rounds
            }
            trivia_init_match(state, cats, total_rounds)
            touch_room(room)
            trivia_start_round(room)
            return

        # FootyMind multiplayer dispatch (faceoff / group; solo uses HTTP)
        if state.get('game_type') == 'footymind':
            difficulty = (data.get('fm_difficulty') or 'easy').lower()
            if difficulty not in ('easy', 'medium', 'hard'):
                difficulty = 'easy'
            total_rounds = int(data.get('total_rounds', 10))
            if total_rounds not in (10, 20):
                total_rounds = 10 if total_rounds < 15 else 20
            humans = [p for p in state['players'].values()
                      if not p.get('is_bot') and not p.get('is_spectator')]
            if len(humans) < 2:
                emit('error_msg', {'msg': 'FootyMind multiplayer needs at least 2 players'})
                return
            state['settings']['mode'] = state.get('mode_hint', 'group')
            state['last_start_args'] = {
                'game_type': 'footymind', 'mode': state['settings']['mode'],
                'fm_difficulty': difficulty, 'total_rounds': total_rounds
            }
            footy_init_match(state, difficulty, total_rounds)
            touch_room(room)
            footy_start_round(room)
            return

        # HalfIt dispatch — works in solo, faceoff, or group mode
        if state.get('game_type') == 'halfit':
            hmode = data.get('halfit_mode', 'equal')
            if hmode not in ('equal', 'target'):
                hmode = 'equal'
            hdiff = data.get('halfit_difficulty', 'easy')
            if hdiff not in ('easy', 'medium', 'hard'):
                hdiff = 'easy'
            total_rounds = int(data.get('total_rounds', 5))
            total_rounds = max(1, min(10, total_rounds))
            # Allow solo (1 human) too — fine for practice
            state['settings']['mode'] = state.get('mode_hint', 'solo')
            state['last_start_args'] = {
                'game_type': 'halfit', 'mode': state['settings']['mode'],
                'halfit_mode': hmode, 'halfit_difficulty': hdiff,
                'total_rounds': total_rounds
            }
            halfit_init_match(state, hmode, hdiff, total_rounds)
            touch_room(room)
            halfit_start_round(room)
            return

        # Angle dispatch — works in solo, faceoff, or group mode
        if state.get('game_type') == 'angle':
            adiff = data.get('angle_difficulty', 'easy')
            if adiff not in ('easy', 'medium', 'hard'):
                adiff = 'easy'
            total_rounds = int(data.get('total_rounds', 5))
            total_rounds = max(1, min(10, total_rounds))
            state['settings']['mode'] = state.get('mode_hint', 'solo')
            state['last_start_args'] = {
                'game_type': 'angle', 'mode': state['settings']['mode'],
                'angle_difficulty': adiff, 'total_rounds': total_rounds
            }
            angle_init_match(state, adiff, total_rounds)
            touch_room(room)
            angle_start_round(room)
            return

        # Pictionary dispatch — solo, faceoff, or group
        if state.get('game_type') == 'pictionary':
            total_rounds = int(data.get('total_rounds', 5))
            total_rounds = max(1, min(15, total_rounds))
            pdiff = data.get('pict_difficulty', 'mixed')
            if pdiff not in ('easy', 'medium', 'hard', 'mixed'):
                pdiff = 'mixed'
            state['settings']['mode'] = state.get('mode_hint', 'solo')
            state['last_start_args'] = {
                'game_type': 'pictionary', 'mode': state['settings']['mode'],
                'total_rounds': total_rounds, 'pict_difficulty': pdiff
            }
            pict_init_match(state, total_rounds, pdiff)
            touch_room(room)
            pict_start_round(room)
            return

        mode = data.get('mode', 'group')
        group_variant = data.get('group_variant', 'chain')
        bot_difficulty = data.get('bot_difficulty', 'medium')
        first_to = int(data.get('first_to', 1))
        bracket_size = int(data.get('bracket_size', 4))
        koth_target = int(data.get('koth_target', 3))

        # Stash so 'rematch' can replay the same setup
        state['last_start_args'] = {
            'mode': mode, 'group_variant': group_variant,
            'bot_difficulty': bot_difficulty, 'first_to': first_to,
            'bracket_size': bracket_size, 'koth_target': koth_target
        }

        humans = [p for p in state['players'].values() if not p.get('is_bot')]
        human_count = len(humans)
        state['settings']['group_variant'] = group_variant
        state['settings']['bracket_size'] = bracket_size
        state['settings']['koth_target'] = koth_target

        if mode == 'solo':
            if sid not in state['players']:
                emit('error_msg', {'msg': 'You are not in the lobby'})
                return
            sidelined = {}
            for other_sid, p in list(state['players'].items()):
                if other_sid != sid and not p.get('is_bot'):
                    sidelined[other_sid] = p
                    del state['players'][other_sid]
            state['sidelined'] = sidelined
            bot = make_bot(bot_difficulty)
            state['players'][bot['sid']] = bot
            state['settings']['mode'] = 'solo'
            state['settings']['bot_difficulty'] = bot_difficulty
            state['series'] = {'active': False, 'target': 1, 'match_number': 1, 'scores': {}}
            start_new_round(room)
            touch_room(room)
            return

        if mode == 'faceoff':
            if human_count != 2:
                emit('error_msg', {'msg': 'Face-off needs exactly 2 players'})
                return
            state['settings']['mode'] = 'faceoff'
            if first_to > 1:
                state['series'] = {'active': True, 'target': first_to, 'match_number': 1,
                                   'scores': {s: 0 for s in state['players']}}
            else:
                state['series'] = {'active': False, 'target': 1, 'match_number': 1, 'scores': {}}
            state['settings']['first_to'] = first_to
            start_new_round(room)
            touch_room(room)
            return

        if mode == 'group':
            state['settings']['mode'] = 'group'
            state['series'] = {'active': False, 'target': 1, 'match_number': 1, 'scores': {}}

            if group_variant == 'bracket':
                if human_count != bracket_size:
                    emit('error_msg',
                         {'msg': f'Bracket needs exactly {bracket_size} players (you have {human_count})'})
                    return
                if not start_bracket_game(room):
                    emit('error_msg', {'msg': 'Could not start bracket'})
                    return
                touch_room(room)
                return

            if group_variant == 'koth':
                if human_count < 3:
                    emit('error_msg', {'msg': 'King of the hill needs 3+ players'})
                    return
                if not start_koth_game(room):
                    emit('error_msg', {'msg': 'Could not start king of the hill'})
                    return
                touch_room(room)
                return

            # chain or pick_target
            if human_count < 3:
                emit('error_msg', {'msg': 'Group mode needs 3+ players'})
                return
            start_new_round(room)
            touch_room(room)
            return

        emit('error_msg', {'msg': 'Unknown mode'})


@socketio.on('submit_settings')
def on_submit_settings(data):
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'setup' or sid != state['host_sid']:
            return
        try:
            difficulty = data['difficulty']
            range_min = float(data['range_min'])
            range_max = float(data['range_max'])
            turn_timer = int(data['turn_timer'])
        except (KeyError, ValueError, TypeError):
            emit('error_msg', {'msg': 'Invalid settings'})
            return
        if difficulty not in ('easy', 'medium', 'hard'):
            return
        if range_min >= range_max:
            emit('error_msg', {'msg': 'Min must be less than Max'})
            return
        if turn_timer < 5 or turn_timer > 120:
            emit('error_msg', {'msg': 'Timer must be 5 to 120 seconds'})
            return
        if difficulty != 'hard' and range_min < 0:
            emit('error_msg', {'msg': 'Negative numbers only allowed in Hard mode'})
            return
        if difficulty == 'easy':
            range_min = int(range_min) if range_min == int(range_min) else int(range_min) + 1
            range_max = int(range_max) if range_max == int(range_max) else int(range_max)
        state['settings'].update({
            'difficulty': difficulty,
            'range_min': range_min,
            'range_max': range_max,
            'turn_timer': turn_timer
        })
        add_activity(state, 'rules_set', difficulty=difficulty,
                     range_min=range_min, range_max=range_max)
        proceed_to_secrets_phase(room)
        broadcast_state(state, code)
        touch_room(room)


@socketio.on('submit_secret')
def on_submit_secret(data):
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'secrets':
            return
        p = state['players'].get(sid)
        if not p or p['eliminated']:
            return
        # In KOTH only the king sets a secret
        if state.get('koth') and sid != state['koth']['king_sid']:
            emit('error_msg', {'msg': 'Only the king sets the secret this round'})
            return
        num = validate_number(data.get('value'), state['settings'])
        if num is None:
            emit('error_msg', {'msg': 'Number must match the range and difficulty'})
            return
        p['secret'] = num
        touch_room(room)

        # KOTH: king sets secret, jump to playing
        if state.get('koth'):
            koth_begin_playing(room)
            return

        if all_secrets_in(state):
            variant = state['settings'].get('group_variant', 'chain')
            if state['settings']['mode'] == 'group' and variant == 'pick_target':
                begin_pick_target_phase(room)
                broadcast_state(state, code)
            else:
                begin_turns(room)
        else:
            broadcast_state(state, code)


@socketio.on('pick_target')
def on_pick_target(data):
    """Used in pick_target variant."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'pick_target':
            return
        p = state['players'].get(sid)
        if not p or p['eliminated'] or p['pick_locked']:
            return
        target_sid = data.get('target_sid')
        target = state['players'].get(target_sid)
        if not target or target['eliminated'] or target_sid == sid:
            emit('error_msg', {'msg': 'Pick a valid opponent'})
            return
        p['picked_target_sid'] = target_sid
        p['pick_locked'] = True
        add_activity(state, 'target_picked', name=p['name'], target=target['name'])
        touch_room(room)
        if all_picks_in(state):
            apply_picks_and_begin_turns(room)
        else:
            broadcast_state(state, code)


@socketio.on('submit_guess')
def on_submit_guess(data):
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'playing' or state['current_turn_sid'] != sid:
            return
        if state['paused']:
            emit('error_msg', {'msg': 'Game is paused'})
            return
        p = state['players'].get(sid)
        if not p:
            return
        num = validate_number(data.get('value'), state['settings'])
        if num is None:
            emit('error_msg', {'msg': 'Invalid guess'})
            return
        target = state['players'].get(p['target_sid'])
        if not target or target['secret'] is None:
            return
        secret = target['secret']
        if abs(num - secret) < 1e-9:
            feedback = 'correct'
        elif num < secret:
            feedback = 'higher'
        else:
            feedback = 'lower'
        p['guesses'].append({'value': num, 'feedback': feedback, 'at': time.time()})
        touch_room(room)

        # Stats: total guesses, cracks, first-try cracks, closest miss
        stats = p.setdefault('stats', {})
        stats['guess_count'] = stats.get('guess_count', 0) + 1
        if feedback == 'correct':
            stats['cracks'] = stats.get('cracks', 0) + 1
            # Count guesses this ROUND only (since p['guesses'] is reset each round)
            if len(p['guesses']) == 1:
                stats['first_try_cracks'] = stats.get('first_try_cracks', 0) + 1
        else:
            # Track closest miss this game
            diff = abs(num - secret)
            cur_best = stats.get('closest_miss')
            if cur_best is None or diff < cur_best:
                stats['closest_miss'] = diff
                stats['closest_miss_value'] = num

        # KOTH special flow
        if state.get('koth'):
            socketio.emit('crack' if feedback == 'correct' else 'guess_made',
                          {'name': p['name'], 'target': target['name'],
                           'first_try': feedback == 'correct' and len(p['guesses']) == 1},
                          room=code)
            add_activity(state, 'guess', name=p['name'], value=num, feedback=feedback)
            state['koth']['round_guesses'].append({
                'guesser_name': p['name'],
                'guesser_sid': sid,
                'value': num,
                'feedback': feedback
            })
            koth_after_guess(room, sid, feedback)
            return

        if feedback == 'correct':
            p['safe_this_round'] = True
            add_activity(state, 'crack', name=p['name'], target=target['name'])
            socketio.emit('crack', {'name': p['name'], 'target': target['name'],
                                    'first_try': len(p['guesses']) == 1}, room=code)
            if state['settings']['mode'] == 'faceoff' or len(active_players(state)) == 2:
                end_match(room, explicit_winner_sid=sid)
                return
        else:
            add_activity(state, 'guess', name=p['name'], value=num, feedback=feedback)
        advance_turn(room, sid)


@socketio.on('pause')
def on_pause():
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] not in ('playing', 'secrets', 'pick_target'):
            return
        if state['paused']:
            return
        if sid not in state['players']:
            return
        state['paused'] = True
        state['paused_at'] = time.time()
        state['paused_by_sid'] = sid
        name = state['players'][sid]['name']
        add_activity(state, 'paused', name=name)
        pause_marker = state['paused_at']
        touch_room(room)

        def pause_watcher():
            socketio.sleep(300)
            with room['lock']:
                s = room['state']
                if s['paused'] and s['paused_at'] == pause_marker:
                    pause_duration = time.time() - s['paused_at']
                    s['paused'] = False
                    s['paused_at'] = None
                    s['paused_by_sid'] = None
                    s['pause_total_elapsed'] += pause_duration
                    add_activity(s, 'pause_timeout')
                    if s['phase'] == 'playing' and s['current_turn_sid']:
                        p = s['players'].get(s['current_turn_sid'])
                        if p:
                            p['guesses'].append({'value': None, 'feedback': 'forfeit', 'at': time.time()})
                            p.setdefault('stats', {})['forfeits'] = p.get('stats', {}).get('forfeits', 0) + 1
                            add_activity(s, 'forfeit', name=p['name'])
                        advance_turn(room, s['current_turn_sid'])
                    else:
                        broadcast_state(s, code)
        socketio.start_background_task(pause_watcher)
    broadcast_state(room['state'], code)


@socketio.on('resume')
def on_resume():
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if not state['paused']:
            return
        elapsed_pause = time.time() - state['paused_at']
        is_pauser = (sid == state['paused_by_sid'])
        if not is_pauser and elapsed_pause < 60:
            emit('error_msg', {'msg': 'Only the player who paused can resume in the first minute'})
            return
        pause_duration = time.time() - state['paused_at']
        state['paused'] = False
        state['paused_at'] = None
        state['paused_by_sid'] = None
        state['pause_total_elapsed'] += pause_duration
        add_activity(state, 'resumed',
                     name=state['players'][sid]['name'] if sid in state['players'] else 'someone')
        if state['phase'] == 'playing' and state['current_turn_sid']:
            current = state['players'].get(state['current_turn_sid'])
            if current and current.get('is_bot'):
                schedule_bot_turn(room, current['sid'])
        touch_room(room)
    broadcast_state(room['state'], code)


@socketio.on('solo_forfeit')
def on_solo_forfeit(data=None):
    """Record a solo-game forfeit as a loss in the player's profile.
    Called by the client when the user confirms 'Leave' on a live solo
    game screen (geography, trivia, etc.) where there's no room state
    on the server side to drive the existing MP forfeit path."""
    sid = request.sid
    with SID_TO_USER_LOCK:
        info = SID_TO_USER.get(sid)
    if not info:
        print(f"[solo_forfeit] sid={sid[:8]} no user info — skipped")
        return
    name = info.get('name')
    uid = info.get('user_id')
    record_forfeit_loss(name, user_id=uid)
    # Read back so we can confirm what got recorded
    try:
        p = get_profile(name, user_id=uid)
        print(f"[solo_forfeit] {name} (uid={uid}): losses={p.get('losses')} "
              f"games={p.get('games_played')} streak={p.get('current_streak')}")
    except Exception:
        pass
    # Confirm to the client so it can show a definitive toast
    emit('forfeit_recorded', {'kind': 'solo', 'name': name})


def _generic_forfeit_win(room, state, code, leaver_sid, leaver_name,
                         winner_p, game_type):
    """Award a face-off forfeit win for the newer real-time games
    (angle, halfit, pictionary) where the per-game blocks above don't apply.
    Ends the game with the remaining player as winner.

    Returns True if it handled the forfeit.
    """
    winner_sid = winner_p['sid']
    winner_name = winner_p['name']
    winner_uid = winner_p.get('user_id')
    if leaver_sid in state['players']:
        del state['players'][leaver_sid]
    if leaver_sid in state.get('chain', []):
        state['chain'].remove(leaver_sid)
    add_activity(state, 'opponent_forfeited', name=leaver_name, winner=winner_name)
    try:
        wp = get_profile(winner_name, user_id=winner_uid)
        wp['wins'] = (wp.get('wins', 0) or 0) + 1
        wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
        wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
        if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
            wp['best_streak'] = wp['current_streak']
        grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type=game_type,
                 coins=10 * MP_COIN_MULTIPLIER)
        mark_profiles_dirty()
    except Exception as e:
        print(f"[forfeit-win-{game_type}] failed: {e}")
    socketio.emit('opponent_left', {
        'leaver_name': leaver_name,
        'msg': f'{leaver_name} left the game — you win!'
    }, room=code)
    state['phase'] = 'game_over'
    # Populate the per-game winner block so the game-over screen renders.
    if game_type == 'angle' and state.get('angle') is not None:
        state['angle']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'total_degrees_off': state['angle'].get('totals_degrees_off', {}).get(winner_sid, 0),
            'user_id': winner_uid}]
    elif game_type == 'halfit' and state.get('halfit') is not None:
        state['halfit']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'total_grams_off': state['halfit'].get('totals_grams_off', {}).get(winner_sid, 0),
            'user_id': winner_uid}]
    elif game_type == 'pictionary' and state.get('pict') is not None:
        state['pict']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'total_points': state['pict'].get('totals_points', {}).get(winner_sid, 0),
            'user_id': winner_uid}]
    elif game_type == 'timeshot' and state.get('timeshot') is not None:
        state['timeshot']['winner_sid'] = winner_sid
        state['timeshot']['winner_name'] = winner_name
        state['timeshot']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'rounds_won': state['timeshot'].get('round_scores', {}).get(winner_sid, 0),
            'is_bot': False}]
    elif game_type == 'geography' and state.get('geo') is not None:
        state['geo']['winners'] = [winner_sid]
        state['geo']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'score': state['geo'].get('scores', {}).get(winner_sid, 0),
            'is_bot': False}]
    elif game_type == 'trivia' and state.get('trivia') is not None:
        state['trivia']['winners'] = [winner_sid]
        state['trivia']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'score': state['trivia'].get('scores', {}).get(winner_sid, 0),
            'is_bot': False}]
    elif game_type == 'footymind' and state.get('footy') is not None:
        state['footy']['winners'] = [winner_sid]
        state['footy']['final_ranking'] = [{
            'sid': winner_sid, 'name': winner_name,
            'score': state['footy'].get('scores', {}).get(winner_sid, 0),
            'is_bot': False}]
    _rank_key = {'angle': 'angle', 'halfit': 'halfit', 'pictionary': 'pict',
                 'timeshot': 'timeshot', 'geography': 'geo',
                 'trivia': 'trivia', 'footymind': 'footy'}.get(game_type, '')
    socketio.emit('game_over', {
        'game_type': game_type,
        'winner_sid': winner_sid,
        'winner_name': winner_name,
        'winners': [{'sid': winner_sid, 'name': winner_name}],
        'final_ranking': (state.get(_rank_key, {}) or {}).get('final_ranking', []),
    }, room=code)
    broadcast_state(state, code)
    return True


@socketio.on('leave_game')
def on_leave_game():
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        socketio.emit('go_home', room=sid)
        return
    try:
        with room['lock']:
            state = room['state']
            if sid not in state['players']:
                return
            p = state['players'][sid]
            name = p['name']
            was_current_turn = (state['current_turn_sid'] == sid)

            # Identify the situation BEFORE removing the leaver
            human_opponents = [pp for pp in state['players'].values()
                               if not pp.get('is_bot')
                               and pp.get('sid') != sid
                               and pp.get('disconnected_at') is None]
            # Add geo phases to "live game" detection
            in_live_game = state['phase'] in ('playing', 'secrets', 'pick_target',
                                              'setup', 'cointoss',
                                              'wc_playing', 'wc_round_intro', 'wc_round_end',
                                              'ts_round', 'ts_round_end',
                                              'geo_round', 'geo_round_end',
                                              'trivia_round', 'trivia_round_end',
                                              'footy_round', 'footy_round_end',
                                              'halfit_round', 'halfit_round_end',
                                              'angle_round', 'angle_round_end',
                                              'pict_round', 'pict_round_end',
                                              'fb_draft', 'fb_match')
            is_faceoff = state.get('mode_hint') == 'faceoff'

            # Quit-as-loss: ANY live-game leave costs you a loss + streak reset.
            # Was previously gated on having human opponents — solo room games
            # (TS/WC/GD vs bot) escaped this. Now they don't.
            if in_live_game and name:
                try:
                    profile = get_profile(name, user_id=p.get('user_id'))
                    profile['losses'] = (profile.get('losses', 0) or 0) + 1
                    profile['games_played'] = (profile.get('games_played', 0) or 0) + 1
                    profile['current_streak'] = 0
                    mark_profiles_dirty()
                    opp_kind = 'multi' if human_opponents else 'solo'
                    print(f"[quit-as-loss] {name} forfeited live {opp_kind} game in {code}: "
                          f"losses={profile['losses']} games={profile['games_played']}")
                    # Tell the leaver's client so it can show a confirmation toast
                    socketio.emit('forfeit_recorded',
                                  {'kind': opp_kind, 'name': name}, room=sid)
                except Exception as e:
                    print(f"[quit-as-loss] failed to record loss: {e}")

            # === KEY FIX ===
            # In a face-off 1v1, when the leaver was one of exactly two humans and
            # the game is live, end the match RIGHT NOW with the remaining human
            # as the winner. Otherwise the opponent is stuck in a never-ending turn.
            ended_by_forfeit = False
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type', 'guessduel') == 'guessduel'):
                winner_sid = human_opponents[0]['sid']
                winner_name = human_opponents[0]['name']
                winner_uid = human_opponents[0].get('user_id')
                # Remove the leaver before declaring the winner so end_match
                # doesn't try to advance them.
                del state['players'][sid]
                if sid in state['chain']:
                    state['chain'].remove(sid)
                add_activity(state, 'opponent_forfeited', name=name, winner=winner_name)
                # Award the win XP/coins
                try:
                    wp = get_profile(winner_name, user_id=winner_uid)
                    wp['wins'] = (wp.get('wins', 0) or 0) + 1
                    wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
                    wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                    if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                        wp['best_streak'] = wp['current_streak']
                    # XP rules: face-off win
                    rule = XP_RULES.get(('guessduel', 'win'))
                    if rule:
                        xp, coins = rule
                        xp *= MP_XP_MULTIPLIER
                        coins *= MP_COIN_MULTIPLIER
                        grant_xp(wp, xp, game_type='guessduel', coins=coins)
                    mark_profiles_dirty()
                except Exception as e:
                    print(f"[forfeit-win] failed to award winner: {e}")
                socketio.emit('opponent_left', {
                    'leaver_name': name,
                    'msg': f'{name} left the game — you win!'
                }, room=code)
                # FORFEIT ends the WHOLE GAME, not just the current match.
                # Mark the series as a clean win for the opponent (target reached)
                # so the displayed series score reflects the forfeit outcome,
                # then end the game directly — don't go through end_match which
                # would try to start a next round in the series.
                if state.get('series', {}).get('active'):
                    target = state['series'].get('target', 1)
                    state['series']['scores'][winner_sid] = target
                    state['series']['active'] = False
                end_game(room, explicit_winner_sid=winner_sid)
                ended_by_forfeit = True

            # Same for WordChain face-off
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type', 'guessduel') == 'wordchain'
                and not ended_by_forfeit):
                winner_sid = human_opponents[0]['sid']
                winner_name = human_opponents[0]['name']
                winner_uid = human_opponents[0].get('user_id')
                del state['players'][sid]
                add_activity(state, 'opponent_forfeited', name=name, winner=winner_name)
                try:
                    wp = get_profile(winner_name, user_id=winner_uid)
                    wp['wins'] = (wp.get('wins', 0) or 0) + 1
                    wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
                    wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                    if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                        wp['best_streak'] = wp['current_streak']
                    rule = XP_RULES.get(('wordchain', 'win'))
                    if rule:
                        xp, coins = rule
                        xp *= MP_XP_MULTIPLIER
                        coins *= MP_COIN_MULTIPLIER
                        grant_xp(wp, xp, game_type='wordchain', coins=coins)
                    mark_profiles_dirty()
                except Exception as e:
                    print(f"[forfeit-win-wc] failed to award winner: {e}")
                socketio.emit('opponent_left', {
                    'leaver_name': name,
                    'msg': f'{name} left the game — you win!'
                }, room=code)
                end_wordchain_game(room, winner_sid=winner_sid)
                ended_by_forfeit = True

            # Football 1v1 forfeit. If the match has not been played yet (someone
            # left during the draft or while waiting), award the manager who
            # stayed a 3-0 win and record it in the league. If the match was
            # already simulated, that result stands.
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type', 'guessduel') == 'football'
                and not ended_by_forfeit):
                fbmp = state.get('football_mp')
                winner = human_opponents[0]
                res = _fb_award_forfeit(state, sid, name, winner)
                if res:
                    state['phase'] = 'fb_match'
                del state['players'][sid]
                if fbmp and isinstance(fbmp.get('submissions'), dict):
                    fbmp['submissions'].pop(sid, None)
                if fbmp and isinstance(fbmp.get('sids'), list):
                    fbmp['sids'] = [s for s in fbmp['sids'] if s != sid]
                add_activity(state, 'opponent_forfeited', name=name, winner=winner['name'])
                ended_by_forfeit = True

            # TimeShot forfeit: opponent left mid-round
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type', 'guessduel') == 'timeshot'
                and not ended_by_forfeit):
                winner_sid = human_opponents[0]['sid']
                winner_name = human_opponents[0]['name']
                winner_uid = human_opponents[0].get('user_id')
                del state['players'][sid]
                add_activity(state, 'opponent_forfeited', name=name, winner=winner_name)
                try:
                    wp = get_profile(winner_name, user_id=winner_uid)
                    wp['wins'] = (wp.get('wins', 0) or 0) + 1
                    wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
                    wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                    if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                        wp['best_streak'] = wp['current_streak']
                    rule = XP_RULES.get(('timeshot', 'win'))
                    if rule:
                        xp, coins = rule
                        xp *= MP_XP_MULTIPLIER
                        coins *= MP_COIN_MULTIPLIER
                        grant_xp(wp, xp, game_type='timeshot', coins=coins)
                    mark_profiles_dirty()
                except Exception as e:
                    print(f"[forfeit-win-ts] failed: {e}")
                socketio.emit('opponent_left', {
                    'leaver_name': name,
                    'msg': f'{name} left the game — you win!'
                }, room=code)
                state['phase'] = 'game_over'
                if state.get('timeshot'):
                    state['timeshot']['winner_sid'] = winner_sid
                    state['timeshot']['winner_name'] = winner_name
                    state['timeshot']['final_ranking'] = [{
                        'sid': winner_sid, 'name': winner_name,
                        'rounds_won': state['timeshot'].get('round_scores', {}).get(winner_sid, 0),
                        'is_bot': False
                    }]
                socketio.emit('game_over', {
                    'game_type': 'timeshot', 'winner_sid': winner_sid,
                    'winner_name': winner_name
                }, room=code)
                broadcast_state(state, code)
                ended_by_forfeit = True

            # Geography MP 1v1 forfeit: opponent wins and game ends
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type', 'guessduel') == 'geography'
                and not ended_by_forfeit):
                winner_sid = human_opponents[0]['sid']
                winner_name = human_opponents[0]['name']
                winner_uid = human_opponents[0].get('user_id')
                del state['players'][sid]
                add_activity(state, 'opponent_forfeited', name=name, winner=winner_name)
                # Award the win XP/coins
                try:
                    wp = get_profile(winner_name, user_id=winner_uid)
                    wp['wins'] = (wp.get('wins', 0) or 0) + 1
                    wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
                    wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                    if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                        wp['best_streak'] = wp['current_streak']
                    grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='geography',
                             coins=10 * MP_COIN_MULTIPLIER)
                    mark_profiles_dirty()
                except Exception as e:
                    print(f"[forfeit-win-geo] failed: {e}")
                socketio.emit('opponent_left', {
                    'leaver_name': name,
                    'msg': f'{name} left the game — you win!'
                }, room=code)
                state['phase'] = 'game_over'
                geo = state.get('geo')
                if geo is not None:
                    geo['winners'] = [winner_sid]
                    geo['final_ranking'] = [{
                        'sid': winner_sid, 'name': winner_name,
                        'score': geo.get('scores', {}).get(winner_sid, 0),
                        'is_bot': False
                    }]
                socketio.emit('game_over', {
                    'game_type': 'geography',
                    'winners': [{'sid': winner_sid, 'name': winner_name}],
                    'final_ranking': (geo or {}).get('final_ranking', [])
                }, room=code)
                broadcast_state(state, code)
                ended_by_forfeit = True

            # Newer real-time games (angle / halfit / pictionary / trivia /
            # footymind) — generic forfeit-win so the remaining player isn't stranded.
            if (is_faceoff and in_live_game and len(human_opponents) == 1
                and state.get('game_type') in ('angle', 'halfit', 'pictionary', 'trivia', 'footymind')
                and not ended_by_forfeit):
                ended_by_forfeit = _generic_forfeit_win(
                    room, state, code, sid, name,
                    human_opponents[0], state.get('game_type'))

            # Group play: leaver removed but game continues. Still announce.
            if (not ended_by_forfeit and in_live_game
                and state.get('mode_hint') == 'group' and len(human_opponents) >= 1):
                socketio.emit('opponent_left', {
                    'leaver_name': name,
                    'msg': f'{name} left the game'
                }, room=code)

            if not ended_by_forfeit:
                # Original flow: remove leaver and continue
                if sid in state['players']:
                    del state['players'][sid]
                if sid in state['chain']:
                    state['chain'].remove(sid)
                if state['chain']:
                    for i, csid in enumerate(state['chain']):
                        next_sid = state['chain'][(i + 1) % len(state['chain'])]
                        if csid in state['players']:
                            state['players'][csid]['target_sid'] = next_sid

                add_activity(state, 'left_game', name=name)

                humans_left = [pp for pp in state['players'].values() if not pp.get('is_bot')]
                if len(humans_left) == 0:
                    reset_to_lobby(room)
                elif state['phase'] == 'playing' and was_current_turn:
                    in_round = in_round_players(state)
                    if in_round:
                        state['current_turn_sid'] = in_round[0]['sid']
                        state['turn_started_at'] = time.time()
                        state['pause_total_elapsed'] = 0.0
                        _maybe_start_turn(room, state['current_turn_sid'])
                    else:
                        end_round(room)
                        return
        touch_room(room)
    finally:
        broadcast_state(room['state'], code)
        socketio.emit('go_home', room=sid)
        with SID_TO_ROOM_LOCK:
            SID_TO_ROOM.pop(sid, None)
        try:
            sio_leave_room(code, sid=sid)
        except Exception:
            pass


@socketio.on('next_game')
def on_next_game():
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state['phase'] != 'game_over':
            return
        reset_to_lobby(room)
    broadcast_state(room['state'], code)


@socketio.on('rematch')
def on_rematch():
    """One-tap: reset to lobby + immediately re-run last game's settings."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    last_args = None
    with room['lock']:
        state = room['state']
        if state['phase'] not in ('game_over', 'lobby'):
            return
        last_args = state.get('last_start_args')
        if not last_args:
            emit('error_msg', {'msg': 'No previous game to rematch'})
            return
        # Reset and re-broadcast lobby first
        if state['phase'] == 'game_over':
            reset_to_lobby(room)
    # Broadcast lobby state, then trigger the same start
    broadcast_state(room['state'], code)
    # Re-emit start_game with same args
    on_start_game(last_args)


@socketio.on('wc_submit_word')
def on_wc_submit_word(data):
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'wordchain':
            return
        if state.get('phase') != 'wc_playing':
            return
        if state.get('current_turn_sid') != sid:
            emit('error_msg', {'msg': 'Not your turn'})
            return
        wc = state.get('wordchain')
        if not wc:
            return
        word = (data.get('word') or '').strip().lower()
        used = {entry['word'] for entry in wc['used_words']}
        # Face-off: each player has their own letter. Solo/group: shared letter.
        my_letter = (wc.get('player_letters') or {}).get(sid) or wc['letter']
        err = validate_wordchain_submission(word, my_letter, wc['min_length'], used)
        if err:
            emit('wc_word_rejected', {'reason': err, 'word': word})
            return
        p = state['players'].get(sid)
        if not p:
            return
        wc['used_words'].append({'word': word, 'name': p['name'], 'sid': sid})
        wc['last_word'] = word
        wc['last_word_by'] = p['name']
        add_activity(state, 'wc_word', name=p['name'], word=word)
        socketio.emit('wc_word_accepted', {'name': p['name'], 'word': word}, room=code)
        wc['current_idx'] += 1
        broadcast_state(state, code)
        touch_room(room)
    # Next turn happens after a brief pause
    def next_turn():
        socketio.sleep(0.7)
        with room['lock']:
            s = room['state']
            if s.get('phase') == 'wc_playing':
                start_wordchain_turn(room)
    socketio.start_background_task(next_turn)


@socketio.on('reset_leaderboard')
def on_reset_leaderboard():
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        room['state']['leaderboard'] = {}
        add_activity(room['state'], 'leaderboard_reset')
    broadcast_state(room['state'], code)
    emit('toast', {'msg': 'Leaderboard cleared'})


# =========================================================================
# COUNTRIES / FLAGS (for FlagDuel)
# =========================================================================
# Wikipedia Commons SVG flag URLs. Free to hotlink for low traffic.

COUNTRIES_EASY = [
    ('United States', 'https://upload.wikimedia.org/wikipedia/en/a/a4/Flag_of_the_United_States.svg'),
    ('United Kingdom', 'https://upload.wikimedia.org/wikipedia/en/a/ae/Flag_of_the_United_Kingdom.svg'),
    ('France', 'https://upload.wikimedia.org/wikipedia/en/c/c3/Flag_of_France.svg'),
    ('Germany', 'https://upload.wikimedia.org/wikipedia/en/b/ba/Flag_of_Germany.svg'),
    ('Italy', 'https://upload.wikimedia.org/wikipedia/en/0/03/Flag_of_Italy.svg'),
    ('Spain', 'https://upload.wikimedia.org/wikipedia/en/9/9a/Flag_of_Spain.svg'),
    ('Japan', 'https://upload.wikimedia.org/wikipedia/en/9/9e/Flag_of_Japan.svg'),
    ('China', 'https://upload.wikimedia.org/wikipedia/commons/f/fa/Flag_of_the_People%27s_Republic_of_China.svg'),
    ('Brazil', 'https://upload.wikimedia.org/wikipedia/en/0/05/Flag_of_Brazil.svg'),
    ('Canada', 'https://upload.wikimedia.org/wikipedia/en/c/cf/Flag_of_Canada.svg'),
    ('Mexico', 'https://upload.wikimedia.org/wikipedia/commons/f/fc/Flag_of_Mexico.svg'),
    ('Russia', 'https://upload.wikimedia.org/wikipedia/en/f/f3/Flag_of_Russia.svg'),
    ('India', 'https://upload.wikimedia.org/wikipedia/en/4/41/Flag_of_India.svg'),
    ('Australia', 'https://upload.wikimedia.org/wikipedia/en/b/b9/Flag_of_Australia.svg'),
    ('South Africa', 'https://upload.wikimedia.org/wikipedia/commons/a/af/Flag_of_South_Africa.svg'),
    ('Argentina', 'https://upload.wikimedia.org/wikipedia/commons/1/1a/Flag_of_Argentina.svg'),
    ('Nigeria', 'https://upload.wikimedia.org/wikipedia/commons/7/79/Flag_of_Nigeria.svg'),
    ('Egypt', 'https://upload.wikimedia.org/wikipedia/commons/f/fe/Flag_of_Egypt.svg'),
    ('Sweden', 'https://upload.wikimedia.org/wikipedia/en/4/4c/Flag_of_Sweden.svg'),
    ('Netherlands', 'https://upload.wikimedia.org/wikipedia/commons/2/20/Flag_of_the_Netherlands.svg'),
    ('Greece', 'https://upload.wikimedia.org/wikipedia/commons/5/5c/Flag_of_Greece.svg'),
    ('South Korea', 'https://upload.wikimedia.org/wikipedia/commons/0/09/Flag_of_South_Korea.svg'),
    ('Turkey', 'https://upload.wikimedia.org/wikipedia/commons/b/b4/Flag_of_Turkey.svg'),
    ('Portugal', 'https://upload.wikimedia.org/wikipedia/commons/5/5c/Flag_of_Portugal.svg'),
    ('Ireland', 'https://upload.wikimedia.org/wikipedia/commons/4/45/Flag_of_Ireland.svg'),
]

COUNTRIES_MEDIUM = [
    ('Norway', 'https://upload.wikimedia.org/wikipedia/commons/d/d9/Flag_of_Norway.svg'),
    ('Finland', 'https://upload.wikimedia.org/wikipedia/commons/b/bc/Flag_of_Finland.svg'),
    ('Denmark', 'https://upload.wikimedia.org/wikipedia/commons/9/9c/Flag_of_Denmark.svg'),
    ('Poland', 'https://upload.wikimedia.org/wikipedia/en/1/12/Flag_of_Poland.svg'),
    ('Belgium', 'https://upload.wikimedia.org/wikipedia/commons/6/65/Flag_of_Belgium.svg'),
    ('Switzerland', 'https://upload.wikimedia.org/wikipedia/commons/f/f3/Flag_of_Switzerland.svg'),
    ('Austria', 'https://upload.wikimedia.org/wikipedia/commons/4/41/Flag_of_Austria.svg'),
    ('Thailand', 'https://upload.wikimedia.org/wikipedia/commons/a/a9/Flag_of_Thailand.svg'),
    ('Vietnam', 'https://upload.wikimedia.org/wikipedia/commons/2/21/Flag_of_Vietnam.svg'),
    ('Indonesia', 'https://upload.wikimedia.org/wikipedia/commons/9/9f/Flag_of_Indonesia.svg'),
    ('Saudi Arabia', 'https://upload.wikimedia.org/wikipedia/commons/0/0d/Flag_of_Saudi_Arabia.svg'),
    ('Kenya', 'https://upload.wikimedia.org/wikipedia/commons/4/49/Flag_of_Kenya.svg'),
    ('Ghana', 'https://upload.wikimedia.org/wikipedia/commons/1/19/Flag_of_Ghana.svg'),
    ('Morocco', 'https://upload.wikimedia.org/wikipedia/commons/2/2c/Flag_of_Morocco.svg'),
    ('Chile', 'https://upload.wikimedia.org/wikipedia/commons/7/78/Flag_of_Chile.svg'),
    ('Peru', 'https://upload.wikimedia.org/wikipedia/commons/c/cf/Flag_of_Peru.svg'),
    ('Colombia', 'https://upload.wikimedia.org/wikipedia/commons/2/21/Flag_of_Colombia.svg'),
    ('New Zealand', 'https://upload.wikimedia.org/wikipedia/commons/3/3e/Flag_of_New_Zealand.svg'),
    ('Singapore', 'https://upload.wikimedia.org/wikipedia/commons/4/48/Flag_of_Singapore.svg'),
    ('Israel', 'https://upload.wikimedia.org/wikipedia/commons/d/d4/Flag_of_Israel.svg'),
]

COUNTRIES_HARD = [
    ('Bhutan', 'https://upload.wikimedia.org/wikipedia/commons/9/91/Flag_of_Bhutan.svg'),
    ('Eritrea', 'https://upload.wikimedia.org/wikipedia/commons/2/29/Flag_of_Eritrea.svg'),
    ('Kyrgyzstan', 'https://upload.wikimedia.org/wikipedia/commons/c/c7/Flag_of_Kyrgyzstan.svg'),
    ('Turkmenistan', 'https://upload.wikimedia.org/wikipedia/commons/1/1b/Flag_of_Turkmenistan.svg'),
    ('Mongolia', 'https://upload.wikimedia.org/wikipedia/commons/4/4c/Flag_of_Mongolia.svg'),
    ('Nepal', 'https://upload.wikimedia.org/wikipedia/commons/9/9b/Flag_of_Nepal.svg'),
    ('Sri Lanka', 'https://upload.wikimedia.org/wikipedia/commons/1/11/Flag_of_Sri_Lanka.svg'),
    ('Uzbekistan', 'https://upload.wikimedia.org/wikipedia/commons/8/84/Flag_of_Uzbekistan.svg'),
    ('Madagascar', 'https://upload.wikimedia.org/wikipedia/commons/b/bc/Flag_of_Madagascar.svg'),
    ('Mauritania', 'https://upload.wikimedia.org/wikipedia/commons/4/43/Flag_of_Mauritania.svg'),
    ('Suriname', 'https://upload.wikimedia.org/wikipedia/commons/6/60/Flag_of_Suriname.svg'),
    ('Guyana', 'https://upload.wikimedia.org/wikipedia/commons/9/99/Flag_of_Guyana.svg'),
    ('Estonia', 'https://upload.wikimedia.org/wikipedia/commons/8/8f/Flag_of_Estonia.svg'),
    ('Latvia', 'https://upload.wikimedia.org/wikipedia/commons/8/84/Flag_of_Latvia.svg'),
    ('Lithuania', 'https://upload.wikimedia.org/wikipedia/commons/1/11/Flag_of_Lithuania.svg'),
    ('Slovakia', 'https://upload.wikimedia.org/wikipedia/commons/e/e6/Flag_of_Slovakia.svg'),
    ('Slovenia', 'https://upload.wikimedia.org/wikipedia/commons/f/f0/Flag_of_Slovenia.svg'),
    ('Croatia', 'https://upload.wikimedia.org/wikipedia/commons/1/1b/Flag_of_Croatia.svg'),
    ('Albania', 'https://upload.wikimedia.org/wikipedia/commons/3/36/Flag_of_Albania.svg'),
    ('Bolivia', 'https://upload.wikimedia.org/wikipedia/commons/d/de/Flag_of_Bolivia_%28state%29.svg'),
]

# Country answer normalization (so people can type slight variants)
COUNTRY_ALIASES = {
    'usa': 'United States', 'us': 'United States', 'america': 'United States',
    'uk': 'United Kingdom', 'britain': 'United Kingdom', 'england': 'United Kingdom',
    'great britain': 'United Kingdom',
    'south korea': 'South Korea', 'korea': 'South Korea',
    'uae': 'United Arab Emirates',
    'czech republic': 'Czechia', 'czechia': 'Czechia',
    'holland': 'Netherlands', 'the netherlands': 'Netherlands',
    'ivory coast': "Côte d'Ivoire",
    'cape verde': 'Cabo Verde',
}


def normalize_country_input(raw: str) -> str:
    s = (raw or '').strip().lower()
    # Strip accents and punctuation
    import unicodedata
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = ''.join(c for c in s if c.isalnum() or c == ' ').strip()
    s = ' '.join(s.split())
    if s in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[s].lower()
    return s


# =========================================================================
# MINDMELD PROMPTS
# =========================================================================
MINDMELD_PROMPTS = [
    "Something hot",
    "A round object",
    "An animal you'd find in a forest",
    "Something you'd find in a kitchen",
    "A color of the sky",
    "Something heavy",
    "Something soft",
    "A musical instrument",
    "Something that flies",
    "A type of weather",
    "Something you do every morning",
    "A piece of furniture",
    "A part of a tree",
    "Something in a hospital",
    "A word that means 'happy'",
    "An ocean creature",
    "Something in your pocket",
    "Something made of wood",
    "A type of bread",
    "A famous landmark",
    "A type of dance",
    "Something cold",
    "An emotion",
    "A board game",
    "Something you find at the beach",
    "A school subject",
    "Something that beeps",
    "A unit of measurement",
    "A bird",
    "Something you wear on your head"
]


# =========================================================================
# MATCH REGISTRY (for 1v1 games — FlagDuel duel, MindMeld)
# =========================================================================

MATCHES: Dict[str, Dict[str, Any]] = {}
MATCHES_LOCK = threading.Lock()
SID_TO_MATCH: Dict[str, str] = {}
MATCH_CODE_LENGTH = 4
MATCH_TTL = 30 * 60   # 30 min

def gen_match_code() -> str:
    while True:
        code = ''.join(random.choices(ROOM_CODE_ALPHABET, k=MATCH_CODE_LENGTH))
        if any(c in code for c in '0O1IL'):
            continue
        with MATCHES_LOCK:
            if code not in MATCHES:
                return code


def create_match(game_type: str) -> str:
    code = gen_match_code()
    with MATCHES_LOCK:
        MATCHES[code] = {
            'code': code,
            'game_type': game_type,
            'players': {},        # sid -> {name, sid, ready, ...}
            'state': None,        # game-specific (set when game starts)
            'created_at': time.time(),
            'last_activity_at': time.time(),
            'lock': threading.Lock()
        }
    return code


def get_match(code: str):
    if not code: return None
    with MATCHES_LOCK:
        return MATCHES.get(code)


def delete_match(code: str):
    with MATCHES_LOCK:
        MATCHES.pop(code, None)


def touch_match(m: dict):
    m['last_activity_at'] = time.time()


def broadcast_match_state(m: dict):
    """Send snapshot to both players."""
    for sid in list(m['players'].keys()):
        snap = build_match_snapshot(m, sid)
        socketio.emit('match_state', snap, room=sid)


def build_match_snapshot(m: dict, for_sid: str) -> dict:
    me = m['players'].get(for_sid, {})
    others = [p for sid, p in m['players'].items() if sid != for_sid]
    snap = {
        'code': m['code'],
        'game_type': m['game_type'],
        'me': {'sid': for_sid, 'name': me.get('name'), 'ready': me.get('ready', False)},
        'opponent': (
            {'name': others[0].get('name'), 'sid': others[0].get('sid'),
             'ready': others[0].get('ready', False), 'connected': others[0].get('connected', True)}
            if others else None
        ),
        'state': m.get('state'),
        'phase': m.get('phase', 'waiting')
    }
    return snap


# =========================================================================
# MATCH SOCKET HANDLERS (MindMeld, future 1v1 games)
# =========================================================================

@socketio.on('create_match')
def on_create_match(data):
    sid = request.sid
    game_type = (data or {}).get('game_type', 'mindmeld')
    name = ((data or {}).get('name') or '').strip()[:20]
    if not name:
        emit('error_msg', {'msg': 'Need a name to create a match'})
        return
    code = create_match(game_type)
    m = get_match(code)
    with m['lock']:
        m['players'][sid] = {
            'sid': sid, 'name': name, 'ready': True, 'connected': True
        }
        m['phase'] = 'waiting'
    with SID_TO_ROOM_LOCK:
        SID_TO_MATCH[sid] = code
    sio_join_room('match_' + code)
    emit('match_created', {'code': code, 'game_type': game_type})
    broadcast_match_state(m)


@socketio.on('join_match')
def on_join_match(data):
    sid = request.sid
    code = ((data or {}).get('code') or '').strip().upper()
    name = ((data or {}).get('name') or '').strip()[:20]
    if not name:
        emit('error_msg', {'msg': 'Need a name to join'})
        return
    m = get_match(code)
    if not m:
        emit('error_msg', {'msg': f'Match {code} not found'})
        return
    with m['lock']:
        # Reconnect by name?
        for old_sid, p in list(m['players'].items()):
            if p['name'] == name and not p.get('connected', True):
                p['sid'] = sid
                p['connected'] = True
                m['players'][sid] = p
                if old_sid != sid:
                    del m['players'][old_sid]
                with SID_TO_ROOM_LOCK:
                    SID_TO_MATCH[sid] = code
                sio_join_room('match_' + code)
                emit('match_joined', {'code': code, 'game_type': m['game_type']})
                broadcast_match_state(m)
                return
        if len(m['players']) >= 2:
            emit('error_msg', {'msg': 'Match is full'})
            return
        if any(p['name'] == name for p in m['players'].values()):
            emit('error_msg', {'msg': 'That name is already in this match'})
            return
        m['players'][sid] = {
            'sid': sid, 'name': name, 'ready': True, 'connected': True
        }
        with SID_TO_ROOM_LOCK:
            SID_TO_MATCH[sid] = code
        sio_join_room('match_' + code)
        emit('match_joined', {'code': code, 'game_type': m['game_type']})
        # If 2 players, start the game
        if len(m['players']) == 2 and m['game_type'] == 'mindmeld':
            start_mindmeld_match(m)
        broadcast_match_state(m)
    touch_match(m)


def start_mindmeld_match(m: dict):
    """Initialize MindMeld game state on the match."""
    m['phase'] = 'mm_playing'
    prompt = random.choice(MINDMELD_PROMPTS)
    m['state'] = {
        'round': 1,
        'prompt': prompt,
        'submissions': {},   # sid -> word (this round)
        'history': []        # list of {round, words: {sid->word}, prompt}
    }


@socketio.on('mindmeld_submit')
def on_mindmeld_submit(data):
    sid = request.sid
    with SID_TO_ROOM_LOCK:
        code = SID_TO_MATCH.get(sid)
    if not code:
        return
    m = get_match(code)
    if not m or m['game_type'] != 'mindmeld':
        return
    with m['lock']:
        if m.get('phase') != 'mm_playing':
            return
        st = m.get('state')
        if not st: return
        word = ((data or {}).get('word') or '').strip().lower()
        if not word or not word.replace('-', '').replace("'", '').isalpha():
            emit('error_msg', {'msg': 'One word, letters only'})
            return
        if len(word) > 30:
            emit('error_msg', {'msg': 'Too long'})
            return
        if sid in st['submissions']:
            return  # already submitted
        st['submissions'][sid] = word
        touch_match(m)
        # If both submitted, check
        if len(st['submissions']) >= 2:
            # Reveal
            words = dict(st['submissions'])
            st['history'].append({
                'round': st['round'],
                'prompt': st['prompt'] if st['round'] == 1 else None,
                'words': words
            })
            unique_words = set(words.values())
            if len(unique_words) == 1:
                # Match!
                m['phase'] = 'mm_done'
                m['state']['matched_word'] = list(unique_words)[0]
                m['state']['rounds_taken'] = st['round']
            else:
                # New round
                st['round'] += 1
                st['prompt'] = None  # no new prompt; bridge from last round
                st['submissions'] = {}
            broadcast_match_state(m)
            return
        # Just one submitted, broadcast state with submission count
        broadcast_match_state(m)


@socketio.on('mindmeld_rematch')
def on_mindmeld_rematch():
    sid = request.sid
    with SID_TO_ROOM_LOCK:
        code = SID_TO_MATCH.get(sid)
    if not code:
        return
    m = get_match(code)
    if not m: return
    with m['lock']:
        if len(m['players']) < 2:
            emit('error_msg', {'msg': 'Need both players'})
            return
        start_mindmeld_match(m)
        broadcast_match_state(m)


# =========================================================================
# HTTP ROUTES
# =========================================================================

@app.route('/version')
def api_version():
    """Return current build tag. Client polls and reloads if its loaded
    version doesn't match — catches stale browser/edge caches."""
    return jsonify({'version': 'v48'})


def _no_cache_html(resp):
    """Apply aggressive no-cache headers so browsers always pull fresh HTML.
    Versioned ?v=N query strings on JS/CSS handle the rest."""
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route('/')
def index():
    return _no_cache_html(make_response(render_template('index.html', room_code='', match_code='')))


@app.route('/r/<code>')
def room_page(code):
    code = (code or '').strip().upper()
    return _no_cache_html(make_response(render_template('index.html', room_code=code, match_code='')))


@app.route('/m/<code>')
def match_page(code):
    # Face-off rooms use the /m/ prefix with 4-char codes for visual distinction,
    # but they're stored in the same ROOMS registry as group rooms.
    code = (code or '').strip().upper()
    return _no_cache_html(make_response(render_template('index.html', room_code=code, match_code='')))


# ============================================================
# TIMESHOT — guess-the-time game
# Computer announces a target time (e.g. 5.75s). Players tap to start
# a HIDDEN timer, tap again to stop. Closest to target wins the round.
# Works for solo (vs bot), 1v1 face-off, and group.
# ============================================================

def ts_pick_target(difficulty: str = 'medium') -> float:
    """Pick a target time in seconds. Difficulty affects the range/precision."""
    if difficulty == 'easy':
        # 2-6 seconds, rounded to 0.5
        return round(random.uniform(2.0, 6.0) * 2) / 2
    if difficulty == 'hard':
        # 1-12 seconds, two decimals (sub-second precision)
        return round(random.uniform(1.0, 12.0), 2)
    # medium: 2-8 seconds, one decimal
    return round(random.uniform(2.0, 8.0), 1)


def ts_bot_attempt(target: float, difficulty: str = 'medium') -> float:
    """Simulate a bot's attempt — adds gaussian noise around the target.
    Harder bots have tighter accuracy."""
    if difficulty == 'easy':
        sigma = 0.60
    elif difficulty == 'hard':
        sigma = 0.12
    else:
        sigma = 0.30
    elapsed = target + random.gauss(0, sigma)
    return max(0.10, round(elapsed, 2))


def ts_init_room(state: dict, difficulty: str, first_to: int = 1):
    """Set up TimeShot game state on a room."""
    state['phase'] = 'ts_round'
    state['game_type'] = 'timeshot'
    state['timeshot'] = {
        'target': ts_pick_target(difficulty),
        'difficulty': difficulty,
        'round_number': 1,
        'first_to': max(1, int(first_to)),
        'attempts': {},        # sid -> {'elapsed': float, 'error': float}
        'started_at': {},      # sid -> client-recorded start time (ms) for verification
        'round_scores': {},    # sid -> rounds_won
        'last_results': None,
    }
    state['round_number'] = 1


def ts_record_attempt(room: dict, sid: str, elapsed_ms: float):
    """Player has tapped stop. Record their elapsed time."""
    state = room['state']
    ts = state.get('timeshot')
    if not ts:
        return
    if sid in ts['attempts']:
        return   # already attempted this round
    elapsed_s = max(0.10, round(float(elapsed_ms) / 1000.0, 2))
    err = abs(elapsed_s - ts['target'])
    ts['attempts'][sid] = {'elapsed': elapsed_s, 'error': round(err, 2)}
    # If everyone (humans + bots) has attempted, end the round
    human_and_bot_sids = list(state['players'].keys())
    pending = [s for s in human_and_bot_sids if s not in ts['attempts']]
    if not pending:
        ts_end_round(room)
        return
    # If only bots remain pending, schedule them
    bot_sids = [s for s in pending if state['players'][s].get('is_bot')]
    if bot_sids and len(bot_sids) == len(pending):
        for bsid in bot_sids:
            # bot fakes its attempt instantly
            be = ts_bot_attempt(ts['target'], ts['difficulty'])
            ts['attempts'][bsid] = {'elapsed': be, 'error': round(abs(be - ts['target']), 2)}
        ts_end_round(room)


def ts_end_round(room: dict):
    """All attempts in for this round. Pick a winner, award per-attempt XP, advance or end."""
    state = room['state']
    ts = state['timeshot']
    # Rank by error
    ranked = sorted(ts['attempts'].items(), key=lambda kv: kv[1]['error'])
    winner_sid = ranked[0][0] if ranked else None
    winner_p = state['players'].get(winner_sid) if winner_sid else None

    # Build results list with player names
    results = []
    for sid_r, att in ranked:
        p = state['players'].get(sid_r)
        if not p:
            continue
        results.append({
            'sid': sid_r,
            'name': p['name'],
            'is_bot': p.get('is_bot', False),
            'elapsed': att['elapsed'],
            'error': att['error']
        })
    ts['last_results'] = {
        'target': ts['target'],
        'round_number': ts['round_number'],
        'ranked': results,
        'winner_sid': winner_sid,
        'winner_name': winner_p['name'] if winner_p else None
    }

    # Score the round
    if winner_sid:
        ts['round_scores'][winner_sid] = ts['round_scores'].get(winner_sid, 0) + 1

    # Award per-attempt XP/coins to each HUMAN based on how close
    for r in results:
        if r['is_bot']:
            continue
        try:
            wp = get_profile(r['name'], r.get('user_id'))
            if r['error'] <= 0.05:
                xp, coins = XP_RULES.get(('timeshot', 'round_perfect'), (10, 2))
            elif r['error'] <= 0.25:
                xp, coins = XP_RULES.get(('timeshot', 'round_close'), (3, 1))
            else:
                xp, coins = (0, 0)
            if xp or coins:
                # For 1v1/group apply MP multipliers
                hint = state.get('mode_hint', 'solo')
                if hint in ('faceoff', 'group') and any(not pp.get('is_bot') for pp in state['players'].values() if pp.get('sid') != r['sid']):
                    xp *= MP_XP_MULTIPLIER
                    coins *= MP_COIN_MULTIPLIER
                grant_xp(wp, xp, game_type='timeshot', coins=coins)
                mark_profiles_dirty()
        except Exception as e:
            print(f"[ts] per-round xp grant failed: {e}")

    state['phase'] = 'ts_round_end'
    broadcast_state(state, room['code'])

    # After 4s, either start next round or end the game
    def _advance():
        socketio.sleep(4)
        with room['lock']:
            ts2 = state.get('timeshot')
            if not ts2:
                return
            # Check for game-ending: first to N rounds won
            high_score = max(ts2['round_scores'].values()) if ts2['round_scores'] else 0
            if high_score >= ts2['first_to']:
                ts_end_game(room)
                return
            # Next round
            ts2['round_number'] += 1
            ts2['target'] = ts_pick_target(ts2['difficulty'])
            ts2['attempts'] = {}
            ts2['started_at'] = {}
            ts2['last_results'] = None
            state['round_number'] = ts2['round_number']
            state['phase'] = 'ts_round'
            broadcast_state(state, room['code'])
    socketio.start_background_task(_advance)


def ts_end_game(room: dict):
    """Final winner: most rounds won. Award win XP + coins."""
    state = room['state']
    ts = state['timeshot']
    scores = ts['round_scores']
    if not scores:
        state['phase'] = 'game_over'
        broadcast_state(state, room['code'])
        return
    # Winner = sid with most rounds won
    winner_sid = max(scores.items(), key=lambda kv: kv[1])[0]
    winner = state['players'].get(winner_sid)
    state['phase'] = 'game_over'
    # Build a ranking that includes ALL players, not just the ones who won
    # a round. Zero-round players appear at the bottom.
    all_player_sids = list(state['players'].keys())
    final_ranking = []
    sorted_sids = sorted(all_player_sids, key=lambda s: -scores.get(s, 0))
    for sid_x in sorted_sids:
        p = state['players'].get(sid_x)
        if not p:
            continue
        final_ranking.append({
            'sid': sid_x, 'name': p['name'],
            'rounds_won': scores.get(sid_x, 0),
            'is_bot': p.get('is_bot', False)
        })
    ts['final_ranking'] = final_ranking
    ts['winner_sid'] = winner_sid
    ts['winner_name'] = winner['name'] if winner else None

    # Award final-win XP to the human winner (if any)
    if winner and not winner.get('is_bot'):
        try:
            wp = get_profile(winner['name'], winner.get('user_id'))
            wp['wins'] = (wp.get('wins', 0) or 0) + 1
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
            if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                wp['best_streak'] = wp['current_streak']
            xp, coins = XP_RULES.get(('timeshot', 'win'), (50, 10))
            hint = state.get('mode_hint', 'solo')
            if hint in ('faceoff', 'group'):
                xp *= MP_XP_MULTIPLIER
                coins *= MP_COIN_MULTIPLIER
            grant_xp(wp, xp, game_type='timeshot', coins=coins)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[ts] win grant failed: {e}")

    # Record losses for other humans
    for p in state['players'].values():
        if p.get('is_bot') or p.get('sid') == winner_sid:
            continue
        try:
            lp = get_profile(p['name'], p.get('user_id'))
            lp['losses'] = (lp.get('losses', 0) or 0) + 1
            lp['games_played'] = (lp.get('games_played', 0) or 0) + 1
            lp['current_streak'] = 0
            mark_profiles_dirty()
        except Exception:
            pass

    socketio.emit('game_over', {
        'game_type': 'timeshot',
        'winner_sid': winner_sid,
        'winner_name': winner['name'] if winner else None,
        'final_ranking': final_ranking
    }, room=room['code'])
    broadcast_state(state, room['code'])


# =========================================================================
# GEOGRAPHY MULTIPLAYER (face-off + group)
#
# Round flow:
#   1) Server picks an item, broadcasts state with phase=geo_round + deadline
#   2) Each player has GEO_ROUND_SECONDS to submit an answer via socket
#   3) When all humans answer OR deadline hits -> phase=geo_round_end
#   4) After GEO_ROUND_END_DELAY -> next round, OR game_over if last round
#   5) Game_over awards XP/coins to top scorer; ties → both get the win XP
# =========================================================================

GEO_ROUND_SECONDS = 15        # time per round before auto-advance
GEO_ROUND_END_DELAY = 4       # seconds to show results before next round
GEO_DEFAULT_ROUNDS = 5
GEO_CORRECT_BASE = 100        # base points for a correct answer
GEO_SPEED_MULT = 5            # speed bonus = (deadline - response) * mult


def geo_pick_item(mode: str, used_keys: set, difficulty: str = 'mixed') -> dict:
    """Pick a single geography item not in used_keys for the round."""
    try:
        import geography_data as gd
    except ImportError:
        return None
    # Try up to 10 times to find an unseen item
    for _ in range(10):
        if mode == 'flags':
            items = gd.get_flags_round(1, difficulty)
        elif mode == 'capitals':
            items = gd.get_capitals_round(1, difficulty)
        elif mode == 'continents':
            items = gd.get_continents_round(1, difficulty)
        elif mode == 'landmarks':
            items = gd.get_landmarks_round(1, difficulty)
        else:
            return None
        if not items:
            return None
        item = items[0]
        key = (item.get('country') or item.get('name') or '').lower()
        if key and key not in used_keys:
            return item
    # All exhausted — just return the last picked one
    return item if items else None


def geo_check_answer(mode: str, item: dict, answer: str) -> bool:
    """Server-side answer validation."""
    if not item:
        return False
    raw = (answer or '').strip()
    if not raw:
        return False
    if mode in ('flags', 'landmarks'):
        # For landmarks the correct answer is the landmark NAME, not country
        expected = item.get('name') if mode == 'landmarks' else item.get('country')
        norm_e = normalize_country_input(expected or '')
        norm_g = normalize_country_input(raw)
        return norm_e == norm_g and bool(norm_e)
    elif mode in ('capitals', 'continents'):
        return raw.strip().lower() == (item.get('answer') or '').strip().lower()
    return False


def geo_init_match(state: dict, mode: str, total_rounds: int, difficulty: str = 'mixed'):
    state['phase'] = 'geo_round'
    state['game_type'] = 'geography'
    state['geo'] = {
        'mode': mode,
        'difficulty': difficulty,
        'round_number': 0,    # will be bumped to 1 in geo_start_round
        'total_rounds': max(1, min(20, int(total_rounds))),
        'current_item': None,
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_answers': {},
        'scores': {sid: 0 for sid, p in state['players'].items() if not p.get('is_bot')},
        'used_keys': [],
    }
    state['round_number'] = 0


def geo_start_round(room: dict):
    state = room['state']
    geo = state.get('geo')
    if not geo:
        return
    geo['round_number'] += 1
    state['round_number'] = geo['round_number']
    used_set = set(geo.get('used_keys', []))
    item = geo_pick_item(geo['mode'], used_set, geo.get('difficulty', 'mixed'))
    if not item:
        # Nothing to ask — end the game early
        geo_end_match(room)
        return
    geo['current_item'] = item
    key = (item.get('country') or item.get('name') or '').lower()
    if key:
        geo['used_keys'].append(key)
    geo['round_started_at'] = time.time()
    geo['round_deadline'] = time.time() + GEO_ROUND_SECONDS
    geo['round_answers'] = {}
    state['phase'] = 'geo_round'
    broadcast_state(state, room['code'])
    # Schedule auto-end if not all players submitted by the deadline
    expected_round = geo['round_number']
    code = room['code']
    def _auto_end():
        socketio.sleep(GEO_ROUND_SECONDS + 0.3)
        with room['lock']:
            cur_geo = room['state'].get('geo')
            if (cur_geo and cur_geo.get('round_number') == expected_round
                and room['state'].get('phase') == 'geo_round'):
                geo_end_round(room)
    socketio.start_background_task(_auto_end)


def geo_end_round(room: dict):
    state = room['state']
    geo = state.get('geo')
    if not geo:
        return
    if state.get('phase') != 'geo_round':
        return
    state['phase'] = 'geo_round_end'
    broadcast_state(state, room['code'])
    # Schedule next round (or game over)
    code = room['code']
    expected_round = geo['round_number']
    def _advance():
        socketio.sleep(GEO_ROUND_END_DELAY)
        with room['lock']:
            cur_geo = room['state'].get('geo')
            if not cur_geo:
                return
            if cur_geo.get('round_number') != expected_round:
                return
            if room['state'].get('phase') != 'geo_round_end':
                return
            if cur_geo['round_number'] >= cur_geo['total_rounds']:
                geo_end_match(room)
            else:
                geo_start_round(room)
    socketio.start_background_task(_advance)


def geo_end_match(room: dict):
    state = room['state']
    geo = state.get('geo')
    if not geo:
        return
    state['phase'] = 'game_over'
    # Determine winner = highest score; ties = multiple winners
    scores = geo.get('scores', {})
    if not scores:
        winners = []
    else:
        top = max(scores.values())
        winners = [sid for sid, sc in scores.items() if sc == top and sc > 0]
    # Build the final ranking for client display
    ranking = []
    for sid, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
        p = state['players'].get(sid)
        if not p:
            continue
        ranking.append({'sid': sid, 'name': p['name'], 'score': sc,
                        'is_bot': bool(p.get('is_bot'))})
    geo['final_ranking'] = ranking
    geo['winners'] = winners

    # Award XP/coins to each winner (humans only)
    for wsid in winners:
        wp_player = state['players'].get(wsid)
        if not wp_player or wp_player.get('is_bot'):
            continue
        try:
            wp = get_profile(wp_player['name'], wp_player.get('user_id'))
            wp['wins'] = (wp.get('wins', 0) or 0) + 1
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
            if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                wp['best_streak'] = wp['current_streak']
            # 50 base * 3 MP = 150 XP, 10 base * 3 = 30 coins (matches GD)
            grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='geography',
                     coins=10 * MP_COIN_MULTIPLIER)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[geo_end_match] win-award failed: {e}")
    # Non-winners: increment games_played and reset streak
    for sid, p in state['players'].items():
        if p.get('is_bot') or sid in winners:
            continue
        try:
            losep = get_profile(p['name'], p.get('user_id'))
            losep['games_played'] = (losep.get('games_played', 0) or 0) + 1
            losep['losses'] = (losep.get('losses', 0) or 0) + 1
            losep['current_streak'] = 0
            mark_profiles_dirty()
        except Exception as e:
            print(f"[geo_end_match] loss-record failed: {e}")

    socketio.emit('game_over', {
        'game_type': 'geography',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']]
    }, room=room['code'])
    broadcast_state(state, room['code'])


@socketio.on('geo_submit_answer')
def on_geo_submit_answer(data=None):
    sid = request.sid
    if not isinstance(data, dict):
        return
    answer = (data.get('answer') or '').strip()[:80]
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'geography':
            return
        if state.get('phase') != 'geo_round':
            return
        geo = state.get('geo') or {}
        if sid in geo.get('round_answers', {}):
            return   # already answered this round
        item = geo.get('current_item')
        if not item:
            return
        correct = geo_check_answer(geo['mode'], item, answer)
        elapsed = max(0.1, time.time() - (geo.get('round_started_at') or time.time()))
        # Score: 100 base + speed bonus (more for faster correct answers)
        if correct:
            time_left = max(0.0, GEO_ROUND_SECONDS - elapsed)
            score_delta = GEO_CORRECT_BASE + int(time_left * GEO_SPEED_MULT)
        else:
            score_delta = 0
        geo['round_answers'][sid] = {
            'answer': answer,
            'time': round(elapsed, 2),
            'correct': correct,
            'score_delta': score_delta
        }
        geo['scores'][sid] = (geo['scores'].get(sid, 0) or 0) + score_delta
        broadcast_state(state, code)
        # If all human players have answered, end the round immediately
        human_sids = [s for s, p in state['players'].items() if not p.get('is_bot')]
        if all(s in geo['round_answers'] for s in human_sids):
            geo_end_round(room)


# =========================================================================
# TRIVIARUSH MULTIPLAYER — faceoff / group quiz race
#   Mirrors the Geography MP flow:
#   1) init_match builds state['trivia'] with scores + round tracking
#   2) start_round picks a question (mc or tf), broadcasts it WITHOUT the
#      answer, sets a deadline, schedules an auto-advance
#   3) players submit an option index; correct answers earn base + speed bonus
#   4) round ends when all answer or the timer expires -> reveal -> next round
#   5) after the last round -> final standings + XP to the winner(s)
#   Solo trivia stays on the existing HTTP flow; this is for 2+ humans.
# =========================================================================

TRIVIA_ROUND_SECONDS = 20       # time to answer each question
TRIVIA_ROUND_END_DELAY = 4      # reveal screen duration before next question
TRIVIA_CORRECT_BASE = 100       # base points for a correct answer
TRIVIA_SPEED_MULT = 5           # speed bonus = (time left) * mult


def trivia_mp_normalize(q: dict) -> dict:
    """Turn a raw trivia_questions entry into a normalized MP question with a
    flat options list + correct index. Returns None for unsupported types."""
    t = q.get('type')
    if t == 'mc':
        opts = list(q.get('options') or [])
        ans = q.get('answer')
        if not isinstance(ans, int) or ans < 0 or ans >= len(opts) or len(opts) < 2:
            return None
        return {'q': q.get('q', ''), 'cat': q.get('cat', ''), 'type': 'mc',
                'options': opts, 'answer_index': ans,
                'explain': q.get('explain', '')}
    if t == 'tf':
        is_true = bool(q.get('answer'))
        return {'q': q.get('q', ''), 'cat': q.get('cat', ''), 'type': 'tf',
                'options': ['True', 'False'], 'answer_index': 0 if is_true else 1,
                'explain': q.get('explain', '')}
    return None   # 'older' and anything else not supported in MP


def trivia_mp_pick_question(categories, used_ids: set):
    """Pick one random normalized mc/tf question, filtered by categories and
    excluding already-used question texts. Returns None if the pool is empty."""
    try:
        import trivia_questions as tq
        pool = tq.QUESTIONS
    except Exception:
        return None
    cands = []
    for q in pool:
        if q.get('type') not in ('mc', 'tf'):
            continue
        if categories and q.get('cat') not in categories:
            continue
        qid = q.get('q', '')[:60]
        if qid in used_ids:
            continue
        cands.append(q)
    if not cands:
        return None
    raw = random.choice(cands)
    norm = trivia_mp_normalize(raw)
    if not norm:
        return None
    norm['id'] = raw.get('q', '')[:60]
    return norm


def trivia_init_match(state: dict, categories, total_rounds: int):
    state['phase'] = 'trivia_round'
    state['game_type'] = 'trivia'
    state['trivia'] = {
        'categories': list(categories) if categories else [],
        'round_number': 0,
        'total_rounds': max(1, min(20, int(total_rounds))),
        'current_q': None,
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_answers': {},
        'scores': {sid: 0 for sid, p in state['players'].items() if not p.get('is_bot')},
        'used_ids': [],
        'final_ranking': [],
        'winners': [],
    }
    state['round_number'] = 0


def trivia_start_round(room: dict):
    state = room['state']
    tv = state.get('trivia')
    if not tv:
        return
    tv['round_number'] += 1
    state['round_number'] = tv['round_number']
    used = set(tv.get('used_ids', []))
    q = trivia_mp_pick_question(tv.get('categories'), used)
    if not q:
        # Pool exhausted (e.g. too few questions in the chosen categories) ->
        # end the match early rather than hang.
        trivia_end_match(room)
        return
    tv['current_q'] = q
    tv['used_ids'].append(q['id'])
    tv['round_started_at'] = time.time()
    tv['round_deadline'] = time.time() + TRIVIA_ROUND_SECONDS
    tv['round_answers'] = {}
    state['phase'] = 'trivia_round'
    broadcast_state(state, room['code'])
    expected_round = tv['round_number']
    def _auto_end():
        socketio.sleep(TRIVIA_ROUND_SECONDS + 0.3)
        with room['lock']:
            cur = room['state'].get('trivia')
            if (cur and cur.get('round_number') == expected_round
                    and room['state'].get('phase') == 'trivia_round'):
                trivia_end_round(room)
    socketio.start_background_task(_auto_end)


def trivia_end_round(room: dict):
    state = room['state']
    tv = state.get('trivia')
    if not tv:
        return
    if state.get('phase') != 'trivia_round':
        return
    state['phase'] = 'trivia_round_end'
    broadcast_state(state, room['code'])
    expected_round = tv['round_number']
    def _advance():
        socketio.sleep(TRIVIA_ROUND_END_DELAY)
        with room['lock']:
            cur = room['state'].get('trivia')
            if not cur:
                return
            if cur.get('round_number') != expected_round:
                return
            if room['state'].get('phase') != 'trivia_round_end':
                return
            if cur['round_number'] >= cur['total_rounds']:
                trivia_end_match(room)
            else:
                trivia_start_round(room)
    socketio.start_background_task(_advance)


def trivia_end_match(room: dict):
    state = room['state']
    tv = state.get('trivia')
    if not tv:
        return
    state['phase'] = 'game_over'
    scores = tv.get('scores', {})
    if not scores:
        winners = []
    else:
        top = max(scores.values())
        winners = [sid for sid, sc in scores.items() if sc == top and sc > 0]
    ranking = []
    for sid, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
        p = state['players'].get(sid)
        if not p:
            continue
        ranking.append({'sid': sid, 'name': p['name'], 'score': sc,
                        'is_bot': bool(p.get('is_bot'))})
    tv['final_ranking'] = ranking
    tv['winners'] = winners

    for wsid in winners:
        wp_player = state['players'].get(wsid)
        if not wp_player or wp_player.get('is_bot'):
            continue
        try:
            wp = get_profile(wp_player['name'], wp_player.get('user_id'))
            wp['wins'] = (wp.get('wins', 0) or 0) + 1
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
            if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                wp['best_streak'] = wp['current_streak']
            grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='trivia',
                     coins=10 * MP_COIN_MULTIPLIER)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[trivia_end_match] win-award failed: {e}")
    for sid, p in state['players'].items():
        if p.get('is_bot') or sid in winners:
            continue
        try:
            losep = get_profile(p['name'], p.get('user_id'))
            losep['games_played'] = (losep.get('games_played', 0) or 0) + 1
            losep['losses'] = (losep.get('losses', 0) or 0) + 1
            losep['current_streak'] = 0
            mark_profiles_dirty()
        except Exception as e:
            print(f"[trivia_end_match] loss-record failed: {e}")

    socketio.emit('game_over', {
        'game_type': 'trivia',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']]
    }, room=room['code'])
    broadcast_state(state, room['code'])


def trivia_public_state(tv: dict, phase: str) -> dict:
    """Client-safe view of trivia state. Hides the correct answer while the
    round is live; reveals it (and per-player results) at round end."""
    if not tv:
        return None
    q = tv.get('current_q') or {}
    reveal = (phase == 'trivia_round_end' or phase == 'game_over')
    pub_q = None
    if q:
        pub_q = {
            'q': q.get('q', ''),
            'cat': q.get('cat', ''),
            'type': q.get('type', 'mc'),
            'options': q.get('options', []),
        }
        if reveal:
            pub_q['answer_index'] = q.get('answer_index')
            pub_q['explain'] = q.get('explain', '')
    return {
        'round_number': tv.get('round_number', 0),
        'total_rounds': tv.get('total_rounds', 0),
        'question': pub_q,
        'round_deadline': tv.get('round_deadline', 0.0),
        'round_seconds': TRIVIA_ROUND_SECONDS,
        'scores': tv.get('scores', {}),
        # round_answers only at reveal (so others' choices aren't shown live)
        'round_answers': tv.get('round_answers', {}) if reveal else {
            sid: {'answered': True} for sid in tv.get('round_answers', {})
        },
        'final_ranking': tv.get('final_ranking', []),
        'winners': tv.get('winners', []),
    }


@socketio.on('trivia_submit_answer')
def on_trivia_submit_answer(data=None):
    sid = request.sid
    if not isinstance(data, dict):
        return
    try:
        choice = int(data.get('choice'))
    except (TypeError, ValueError):
        return
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'trivia':
            return
        if state.get('phase') != 'trivia_round':
            return
        tv = state.get('trivia') or {}
        if sid in tv.get('round_answers', {}):
            return   # already answered
        q = tv.get('current_q')
        if not q:
            return
        correct = (choice == q.get('answer_index'))
        elapsed = max(0.1, time.time() - (tv.get('round_started_at') or time.time()))
        if correct:
            time_left = max(0.0, TRIVIA_ROUND_SECONDS - elapsed)
            score_delta = TRIVIA_CORRECT_BASE + int(time_left * TRIVIA_SPEED_MULT)
        else:
            score_delta = 0
        tv['round_answers'][sid] = {
            'choice': choice,
            'time': round(elapsed, 2),
            'correct': correct,
            'score_delta': score_delta,
        }
        tv['scores'][sid] = (tv['scores'].get(sid, 0) or 0) + score_delta
        broadcast_state(state, code)
        human_sids = [s for s, p in state['players'].items() if not p.get('is_bot')]
        if all(s in tv['round_answers'] for s in human_sids):
            trivia_end_round(room)


# =========================================================================
# FOOTYMIND MULTIPLAYER — faceoff / group "guess the footballer"
#   Same flow as TriviaRush MP, but the "question" is a career path and the
#   answer is a TYPED player name (matched via lookup_player, the same fuzzy
#   alias matcher the solo mode uses). Solo FootyMind stays on HTTP.
# =========================================================================

FOOTY_ROUND_SECONDS = 25        # typing a name takes longer than tapping
FOOTY_ROUND_END_DELAY = 4
FOOTY_CORRECT_BASE = 100
FOOTY_SPEED_MULT = 4


def footy_mp_pick_player(difficulty: str, used_names: set):
    """Pick one player not yet used, at the given difficulty (padded from the
    full pool if sparse). Returns a dict incl. the canonical name (server-side)."""
    try:
        from footy_players import get_players_by_difficulty, PLAYERS
    except Exception:
        return None
    pool = get_players_by_difficulty(difficulty)
    if len(pool) < 1:
        pool = list(PLAYERS)
    cands = [p for p in pool if p.get('name') and p['name'] not in used_names]
    if not cands:
        # everyone at this difficulty used -> allow the full pool
        cands = [p for p in PLAYERS if p.get('name') and p['name'] not in used_names]
    if not cands:
        return None
    p = random.choice(cands)
    return {
        'name': p['name'],   # server-side only (the answer)
        'nationality': p.get('nationality', ''),
        'position': p.get('position', ''),
        'difficulty': p.get('difficulty', difficulty),
        'path': [{'years': yrs, 'club': club} for (yrs, club) in p.get('path', [])],
    }


def footy_init_match(state: dict, difficulty: str, total_rounds: int):
    state['phase'] = 'footy_round'
    state['game_type'] = 'footymind'
    state['footy'] = {
        'difficulty': difficulty,
        'round_number': 0,
        'total_rounds': max(1, min(20, int(total_rounds))),
        'current_player': None,
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_answers': {},
        'scores': {sid: 0 for sid, p in state['players'].items() if not p.get('is_bot')},
        'used_names': [],
        'final_ranking': [],
        'winners': [],
    }
    state['round_number'] = 0


def footy_start_round(room: dict):
    state = room['state']
    fm = state.get('footy')
    if not fm:
        return
    fm['round_number'] += 1
    state['round_number'] = fm['round_number']
    used = set(fm.get('used_names', []))
    player = footy_mp_pick_player(fm.get('difficulty', 'easy'), used)
    if not player:
        footy_end_match(room)
        return
    fm['current_player'] = player
    fm['used_names'].append(player['name'])
    fm['round_started_at'] = time.time()
    fm['round_deadline'] = time.time() + FOOTY_ROUND_SECONDS
    fm['round_answers'] = {}
    state['phase'] = 'footy_round'
    broadcast_state(state, room['code'])
    expected_round = fm['round_number']
    def _auto_end():
        socketio.sleep(FOOTY_ROUND_SECONDS + 0.3)
        with room['lock']:
            cur = room['state'].get('footy')
            if (cur and cur.get('round_number') == expected_round
                    and room['state'].get('phase') == 'footy_round'):
                footy_end_round(room)
    socketio.start_background_task(_auto_end)


def footy_end_round(room: dict):
    state = room['state']
    fm = state.get('footy')
    if not fm:
        return
    if state.get('phase') != 'footy_round':
        return
    state['phase'] = 'footy_round_end'
    broadcast_state(state, room['code'])
    expected_round = fm['round_number']
    def _advance():
        socketio.sleep(FOOTY_ROUND_END_DELAY)
        with room['lock']:
            cur = room['state'].get('footy')
            if not cur:
                return
            if cur.get('round_number') != expected_round:
                return
            if room['state'].get('phase') != 'footy_round_end':
                return
            if cur['round_number'] >= cur['total_rounds']:
                footy_end_match(room)
            else:
                footy_start_round(room)
    socketio.start_background_task(_advance)


def footy_end_match(room: dict):
    state = room['state']
    fm = state.get('footy')
    if not fm:
        return
    state['phase'] = 'game_over'
    scores = fm.get('scores', {})
    if not scores:
        winners = []
    else:
        top = max(scores.values())
        winners = [sid for sid, sc in scores.items() if sc == top and sc > 0]
    ranking = []
    for sid, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
        p = state['players'].get(sid)
        if not p:
            continue
        ranking.append({'sid': sid, 'name': p['name'], 'score': sc,
                        'is_bot': bool(p.get('is_bot'))})
    fm['final_ranking'] = ranking
    fm['winners'] = winners

    for wsid in winners:
        wp_player = state['players'].get(wsid)
        if not wp_player or wp_player.get('is_bot'):
            continue
        try:
            wp = get_profile(wp_player['name'], wp_player.get('user_id'))
            wp['wins'] = (wp.get('wins', 0) or 0) + 1
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
            if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                wp['best_streak'] = wp['current_streak']
            grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='footymind',
                     coins=10 * MP_COIN_MULTIPLIER)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[footy_end_match] win-award failed: {e}")
    for sid, p in state['players'].items():
        if p.get('is_bot') or sid in winners:
            continue
        try:
            losep = get_profile(p['name'], p.get('user_id'))
            losep['games_played'] = (losep.get('games_played', 0) or 0) + 1
            losep['losses'] = (losep.get('losses', 0) or 0) + 1
            losep['current_streak'] = 0
            mark_profiles_dirty()
        except Exception as e:
            print(f"[footy_end_match] loss-record failed: {e}")

    socketio.emit('game_over', {
        'game_type': 'footymind',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']]
    }, room=room['code'])
    broadcast_state(state, room['code'])


def footy_public_state(fm: dict, phase: str) -> dict:
    """Client-safe view. Hides the player's NAME (the answer) during the round;
    reveals it + per-player answers at round end."""
    if not fm:
        return None
    p = fm.get('current_player') or {}
    reveal = (phase == 'footy_round_end' or phase == 'game_over')
    clue = None
    if p:
        clue = {
            'nationality': p.get('nationality', ''),
            'position': p.get('position', ''),
            'path': p.get('path', []),
        }
        if reveal:
            clue['name'] = p.get('name', '')
    return {
        'round_number': fm.get('round_number', 0),
        'total_rounds': fm.get('total_rounds', 0),
        'clue': clue,
        'round_deadline': fm.get('round_deadline', 0.0),
        'round_seconds': FOOTY_ROUND_SECONDS,
        'scores': fm.get('scores', {}),
        'round_answers': fm.get('round_answers', {}) if reveal else {
            sid: {'answered': True} for sid in fm.get('round_answers', {})
        },
        'final_ranking': fm.get('final_ranking', []),
        'winners': fm.get('winners', []),
    }


@socketio.on('footy_submit_answer')
def on_footy_submit_answer(data=None):
    sid = request.sid
    if not isinstance(data, dict):
        return
    answer = (data.get('answer') or '').strip()[:60]
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'footymind':
            return
        if state.get('phase') != 'footy_round':
            return
        fm = state.get('footy') or {}
        if sid in fm.get('round_answers', {}):
            return
        p = fm.get('current_player')
        if not p:
            return
        matched = lookup_player(answer)            # fuzzy alias match
        correct = (matched is not None and matched == p.get('name'))
        elapsed = max(0.1, time.time() - (fm.get('round_started_at') or time.time()))
        if correct:
            time_left = max(0.0, FOOTY_ROUND_SECONDS - elapsed)
            score_delta = FOOTY_CORRECT_BASE + int(time_left * FOOTY_SPEED_MULT)
        else:
            score_delta = 0
        fm['round_answers'][sid] = {
            'answer': answer,
            'time': round(elapsed, 2),
            'correct': correct,
            'score_delta': score_delta,
        }
        fm['scores'][sid] = (fm['scores'].get(sid, 0) or 0) + score_delta
        broadcast_state(state, code)
        human_sids = [s for s, p2 in state['players'].items() if not p2.get('is_bot')]
        if all(s in fm['round_answers'] for s in human_sids):
            footy_end_round(room)


# =========================================================================
# HALFIT — spatial-estimation slicing game
#   Players slice a shape with a straight line. Mode A = equal cut,
#   Mode B = target cut (e.g. "cut 73g from this 187g banana"). Server
#   generates the shape, broadcasts vertices + mass, scores each cut by
#   absolute grams off. Lowest grams off wins the round; sum across rounds
#   determines the match winner.
# =========================================================================

HALFIT_ROUND_SECONDS = 25      # how long a player has to make a cut
HALFIT_ROUND_END_SECONDS = 5   # how long the result screen shows before next round

try:
    import halfit_data as _halfit
except ImportError:
    _halfit = None


def halfit_init_match(state: dict, mode: str, difficulty: str,
                      total_rounds: int):
    """Reset state for a new HalfIt match. mode = 'equal' | 'target'."""
    state['phase'] = 'halfit_round'
    state['game_type'] = 'halfit'
    state['halfit'] = {
        'mode': mode,                                  # 'equal' or 'target'
        'difficulty': difficulty,                      # 'easy' / 'medium' / 'hard'
        'round_number': 0,
        'total_rounds': max(1, min(20, int(total_rounds))),
        'current_shape': None,
        'current_target_g': None,
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_cuts': {},                              # sid -> {p1, p2, score}
        'totals_grams_off': {sid: 0.0 for sid, p in state['players'].items()
                             if not p.get('is_bot')},
    }
    state['round_number'] = 0


def halfit_start_round(room: dict):
    state = room['state']
    h = state.get('halfit')
    if not h or not _halfit:
        return
    h['round_number'] += 1
    state['round_number'] = h['round_number']
    shape = _halfit.generate_shape(h['difficulty'])
    h['current_shape'] = shape
    if h['mode'] == 'target':
        h['current_target_g'] = _halfit.pick_target_mass(
            shape['total_mass_g'], h['difficulty'])
    else:
        h['current_target_g'] = None
    h['round_started_at'] = time.time()
    h['round_deadline'] = time.time() + HALFIT_ROUND_SECONDS
    h['round_cuts'] = {}
    state['phase'] = 'halfit_round'
    broadcast_state(state, room['code'])
    # Schedule auto-end if not everyone cut by the deadline
    expected_round = h['round_number']
    code = room['code']

    def deadline_check():
        socketio.sleep(HALFIT_ROUND_SECONDS + 0.5)
        with room['lock']:
            cur_state = room['state']
            cur_h = cur_state.get('halfit') or {}
            if (cur_h.get('round_number') == expected_round
                    and cur_state.get('phase') == 'halfit_round'):
                halfit_end_round(room)
    socketio.start_background_task(deadline_check)


def halfit_end_round(room: dict):
    state = room['state']
    h = state.get('halfit')
    if not h or state.get('phase') != 'halfit_round':
        return
    state['phase'] = 'halfit_round_end'
    # Players who already cut had their total updated in on_halfit_submit_cut.
    # Here we ONLY add the no-cut penalty for players who never cut, to avoid
    # double-counting (this was a bug in v28).
    shape = h.get('current_shape') or {}
    total_mass = shape.get('total_mass_g', 100)
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        if sid not in h['round_cuts']:
            h['round_cuts'][sid] = {
                'p1': None, 'p2': None,
                'score': {'grams_off': total_mass, 'surgical': False,
                          'left_mass_g': 0, 'right_mass_g': 0,
                          'total_mass_g': total_mass, 'no_cut': True}
            }
            h['totals_grams_off'][sid] = round(
                h['totals_grams_off'].get(sid, 0) + total_mass, 2)
    broadcast_state(state, room['code'])
    expected_round = h['round_number']
    code = room['code']

    def advance():
        socketio.sleep(HALFIT_ROUND_END_SECONDS)
        with room['lock']:
            cur_state = room['state']
            cur_h = cur_state.get('halfit') or {}
            if cur_state.get('phase') != 'halfit_round_end':
                return
            if cur_h.get('round_number') != expected_round:
                return
            if cur_h['round_number'] >= cur_h['total_rounds']:
                halfit_end_match(room)
            else:
                halfit_start_round(room)
    socketio.start_background_task(advance)


def halfit_end_match(room: dict):
    state = room['state']
    h = state.get('halfit')
    if not h:
        return
    state['phase'] = 'game_over'
    totals = h['totals_grams_off']
    # Lowest grams off wins. Build ranking.
    ranking = []
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        ranking.append({
            'sid': sid,
            'name': p['name'],
            'user_id': p.get('user_id'),
            'total_grams_off': round(totals.get(sid, 0), 2),
        })
    ranking.sort(key=lambda r: r['total_grams_off'])
    winners = [ranking[0]['sid']] if ranking else []
    # Award winner XP + record losses
    is_multi = len([s for s, p in state['players'].items() if not p.get('is_bot')]) >= 2
    for r in ranking:
        try:
            sid = r['sid']
            wp = get_profile(r['name'], user_id=r.get('user_id'))
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            if sid in winners and is_multi:
                wp['wins'] = (wp.get('wins', 0) or 0) + 1
                wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                    wp['best_streak'] = wp['current_streak']
                grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='halfit',
                         coins=10 * MP_COIN_MULTIPLIER)
            elif is_multi:
                wp['losses'] = (wp.get('losses', 0) or 0) + 1
                wp['current_streak'] = 0
            else:
                # Solo — small XP for completion
                grant_xp(wp, 15, game_type='halfit', coins=3)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[halfit_end_match] xp/loss failed: {e}")
    socketio.emit('game_over', {
        'game_type': 'halfit',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']],
        'winner_sid': winners[0] if winners else None,
        'winner_name': state['players'][winners[0]]['name'] if winners and winners[0] in state['players'] else None,
    }, room=room['code'])
    broadcast_state(state, room['code'])


@socketio.on('halfit_submit_cut')
def on_halfit_submit_cut(data=None):
    """Client sends two points defining a straight cut line."""
    sid = request.sid
    if not isinstance(data, dict) or not _halfit:
        return
    try:
        p1 = (float(data['p1'][0]), float(data['p1'][1]))
        p2 = (float(data['p2'][0]), float(data['p2'][1]))
    except (KeyError, TypeError, ValueError):
        return
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'halfit':
            return
        if state.get('phase') != 'halfit_round':
            return
        h = state.get('halfit') or {}
        if sid in h.get('round_cuts', {}):
            return   # already cut this round
        shape = h.get('current_shape')
        if not shape:
            return
        score = _halfit.score_cut(
            shape['vertices'], shape['density_per_unit_area'],
            p1, p2, h['mode'], h.get('current_target_g'))
        h['round_cuts'][sid] = {'p1': p1, 'p2': p2, 'score': score}
        h['totals_grams_off'][sid] = round(
            h.get('totals_grams_off', {}).get(sid, 0) + score['grams_off'], 2)
        broadcast_state(state, code)
        # End the round early if everyone has submitted
        human_sids = [s for s, p in state['players'].items() if not p.get('is_bot')]
        if all(s in h['round_cuts'] for s in human_sids):
            halfit_end_round(room)


# =========================================================================
# ANGLE — protractor estimation game
#   Computer shows a target angle (e.g. 50 degrees). Each player drags a
#   rotating arm. The angle of their arm (measured from the fixed baseline,
#   0-180 degrees) is compared to the target. Closest wins the round. Score
#   = degrees off, lower is better. Sum across rounds = match total.
#
#   Server-authoritative: the target is generated and the scoring is done on
#   the server so a client can't fake a perfect answer.
# =========================================================================

ANGLE_ROUND_SECONDS = 20       # time to set an angle each round
ANGLE_ROUND_END_SECONDS = 5    # result screen duration before next round


def angle_pick_target(difficulty: str, rng: random.Random = None) -> int:
    """Pick a target angle in degrees.
    easy   = multiples of 10, range 20-160
    medium = multiples of 5, range 10-170
    hard   = any whole number, range 5-175
    """
    if rng is None:
        rng = random.Random()
    if difficulty == 'easy':
        return rng.choice(list(range(20, 161, 10)))
    elif difficulty == 'medium':
        return rng.choice(list(range(10, 171, 5)))
    else:
        return rng.randint(5, 175)


def angle_init_match(state: dict, difficulty: str, total_rounds: int):
    """Reset state for a new Angle match."""
    state['phase'] = 'angle_round'
    state['game_type'] = 'angle'
    state['angle'] = {
        'difficulty': difficulty,
        'round_number': 0,
        'total_rounds': max(1, min(20, int(total_rounds))),
        'current_target': None,
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_answers': {},        # sid -> {angle, degrees_off, bullseye}
        'totals_degrees_off': {sid: 0.0 for sid, p in state['players'].items()
                               if not p.get('is_bot')},
    }
    state['round_number'] = 0


def angle_start_round(room: dict):
    state = room['state']
    a = state.get('angle')
    if not a:
        return
    a['round_number'] += 1
    state['round_number'] = a['round_number']
    a['current_target'] = angle_pick_target(a['difficulty'])
    a['round_started_at'] = time.time()
    a['round_deadline'] = time.time() + ANGLE_ROUND_SECONDS
    a['round_answers'] = {}
    state['phase'] = 'angle_round'
    broadcast_state(state, room['code'])
    expected_round = a['round_number']
    code = room['code']

    def deadline_check():
        socketio.sleep(ANGLE_ROUND_SECONDS + 0.5)
        with room['lock']:
            cur_state = room['state']
            cur_a = cur_state.get('angle') or {}
            if (cur_a.get('round_number') == expected_round
                    and cur_state.get('phase') == 'angle_round'):
                angle_end_round(room)
    socketio.start_background_task(deadline_check)


def angle_end_round(room: dict):
    state = room['state']
    a = state.get('angle')
    if not a or state.get('phase') != 'angle_round':
        return
    state['phase'] = 'angle_round_end'
    # Players who already submitted had their total updated in on_angle_submit.
    # Here we ONLY add the penalty for players who never answered, to avoid
    # double-counting.
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        if sid not in a['round_answers']:
            a['round_answers'][sid] = {
                'angle': None, 'degrees_off': 180.0,
                'bullseye': False, 'no_answer': True
            }
            a['totals_degrees_off'][sid] = round(
                a['totals_degrees_off'].get(sid, 0) + 180.0, 2)
    broadcast_state(state, room['code'])
    expected_round = a['round_number']
    code = room['code']

    def advance():
        socketio.sleep(ANGLE_ROUND_END_SECONDS)
        with room['lock']:
            cur_state = room['state']
            cur_a = cur_state.get('angle') or {}
            if cur_state.get('phase') != 'angle_round_end':
                return
            if cur_a.get('round_number') != expected_round:
                return
            if cur_a['round_number'] >= cur_a['total_rounds']:
                angle_end_match(room)
            else:
                angle_start_round(room)
    socketio.start_background_task(advance)


def angle_end_match(room: dict):
    state = room['state']
    a = state.get('angle')
    if not a:
        return
    state['phase'] = 'game_over'
    totals = a['totals_degrees_off']
    ranking = []
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        ranking.append({
            'sid': sid,
            'name': p['name'],
            'user_id': p.get('user_id'),
            'total_degrees_off': round(totals.get(sid, 0), 2),
        })
    ranking.sort(key=lambda r: r['total_degrees_off'])
    winners = [ranking[0]['sid']] if ranking else []
    is_multi = len([s for s, p in state['players'].items()
                    if not p.get('is_bot')]) >= 2
    for r in ranking:
        try:
            sid = r['sid']
            wp = get_profile(r['name'], user_id=r.get('user_id'))
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            if sid in winners and is_multi:
                wp['wins'] = (wp.get('wins', 0) or 0) + 1
                wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                    wp['best_streak'] = wp['current_streak']
                grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='angle',
                         coins=10 * MP_COIN_MULTIPLIER)
            elif is_multi:
                wp['losses'] = (wp.get('losses', 0) or 0) + 1
                wp['current_streak'] = 0
            else:
                grant_xp(wp, 15, game_type='angle', coins=3)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[angle_end_match] xp/loss failed: {e}")
    socketio.emit('game_over', {
        'game_type': 'angle',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']],
        'winner_sid': winners[0] if winners else None,
        'winner_name': state['players'][winners[0]]['name'] if winners and winners[0] in state['players'] else None,
    }, room=room['code'])
    broadcast_state(state, room['code'])


@socketio.on('angle_submit')
def on_angle_submit(data=None):
    """Client sends their chosen angle in degrees (0-180 from baseline)."""
    sid = request.sid
    if not isinstance(data, dict):
        return
    raw = data.get('angle')
    try:
        chosen = float(raw)
    except (TypeError, ValueError):
        return
    # Clamp to valid protractor range
    if chosen < 0:
        chosen = 0.0
    if chosen > 180:
        chosen = 180.0
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'angle':
            return
        if state.get('phase') != 'angle_round':
            return
        a = state.get('angle') or {}
        if sid in a.get('round_answers', {}):
            return   # already answered this round
        target = a.get('current_target')
        if target is None:
            return
        off = abs(chosen - target)
        a['round_answers'][sid] = {
            'angle': round(chosen, 1),
            'degrees_off': round(off, 1),
            'bullseye': off <= 1.0
        }
        a['totals_degrees_off'][sid] = round(
            a.get('totals_degrees_off', {}).get(sid, 0) + off, 2)
        broadcast_state(state, code)
        human_sids = [s for s, p in state['players'].items() if not p.get('is_bot')]
        if all(s in a['round_answers'] for s in human_sids):
            angle_end_round(room)


# =========================================================================
# PICTIONARY — emoji-rebus guessing game
#   Everyone sees the same emoji puzzle. Players type guesses; the server
#   checks them forgivingly (plurals, tenses, spacing, typos all pass).
#   Scoring per round: a correct guess earns points = base - (hints_used *
#   penalty), with a small speed bonus for answering before others. Players
#   get up to 3 hints each per round (costing points). Wrong guesses are
#   allowed unlimited times within the round timer. Highest total wins.
#
#   Unlimited non-repeating: a shuffled puzzle order is stored per match;
#   when exhausted it reshuffles.
# =========================================================================

PICT_ROUND_SECONDS = 40        # time to guess each puzzle
PICT_ROUND_END_SECONDS = 5     # result screen duration
PICT_BASE_POINTS = 100         # points for a correct answer with no hints
PICT_HINT_PENALTY = 20         # points lost per hint used
PICT_SPEED_BONUS = 30          # extra for being first correct (decays by order)
PICT_MAX_HINTS = 3

try:
    import pictionary_data as _pict
except ImportError:
    _pict = None


def pict_init_match(state: dict, total_rounds: int, difficulty: str = 'mixed'):
    """Reset state for a new Pictionary match."""
    state['phase'] = 'pict_round'
    state['game_type'] = 'pictionary'
    order = _pict.make_shuffled_order(difficulty=difficulty) if _pict else []
    state['pict'] = {
        'difficulty': difficulty,
        'round_number': 0,
        'total_rounds': max(1, min(20, int(total_rounds))),
        'order': order,            # shuffled bank indices
        'order_pos': 0,            # how far we've served
        'current': None,           # public puzzle data (NO answer leaked)
        '_answer': None,           # server-only answer
        '_alternates': None,       # server-only accepted spellings
        'round_started_at': 0.0,
        'round_deadline': 0.0,
        'round_results': {},       # sid -> {solved, points, hints_used, order_solved}
        'hints_used': {},          # sid -> int (this round)
        'solve_order': [],         # sids in order they solved (for speed bonus)
        'totals_points': {sid: 0 for sid, p in state['players'].items()
                          if not p.get('is_bot')},
    }
    state['round_number'] = 0


def pict_start_round(room: dict):
    state = room['state']
    pc = state.get('pict')
    if not pc or not _pict:
        return
    pc['round_number'] += 1
    state['round_number'] = pc['round_number']
    # Pull next puzzle from the shuffled order; reshuffle if exhausted
    if pc['order_pos'] >= len(pc['order']):
        pc['order'] = _pict.make_shuffled_order(
            difficulty=pc.get('difficulty', 'mixed'))
        pc['order_pos'] = 0
    bank_idx = pc['order'][pc['order_pos']]
    pc['order_pos'] += 1
    puzzle = _pict.get_puzzle(bank_idx)
    # Public view: emoji + category + word count + hints, but NEVER the answer
    pc['current'] = {
        'emoji': puzzle['emoji'],
        'category': puzzle['category'],
        'word_count': puzzle['word_count'],
        'hints': puzzle['hints'],          # client only reveals on request
    }
    pc['_answer'] = puzzle['answer']
    pc['_alternates'] = puzzle['alternates']
    pc['round_started_at'] = time.time()
    pc['round_deadline'] = time.time() + PICT_ROUND_SECONDS
    pc['round_results'] = {}
    pc['hints_used'] = {}
    pc['solve_order'] = []
    state['phase'] = 'pict_round'
    broadcast_state(state, room['code'])
    expected_round = pc['round_number']
    code = room['code']

    def deadline_check():
        socketio.sleep(PICT_ROUND_SECONDS + 0.5)
        with room['lock']:
            cur_state = room['state']
            cur_pc = cur_state.get('pict') or {}
            if (cur_pc.get('round_number') == expected_round
                    and cur_state.get('phase') == 'pict_round'):
                pict_end_round(room)
    socketio.start_background_task(deadline_check)


def pict_public_state(pc: dict) -> dict:
    """Strip server-only fields (the answer!) before broadcasting."""
    if not pc:
        return None
    return {
        'round_number': pc.get('round_number'),
        'total_rounds': pc.get('total_rounds'),
        'current': pc.get('current'),
        'round_started_at': pc.get('round_started_at'),
        'round_deadline': pc.get('round_deadline'),
        'round_results': pc.get('round_results'),
        'hints_used': pc.get('hints_used'),
        'solve_order': pc.get('solve_order'),
        'totals_points': pc.get('totals_points'),
        # Reveal the answer ONLY when the round has ended
        'revealed_answer': pc.get('_answer') if pc.get('_revealed') else None,
    }


def pict_end_round(room: dict):
    state = room['state']
    pc = state.get('pict')
    if not pc or state.get('phase') != 'pict_round':
        return
    state['phase'] = 'pict_round_end'
    pc['_revealed'] = True          # now safe to show the answer
    # Players who never solved get a 0-point result recorded
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        if sid not in pc['round_results']:
            pc['round_results'][sid] = {
                'solved': False, 'points': 0,
                'hints_used': pc['hints_used'].get(sid, 0),
                'order_solved': None
            }
    broadcast_state(state, room['code'])
    expected_round = pc['round_number']
    code = room['code']

    def advance():
        socketio.sleep(PICT_ROUND_END_SECONDS)
        with room['lock']:
            cur_state = room['state']
            cur_pc = cur_state.get('pict') or {}
            if cur_state.get('phase') != 'pict_round_end':
                return
            if cur_pc.get('round_number') != expected_round:
                return
            cur_pc['_revealed'] = False
            if cur_pc['round_number'] >= cur_pc['total_rounds']:
                pict_end_match(room)
            else:
                pict_start_round(room)
    socketio.start_background_task(advance)


def pict_end_match(room: dict):
    state = room['state']
    pc = state.get('pict')
    if not pc:
        return
    state['phase'] = 'game_over'
    totals = pc['totals_points']
    ranking = []
    for sid, p in state['players'].items():
        if p.get('is_bot'):
            continue
        ranking.append({
            'sid': sid,
            'name': p['name'],
            'user_id': p.get('user_id'),
            'total_points': totals.get(sid, 0),
        })
    # Highest points wins (descending)
    ranking.sort(key=lambda r: -r['total_points'])
    winners = [ranking[0]['sid']] if ranking else []
    is_multi = len([s for s, p in state['players'].items()
                    if not p.get('is_bot')]) >= 2
    for r in ranking:
        try:
            sid = r['sid']
            wp = get_profile(r['name'], user_id=r.get('user_id'))
            wp['games_played'] = (wp.get('games_played', 0) or 0) + 1
            if sid in winners and is_multi:
                wp['wins'] = (wp.get('wins', 0) or 0) + 1
                wp['current_streak'] = (wp.get('current_streak', 0) or 0) + 1
                if wp['current_streak'] > (wp.get('best_streak', 0) or 0):
                    wp['best_streak'] = wp['current_streak']
                grant_xp(wp, 50 * MP_XP_MULTIPLIER, game_type='pictionary',
                         coins=10 * MP_COIN_MULTIPLIER)
            elif is_multi:
                wp['losses'] = (wp.get('losses', 0) or 0) + 1
                wp['current_streak'] = 0
            else:
                grant_xp(wp, 15, game_type='pictionary', coins=3)
            mark_profiles_dirty()
        except Exception as e:
            print(f"[pict_end_match] xp/loss failed: {e}")
    socketio.emit('game_over', {
        'game_type': 'pictionary',
        'final_ranking': ranking,
        'winners': [{'sid': w, 'name': state['players'][w]['name']}
                    for w in winners if w in state['players']],
        'winner_sid': winners[0] if winners else None,
        'winner_name': state['players'][winners[0]]['name'] if winners and winners[0] in state['players'] else None,
    }, room=room['code'])
    broadcast_state(state, room['code'])


@socketio.on('pict_guess')
def on_pict_guess(data=None):
    """Player submits a text guess. Forgiving match against the hidden answer."""
    sid = request.sid
    if not isinstance(data, dict) or not _pict:
        return
    guess = data.get('guess')
    if not isinstance(guess, str) or not guess.strip():
        return
    if len(guess) > 100:
        guess = guess[:100]
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'pictionary':
            return
        if state.get('phase') != 'pict_round':
            return
        pc = state.get('pict') or {}
        # Already solved this round? Ignore further guesses.
        if sid in pc.get('round_results', {}) and pc['round_results'][sid].get('solved'):
            return
        correct = _pict.check_answer(guess, pc.get('_answer', ''),
                                     pc.get('_alternates'))
        if not correct:
            # Tell only this player their guess was wrong (don't leak to others)
            emit('pict_guess_result', {'correct': False, 'guess': guess})
            return
        # Correct! Compute points.
        hints = pc['hints_used'].get(sid, 0)
        order_solved = len(pc['solve_order'])     # 0 = first to solve
        pc['solve_order'].append(sid)
        speed_bonus = max(0, PICT_SPEED_BONUS - order_solved * 10)
        points = max(10, PICT_BASE_POINTS - hints * PICT_HINT_PENALTY + speed_bonus)
        pc['round_results'][sid] = {
            'solved': True, 'points': points,
            'hints_used': hints, 'order_solved': order_solved
        }
        pc['totals_points'][sid] = pc['totals_points'].get(sid, 0) + points
        # Tell the solver they got it (with their answer so client can show it)
        emit('pict_guess_result', {'correct': True, 'points': points,
                                    'answer': pc.get('_answer')})
        broadcast_state(state, code)
        # If ALL humans have solved, end the round early
        human_sids = [s for s, p in state['players'].items() if not p.get('is_bot')]
        if all(s in pc['round_results'] and pc['round_results'][s].get('solved')
               for s in human_sids):
            pict_end_round(room)


@socketio.on('pict_use_hint')
def on_pict_use_hint(data=None):
    """Player requests their next hint (max PICT_MAX_HINTS per round)."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'pictionary':
            return
        if state.get('phase') != 'pict_round':
            return
        pc = state.get('pict') or {}
        # Solved players don't need hints
        if sid in pc.get('round_results', {}) and pc['round_results'][sid].get('solved'):
            return
        used = pc['hints_used'].get(sid, 0)
        if used >= PICT_MAX_HINTS:
            emit('pict_hint', {'exhausted': True})
            return
        cur = pc.get('current') or {}
        hints = cur.get('hints') or []
        if used < len(hints):
            hint_text = hints[used]
        else:
            hint_text = "No more hints"
        pc['hints_used'][sid] = used + 1
        emit('pict_hint', {'hint': hint_text, 'hint_number': used + 1,
                           'remaining': PICT_MAX_HINTS - (used + 1)})
        broadcast_state(state, code)


@socketio.on('ts_stop_timer')
def on_ts_stop_timer(data=None):
    """Client tapped stop. Send the elapsed milliseconds to the server."""
    sid = request.sid
    if not isinstance(data, dict):
        return
    elapsed_ms = data.get('elapsed_ms')
    if elapsed_ms is None:
        return
    try:
        elapsed_ms = float(elapsed_ms)
    except Exception:
        return
    # Reject obviously broken values
    if elapsed_ms < 50 or elapsed_ms > 30000:
        emit('error_msg', {'msg': 'Time out of range'})
        return
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        if state.get('game_type') != 'timeshot':
            return
        if state.get('phase') != 'ts_round':
            return
        ts_record_attempt(room, sid, elapsed_ms)


# ---- Presence & Direct Challenge API ----

@app.route('/api/profile/rename', methods=['POST'])
def api_profile_rename():
    """Rename a player's profile (move their XP/wins/etc. to a new name key)
    and optionally set their avatar color. Called by the edit-profile modal.

    Since profiles are keyed by user_id (not display name), two players are
    allowed to choose the same display name — each keeps their own progress.
    """
    data = request.get_json(silent=True) or {}
    user_id = (data.get('user_id') or '').strip()
    new_name = (data.get('new_name') or '').strip()
    avatar_color = (data.get('avatar_color') or '').strip()
    avatar_image = (data.get('avatar_image') or '').strip()    # optional data URL

    if not new_name:
        return jsonify({'ok': False, 'msg': 'Name cannot be empty'}), 400
    if len(new_name) > 20:
        return jsonify({'ok': False, 'msg': 'Name must be 20 chars or fewer'}), 400
    if not user_id or not user_id.startswith(('u_', 'g_')):
        return jsonify({'ok': False, 'msg': 'Missing or invalid user_id'}), 400

    # Avatar image safety: only accept reasonably-sized data URLs (< 200KB)
    if avatar_image and not (avatar_image.startswith('data:image/')
                              and len(avatar_image) < 200_000):
        return jsonify({'ok': False, 'msg': 'Image too large or unsupported format'}), 400

    p = get_profile(new_name, user_id=user_id)
    with PROFILES_LOCK:
        p['name'] = new_name
        if avatar_color:
            p['avatar_color'] = avatar_color
        if avatar_image:
            p['avatar_image'] = avatar_image
        elif 'avatar_image' in data and not avatar_image:
            # Explicit empty string removes the image
            p.pop('avatar_image', None)
    mark_profiles_dirty()

    # Keep the SID_TO_USER name in sync so the online list updates live.
    with SID_TO_USER_LOCK:
        sid = USER_TO_SID.get(user_id)
        if sid and sid in SID_TO_USER:
            SID_TO_USER[sid]['name'] = new_name

    # Sync the football league display name if this manager is on the table.
    try:
        lg = _fb_load_league()
        if user_id in lg:
            lg[user_id]['name'] = new_name
            _storage.kv_set_obj(_fbleague.LEAGUE_KEY, lg)
    except Exception:
        pass

    return jsonify({'ok': True, 'name': new_name,
                    'avatar_color': p.get('avatar_color'),
                    'has_image': bool(p.get('avatar_image'))})


@app.route('/api/online')
def api_online_list():
    """Return list of currently online users with their status.
    Used by the 'Players Online' menu tab."""
    requester_uid = (request.args.get('me') or '').strip()
    out = []
    with SID_TO_USER_LOCK:
        items = list(SID_TO_USER.items())
    for sid, info in items:
        uid = info.get('user_id')
        if not uid:
            continue
        if uid == requester_uid:
            continue   # don't list yourself
        st = get_user_status(sid)
        # Fetch avatar from profile so the online list can render it
        avatar_color = None
        avatar_image = None
        try:
            prof = get_profile(info.get('name', ''), user_id=uid)
            avatar_color = prof.get('avatar_color')
            avatar_image = prof.get('avatar_image')
        except Exception:
            pass
        out.append({
            'user_id': uid,
            'name': info.get('name', '') or '(anonymous)',
            'status': st['status'],
            'game': st['game'],
            'avatar_color': avatar_color,
            'avatar_image': avatar_image
        })
    # Sort: free players first, then busy
    free_first = {'idle': 0, 'in_solo': 1, 'in_lobby': 2, 'in_1v1': 3, 'in_group': 4}
    out.sort(key=lambda u: (free_first.get(u['status'], 9), u['name'].lower()))
    return jsonify({'users': out, 'count': len(out)})


@socketio.on('challenge_send')
def on_challenge_send(data=None):
    """Player A challenges Player B to a face-off.
    Server forwards the challenge to B's socket and tracks it briefly."""
    sid_from = request.sid
    if not isinstance(data, dict):
        return
    target_uid = (data.get('target_user_id') or '').strip()
    game = (data.get('game') or 'guessduel').strip()
    if game not in ('guessduel', 'wordchain', 'footymind', 'trivia', 'geo',
                    'oneshot', 'timeshot', 'geography', 'halfit', 'angle',
                    'pictionary', 'football'):
        emit('challenge_error', {'msg': 'Unknown game'})
        return
    with SID_TO_USER_LOCK:
        sender = SID_TO_USER.get(sid_from)
        target_sid = USER_TO_SID.get(target_uid)
    if not sender:
        emit('challenge_error', {'msg': 'You must enter a name first'})
        return
    if not target_sid:
        emit('challenge_error', {'msg': 'Player is no longer online'})
        return
    sender_status = get_user_status(sid_from)
    if sender_status['status'] == 'in_1v1' or sender_status['status'] == 'in_group':
        emit('challenge_error', {'msg': 'Finish your current match first'})
        return
    # Build challenge record
    challenge_id = 'ch_' + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    now = time.time()
    with CHALLENGE_LOCK:
        # Drop stale challenges from this sender
        for cid, ch in list(PENDING_CHALLENGES.items()):
            if ch['from_sid'] == sid_from and (now - ch['created_at']) < CHALLENGE_TTL:
                # Already pending — let the new one supersede
                PENDING_CHALLENGES.pop(cid, None)
        PENDING_CHALLENGES[challenge_id] = {
            'from_sid': sid_from,
            'from_user_id': sender['user_id'],
            'from_name': sender.get('name', ''),
            'to_sid': target_sid,
            'to_user_id': target_uid,
            'game': game,
            'created_at': now
        }
    print(f"[challenge] {sender.get('name')!r} -> {target_uid[:10]}... game={game} id={challenge_id[:8]}")
    # Tell the target
    socketio.emit('challenge_received', {
        'challenge_id': challenge_id,
        'from_name': sender.get('name', '(anonymous)'),
        'from_user_id': sender['user_id'],
        'game': game,
        'ttl': CHALLENGE_TTL
    }, room=target_sid)
    # Confirm to sender
    emit('challenge_sent', {'challenge_id': challenge_id, 'ttl': CHALLENGE_TTL})

    # Auto-expire
    def expire():
        socketio.sleep(CHALLENGE_TTL + 1)
        with CHALLENGE_LOCK:
            ch = PENDING_CHALLENGES.pop(challenge_id, None)
        if ch:
            socketio.emit('challenge_expired', {'challenge_id': challenge_id}, room=ch['from_sid'])
            socketio.emit('challenge_expired', {'challenge_id': challenge_id}, room=ch['to_sid'])
    socketio.start_background_task(expire)


@socketio.on('challenge_accept')
def on_challenge_accept(data=None):
    """Target accepts a challenge. Server creates a face-off room and joins both players."""
    sid = request.sid
    if not isinstance(data, dict):
        return
    challenge_id = (data.get('challenge_id') or '').strip()
    with CHALLENGE_LOCK:
        ch = PENDING_CHALLENGES.pop(challenge_id, None)
    if not ch:
        emit('challenge_error', {'msg': 'Challenge expired or invalid'})
        return
    if ch['to_sid'] != sid:
        emit('challenge_error', {'msg': 'Not your challenge to accept'})
        return
    # Create the face-off room
    code = create_room(ch['game'], 'faceoff')
    print(f"[challenge] accepted id={challenge_id[:8]} -> room {code}")
    # Tell both clients to join the room
    socketio.emit('challenge_accepted', {
        'challenge_id': challenge_id,
        'code': code,
        'game': ch['game']
    }, room=ch['from_sid'])
    socketio.emit('challenge_accepted', {
        'challenge_id': challenge_id,
        'code': code,
        'game': ch['game']
    }, room=ch['to_sid'])


@socketio.on('challenge_decline')
def on_challenge_decline(data=None):
    sid = request.sid
    if not isinstance(data, dict):
        return
    challenge_id = (data.get('challenge_id') or '').strip()
    with CHALLENGE_LOCK:
        ch = PENDING_CHALLENGES.pop(challenge_id, None)
    if not ch:
        return
    print(f"[challenge] declined id={challenge_id[:8]}")
    socketio.emit('challenge_declined', {'challenge_id': challenge_id},
                  room=ch['from_sid'])


# ---- Profile / XP API ----

# Server-defined XP rules per game. Client tells us 'this happened', we look
# up the XP amount. Prevents trivial cheating by clients claiming arbitrary
# rewards.
XP_RULES = {
    # (game, event) -> (xp, coins)
    ('oneshot', 'solved_1'):  (100, 10),
    ('oneshot', 'solved_2'):  (60,  8),
    ('oneshot', 'solved_3'):  (40,  6),
    ('oneshot', 'solved_4'):  (25,  4),
    ('oneshot', 'solved_5'):  (15,  3),
    ('oneshot', 'solved_6'):  (10,  2),
    ('oneshot', 'failed'):    (0,   0),

    # FootyMind: client reports correct answers and the difficulty
    ('footymind', 'correct_easy'):   (3, 1),
    ('footymind', 'correct_medium'): (5, 1),
    ('footymind', 'correct_hard'):   (8, 2),
    ('footymind', 'round_50pct'):    (15, 3),
    ('footymind', 'round_70pct'):    (30, 6),
    ('footymind', 'round_perfect'):  (60, 15),

    # TriviaRush
    ('trivia', 'correct'):       (2, 1),
    ('trivia', 'round_50pct'):   (15, 3),
    ('trivia', 'round_70pct'):   (30, 6),
    ('trivia', 'round_perfect'): (60, 15),

    # Geography
    ('geo', 'correct'):       (3, 1),
    ('geo', 'round_50pct'):   (15, 3),
    ('geo', 'round_70pct'):   (30, 6),
    ('geo', 'round_perfect'): (60, 15),

    # GuessDuel / WordChain — awarded server-side in game_over handlers
    ('guessduel', 'win'):   (50, 10),
    ('guessduel', 'crack'): (5,  1),
    ('guessduel', 'round_survived'): (2, 0),
    ('wordchain', 'win'):   (50, 10),
    ('wordchain', 'word'):  (1,  0),

    # TimeShot — stop the clock at a target time
    ('timeshot', 'win'):           (50, 10),
    ('timeshot', 'round_perfect'): (10, 2),    # within 0.05s
    ('timeshot', 'round_close'):   (3, 1),     # within 0.25s
}

# Multiplayer multiplier — beating a real person is worth more than a bot
MP_XP_MULTIPLIER = 3
MP_COIN_MULTIPLIER = 3


@app.route('/api/profile/<name>')
def api_profile_get(name):
    """Read a profile by name (or uid query). Used to render the home profile
    card. When a uid is provided, look up by user_id key — this is the right
    way to fetch your own profile since two display names may now collide."""
    uid = (request.args.get('uid') or '').strip() or None
    p = get_profile(name, user_id=uid)
    return jsonify({
        'name': p.get('name', name),
        'xp': p.get('xp', 0),
        'level': p.get('level', 1),
        'coins': p.get('coins', 0),
        'title': title_for_level(p.get('level', 1)),
        'xp_for_current': xp_for_level(p.get('level', 1)),
        'xp_for_next': xp_for_level(p.get('level', 1) + 1),
        'games_played': p.get('games_played', 0),
        'wins': p.get('wins', 0),
        'losses': p.get('losses', 0),
        'current_streak': p.get('current_streak', 0),
        'best_streak': p.get('best_streak', 0),
        'avatar_color': p.get('avatar_color'),
        'avatar_image': p.get('avatar_image'),
        'achievements': p.get('achievements', []),
        'xp_by_game': p.get('xp_by_game', {})
    })


@app.route('/api/profile/award', methods=['POST'])
def api_profile_award():
    """Award XP / coins for a game event. The server decides how much based
    on the (game, event) pair so a client can't claim arbitrary rewards."""
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    user_id = (data.get('user_id') or '').strip() or None
    game = (data.get('game') or '').strip()
    event = (data.get('event') or '').strip()
    multiplayer = bool(data.get('multiplayer'))
    if not name:
        return jsonify({'error': 'name required'}), 400
    rule = XP_RULES.get((game, event))
    if not rule:
        return jsonify({'error': f'unknown event ({game}, {event})'}), 400
    xp, coins = rule
    if multiplayer:
        xp *= MP_XP_MULTIPLIER
        coins *= MP_COIN_MULTIPLIER
    profile = get_profile(name, user_id=user_id)
    result = grant_xp(profile, xp, game_type=game, coins=coins)
    return jsonify(result)


# =========================================================================
# ADMIN PANEL — owner-only content management at /admin
#   Lets the owner add trivia / pictionary / footy / geography content that
#   persists in Redis and merges into the live games without a redeploy.
#   Auth: a single password set via the ADMIN_PASSWORD env var. A signed
#   token cookie keeps the session. If ADMIN_PASSWORD is unset, the panel is
#   disabled (returns 503) so it can't be left wide open by accident.
# =========================================================================
import admin_content as _admin
import hmac as _hmac

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

# Google Sign-In: the OAuth Client ID. Public by design (it appears in the
# client). Read from env var, falling back to the known project Client ID so
# it works even if the env var isn't set. Token verification is done server
# side against Google, so a forged token can't impersonate anyone.
GOOGLE_CLIENT_ID = os.environ.get(
    'GOOGLE_CLIENT_ID',
    '708463902952-h14h0vaet38kd7lr0lsl3ttphrmsi0t2.apps.googleusercontent.com')
# Secret for signing the admin cookie. Derived from the password + a constant
# so it's stable across restarts without needing another env var.
_ADMIN_COOKIE_NAME = 'gr_admin'


def _admin_token() -> str:
    if not ADMIN_PASSWORD:
        return ''
    return hashlib.sha256(('gameroom-admin::' + ADMIN_PASSWORD).encode()).hexdigest()


def _admin_authed() -> bool:
    if not ADMIN_PASSWORD:
        return False
    tok = request.cookies.get(_ADMIN_COOKIE_NAME, '')
    expected = _admin_token()
    return bool(tok) and _hmac.compare_digest(tok, expected)


@app.route('/admin')
def admin_page():
    if not ADMIN_PASSWORD:
        return ("<h1>Admin disabled</h1><p>Set the ADMIN_PASSWORD environment "
                "variable to enable the admin panel.</p>"), 503
    # The page itself always renders; the client-side checks auth via /api/admin/me
    return _no_cache_html(make_response(render_template('admin.html')))


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    if not ADMIN_PASSWORD:
        return jsonify({'error': 'admin disabled'}), 503
    data = request.get_json(force=True, silent=True) or {}
    pw = data.get('password', '')
    if not pw or not _hmac.compare_digest(pw, ADMIN_PASSWORD):
        return jsonify({'ok': False, 'error': 'wrong password'}), 401
    resp = make_response(jsonify({'ok': True}))
    # httponly cookie, ~30 days
    resp.set_cookie(_ADMIN_COOKIE_NAME, _admin_token(), max_age=30*24*3600,
                    httponly=True, samesite='Lax')
    return resp


@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    resp = make_response(jsonify({'ok': True}))
    resp.delete_cookie(_ADMIN_COOKIE_NAME)
    return resp


@app.route('/api/admin/me')
def admin_me():
    return jsonify({'authed': _admin_authed(),
                    'enabled': bool(ADMIN_PASSWORD)})


@app.route('/api/admin/content/<kind>', methods=['GET'])
def admin_list(kind):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if kind not in _admin.KINDS:
        return jsonify({'error': 'bad kind'}), 400
    return jsonify({'items': _admin.list_items(kind),
                    'counts': _admin.count_all()})


@app.route('/api/admin/content/<kind>', methods=['POST'])
def admin_add(kind):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if kind not in _admin.KINDS:
        return jsonify({'error': 'bad kind'}), 400
    item = request.get_json(force=True, silent=True) or {}
    # Light server-side validation per kind so junk doesn't reach the games.
    err = _validate_admin_item(kind, item)
    if err:
        return jsonify({'error': err}), 400
    stored = _admin.add_item(kind, item)
    refresh_all_admin_content()    # take effect immediately
    return jsonify({'ok': True, 'item': stored})


@app.route('/api/admin/content/<kind>/<item_id>', methods=['DELETE'])
def admin_delete(kind, item_id):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if kind not in _admin.KINDS:
        return jsonify({'error': 'bad kind'}), 400
    ok = _admin.delete_item(kind, item_id)
    refresh_all_admin_content()
    return jsonify({'ok': ok})


def _validate_admin_item(kind, item):
    """Return an error string if the item is invalid, else None."""
    try:
        if kind == 'trivia':
            if not item.get('q'): return 'question text required'
            t = item.get('type', 'mc')
            if t == 'mc':
                opts = item.get('options') or []
                if len([o for o in opts if str(o).strip()]) < 2:
                    return 'multiple-choice needs at least 2 options'
                ai = item.get('answer')
                if ai is None or int(ai) < 0 or int(ai) >= len(opts):
                    return 'answer must be the index of a valid option'
            elif t == 'tf':
                if 'answer' not in item:
                    return 'true/false needs an answer'
            else:
                return 'type must be mc or tf'
        elif kind == 'pictionary':
            if not item.get('emoji'): return 'emoji required'
            if not item.get('answer'): return 'answer required'
        elif kind == 'footy':
            if not item.get('name'): return 'player name required'
            path = item.get('path') or []
            if len([p for p in path if len(p) == 2 and p[1]]) < 1:
                return 'at least one career step (years + club) required'
        elif kind == 'geo_flag':
            if not item.get('name'): return 'country name required'
            if not item.get('iso2') and not item.get('image_url'):
                return 'either an ISO2 code or an image URL is required'
        elif kind == 'geo_landmark':
            if not item.get('name'): return 'landmark name required'
            if not item.get('image_url'): return 'image URL required'
    except Exception as e:
        return f'invalid data: {e}'
    return None


# =========================================================================
# ADMIN — extended features: players, bulk, game toggles, announcement,
# rooms monitor, export. All require _admin_authed().
# =========================================================================

@app.route('/api/admin/players', methods=['GET'])
def admin_players():
    """List all player profiles (summary fields) for the management table."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    with PROFILES_LOCK:
        rows = []
        for key, p in PROFILES_CACHE.items():
            rows.append({
                'key': key,
                'name': p.get('name', '(unnamed)'),
                'user_id': p.get('user_id'),
                'level': p.get('level', 1),
                'xp': p.get('xp', 0),
                'coins': p.get('coins', 0),
                'games_played': p.get('games_played', 0),
                'wins': p.get('wins', 0),
                'losses': p.get('losses', 0),
                'last_played_at': p.get('last_played_at'),
            })
    rows.sort(key=lambda r: -(r['xp'] or 0))
    return jsonify({'players': rows, 'total': len(rows)})


@app.route('/api/admin/players/<path:key>/reset', methods=['POST'])
def admin_player_reset(key):
    """Reset a player's progress to a fresh profile (keeps name + user_id)."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    with PROFILES_LOCK:
        p = PROFILES_CACHE.get(key)
        if not p:
            return jsonify({'error': 'not found'}), 404
        name = p.get('name', '')
        uid = p.get('user_id')
        fresh = fresh_profile(name)
        if uid:
            fresh['user_id'] = uid
        PROFILES_CACHE[key] = fresh
    mark_profiles_dirty()
    save_profiles()
    return jsonify({'ok': True})


@app.route('/api/admin/players/<path:key>', methods=['DELETE'])
def admin_player_delete(key):
    """Delete a player profile entirely."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    with PROFILES_LOCK:
        existed = PROFILES_CACHE.pop(key, None) is not None
    if existed:
        mark_profiles_dirty()
        save_profiles()
    return jsonify({'ok': existed})


@app.route('/api/admin/bans', methods=['GET'])
def admin_bans_list():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify({'banned_names': _admin.get_settings().get('banned_names', [])})


@app.route('/api/admin/bans', methods=['POST'])
def admin_bans_add():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    banned = _admin.add_banned_name(name)
    return jsonify({'ok': True, 'banned_names': banned})


@app.route('/api/admin/bans/<path:name>', methods=['DELETE'])
def admin_bans_remove(name):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    banned = _admin.remove_banned_name(name)
    return jsonify({'ok': True, 'banned_names': banned})


@app.route('/api/admin/bulk/<kind>', methods=['POST'])
def admin_bulk(kind):
    """Bulk-add items. Body: {items:[...]} already-parsed by the client."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if kind not in _admin.KINDS:
        return jsonify({'error': 'bad kind'}), 400
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return jsonify({'error': 'no items'}), 400
    # Validate each; only add the valid ones, report the rest.
    valid, errors = [], []
    for i, it in enumerate(items):
        err = _validate_admin_item(kind, it)
        if err:
            errors.append({'index': i, 'error': err})
        else:
            valid.append(it)
    result = _admin.bulk_add(kind, valid) if valid else {'added': 0, 'failed': []}
    refresh_all_admin_content()
    return jsonify({'ok': True, 'added': result['added'],
                    'rejected': errors, 'rejected_count': len(errors)})


@app.route('/api/admin/import/<kind>', methods=['POST'])
def admin_import(kind):
    """Import a CSV/XLSX question bank. Accepts a multipart file upload."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if kind not in _admin.IMPORT_COLUMNS:
        return jsonify({'error': 'bad kind'}), 400
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'no file uploaded'}), 400
    try:
        data = f.read()
        if len(data) > 5 * 1024 * 1024:
            return jsonify({'error': 'file too large (max 5 MB)'}), 400
        result = _admin.import_spreadsheet(kind, f.filename, data)
    except Exception as e:
        return jsonify({'error': f'could not read file: {e}'}), 400
    refresh_all_admin_content()
    return jsonify({'ok': True, 'added': result['added'],
                    'rejected_count': result['rejected_count'],
                    'errors': result['errors'][:30]})


@app.route('/api/admin/template/<kind>', methods=['GET'])
def admin_template(kind):
    """Download a CSV template (with example rows) for a content kind."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    cols = _admin.IMPORT_COLUMNS.get(kind)
    if not cols:
        return jsonify({'error': 'bad kind'}), 400
    examples = {
        'trivia': [
            ['science', 'What is the largest planet in our solar system?', 'Jupiter', 'Mars', 'Earth', 'Saturn', 'Jupiter is about 11x Earth\u2019s diameter'],
            ['football', 'Which country won the 2022 World Cup?', 'Argentina', 'France', 'Brazil', 'Germany', 'Won on penalties vs France'],
        ],
        'pictionary': [
            ['\U0001F319\U0001F6B6', 'moonwalk', 'word', 'moon walk'],
            ['\U0001F525\U0001F692', 'fire truck', 'thing', ''],
        ],
        'footy': [
            ['Lionel Messi', 'Argentina', 'Forward', 'easy', 'messi, la pulga', '2004-2021:Barcelona; 2021-2023:Paris Saint-Germain; 2023-now:Inter Miami'],
            ['Steven Gerrard', 'England', 'Midfielder', 'medium', 'stevie g', '1998-2015:Liverpool; 2015-2016:LA Galaxy'],
        ],
        'geo_flag': [
            ['Japan', 'jp', '', 'easy'],
            ['Brazil', 'br', '', 'easy'],
        ],
        'geo_landmark': [
            ['Eiffel Tower', 'France', 'https://upload.wikimedia.org/wikipedia/commons/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg', 'easy'],
            ['Great Wall', 'China', 'https://upload.wikimedia.org/wikipedia/commons/2/23/The_Great_Wall_of_China_at_Jinshanling-edit.jpg', 'medium'],
        ],
    }
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for row in examples.get(kind, []):
        w.writerow(row)
    resp = make_response('\ufeff' + buf.getvalue())  # BOM so Excel opens UTF-8 cleanly
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=gameroom_template_{kind}.csv'
    return resp
ALL_GAME_KEYS = ['guessduel', 'wordchain', 'oneshot', 'footymind', 'trivia',
                 'geography', 'timeshot', 'halfit', 'angle', 'pictionary']


@app.route('/api/admin/games', methods=['GET'])
def admin_games_list():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    disabled = _admin.get_settings().get('disabled_games', [])
    return jsonify({'games': ALL_GAME_KEYS, 'disabled': disabled})


@app.route('/api/admin/games/<game_key>', methods=['POST'])
def admin_games_toggle(game_key):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    if game_key not in ALL_GAME_KEYS:
        return jsonify({'error': 'unknown game'}), 400
    data = request.get_json(force=True, silent=True) or {}
    disabled = bool(data.get('disabled'))
    new_list = _admin.set_game_disabled(game_key, disabled)
    return jsonify({'ok': True, 'disabled': new_list})


# ---- Announcement ----
@app.route('/api/admin/announcement', methods=['GET'])
def admin_announcement_get():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify(_admin.get_settings().get('announcement', {'text': '', 'enabled': False}))


@app.route('/api/admin/announcement', methods=['POST'])
def admin_announcement_set():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(force=True, silent=True) or {}
    ann = _admin.set_announcement(data.get('text', ''), data.get('enabled', False))
    return jsonify({'ok': True, 'announcement': ann})


# ---- Live rooms monitor ----
@app.route('/api/admin/rooms', methods=['GET'])
def admin_rooms_list():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    now = time.time()
    rows = []
    with ROOMS_DICT_LOCK:
        for code, room in ROOMS.items():
            state = room.get('state', {}) or {}
            players = state.get('players', {}) or {}
            humans = [p for p in players.values() if not p.get('is_bot')]
            rows.append({
                'code': code,
                'game_type': state.get('game_type', '?'),
                'mode': state.get('mode_hint', '?'),
                'phase': state.get('phase', '?'),
                'players': len(humans),
                'player_names': [p.get('name', '?') for p in humans][:8],
                'age_sec': int(now - room.get('created_at', now)),
                'idle_sec': int(now - room.get('last_activity_at', now)),
            })
    rows.sort(key=lambda r: r['idle_sec'])
    return jsonify({'rooms': rows, 'total': len(rows)})


@app.route('/api/admin/rooms/<code>', methods=['DELETE'])
def admin_rooms_close(code):
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    code = (code or '').upper()
    room = get_room(code)
    if not room:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    try:
        socketio.emit('room_closed', {'msg': 'This room was closed by an admin.'},
                      room=code)
    except Exception:
        pass
    delete_room(code)
    return jsonify({'ok': True})


# ---- Export / backup ----
@app.route('/api/admin/export', methods=['GET'])
def admin_export():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    with PROFILES_LOCK:
        profiles = dict(PROFILES_CACHE)
    content = {k: _admin.list_items(k) for k in _admin.KINDS}
    payload = {
        'exported_at': time.time(),
        'version': 'v48',
        'profiles': profiles,
        'admin_content': content,
        'settings': _admin.get_settings(),
    }
    resp = make_response(jsonify(payload))
    resp.headers['Content-Disposition'] = 'attachment; filename=gameroom_backup.json'
    return resp


# =========================================================================
# PUBLIC endpoints the main app reads (no auth) — announcement + game list.
# Fail-open: if these error, the client just shows everything / no banner.
# =========================================================================

@app.route('/api/public/config', methods=['GET'])
def public_config():
    try:
        s = _admin.get_settings()
        ann = s.get('announcement', {})
        return jsonify({
            'disabled_games': s.get('disabled_games', []),
            'announcement': {
                'text': ann.get('text', '') if ann.get('enabled') else '',
                'enabled': bool(ann.get('enabled')) and bool(ann.get('text')),
            },
            'google_client_id': GOOGLE_CLIENT_ID,
        })
    except Exception:
        return jsonify({'disabled_games': [], 'announcement': {'text': '', 'enabled': False},
                        'google_client_id': GOOGLE_CLIENT_ID})


@app.route('/api/auth/google', methods=['POST'])
def auth_google():
    """Verify a Google ID token (sent by the Sign-in-with-Google button) and
    return a stable identity the client uses as its user_id. The profile is
    keyed by the Google account's unique 'sub', so progress follows the user
    across devices/browsers when signed in. Guests are unaffected.
    """
    data = request.get_json(force=True, silent=True) or {}
    token = data.get('credential') or data.get('token') or ''
    if not token:
        return jsonify({'ok': False, 'error': 'no token'}), 400
    try:
        from google.oauth2 import id_token as _gid
        from google.auth.transport import requests as _greq
        info = _gid.verify_oauth2_token(token, _greq.Request(), GOOGLE_CLIENT_ID)
        # info contains verified fields: sub (stable id), email, name, picture
        sub = info.get('sub')
        if not sub:
            return jsonify({'ok': False, 'error': 'invalid token'}), 401
        email = info.get('email', '')
        name = info.get('name') or (email.split('@')[0] if email else 'Player')
        picture = info.get('picture', '')
        user_id = 'g_' + sub      # 'g_' prefix marks a Google-authed identity
        # Ensure a profile exists and is keyed by this stable id.
        p = get_profile(name[:20], user_id=user_id)
        # Backfill email + google picture on first sign-in (don't overwrite a
        # custom avatar the user may have chosen).
        if email and not p.get('email'):
            p['email'] = email
        if picture and not p.get('avatar_image'):
            p['avatar_image'] = picture
        p['auth_provider'] = 'google'
        mark_profiles_dirty()
        return jsonify({
            'ok': True,
            'user_id': user_id,
            'name': p.get('name', name)[:20],
            'email': email,
            'picture': p.get('avatar_image', ''),
        })
    except ValueError as e:
        # Token failed verification (expired, wrong audience, forged, etc.)
        print(f"[auth_google] token verification failed: {e}")
        return jsonify({'ok': False, 'error': 'token verification failed'}), 401
    except Exception as e:
        print(f"[auth_google] error: {e}")
        return jsonify({'ok': False, 'error': 'auth error'}), 500




@app.route('/api/oneshot/today')
def api_oneshot_today():
    date_str = today_str()
    info = daily_secret_for(date_str)
    # Don't reveal the secret — just confirm the date and bounds
    return jsonify({
        'date': info['date'],
        'range_min': info['range_min'],
        'range_max': info['range_max'],
        'max_guesses': 6
    })


@app.route('/api/oneshot/guess', methods=['POST'])
def api_oneshot_guess():
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    date_str = (data.get('date') or today_str()).strip()
    try:
        guess = int(data.get('guess'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid guess'}), 400
    info = daily_secret_for(date_str)
    if guess < info['range_min'] or guess > info['range_max']:
        return jsonify({'error': f"Guess must be {info['range_min']}-{info['range_max']}"}), 400
    secret = info['secret']
    if guess == secret:
        feedback = 'correct'
    elif guess < secret:
        feedback = 'higher'
    else:
        feedback = 'lower'
    return jsonify({
        'guess': guess,
        'feedback': feedback,
        'secret': secret if feedback == 'correct' else None
    })


@app.route('/api/oneshot/reveal', methods=['POST'])
def api_oneshot_reveal():
    """Called when player runs out of guesses, to reveal answer."""
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    date_str = (data.get('date') or today_str()).strip()
    info = daily_secret_for(date_str)
    return jsonify({'date': date_str, 'secret': info['secret']})


# ---- FlagDuel API ----

@app.route('/api/flagduel/round')
def api_flagduel_round():
    """Returns one country/flag pair for the requested difficulty."""
    diff = (request.args.get('difficulty') or 'easy').lower()
    pool = COUNTRIES_EASY if diff == 'easy' else \
           COUNTRIES_MEDIUM if diff == 'medium' else \
           COUNTRIES_HARD
    # Generate a set of 10 unique flags for a "round"
    n = int(request.args.get('n', 10))
    n = max(1, min(20, n))
    sample = random.sample(pool, min(n, len(pool)))
    out = [{'country': c, 'flag': f} for (c, f) in sample]
    return jsonify({'difficulty': diff, 'flags': out})


@app.route('/api/flagduel/check', methods=['POST'])
def api_flagduel_check():
    """Check if a guess matches a country."""
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    answer = data.get('country', '')
    guess = data.get('guess', '')
    norm_a = normalize_country_input(answer)
    norm_g = normalize_country_input(guess)
    correct = norm_a == norm_g
    return jsonify({'correct': correct, 'normalized_answer': answer})


# ---- FootyMind API ----

def normalize_player_input(raw: str) -> str:
    """Lowercase, strip accents, strip punctuation, collapse whitespace."""
    import unicodedata
    s = (raw or '').strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    # Replace punctuation with spaces
    s = ''.join(c if c.isalnum() else ' ' for c in s)
    s = ' '.join(s.split())
    return s


def lookup_player(guess: str):
    """Return the canonical player name if the guess matches any alias,
       else None. Tries direct lookup then a couple of forgiving fallbacks."""
    try:
        from footy_players import ALIAS_TO_PLAYER, PLAYERS
    except ImportError:
        return None
    norm = normalize_player_input(guess)
    if not norm:
        return None
    # Direct alias hit (aliases are stored lowercase, already mostly accent-free)
    if norm in ALIAS_TO_PLAYER:
        return ALIAS_TO_PLAYER[norm]
    # Try normalized-vs-normalized comparison for any alias (handles diacritics)
    for alias, canonical in ALIAS_TO_PLAYER.items():
        if normalize_player_input(alias) == norm:
            return canonical
    # Also try matching against the player's normalized canonical name
    for p in PLAYERS:
        if normalize_player_input(p['name']) == norm:
            return p['name']
    return None


@app.route('/api/footymind/round')
def api_footymind_round():
    """Returns a set of N players for a round, with their career paths
       (but no name)."""
    try:
        from footy_players import get_players_by_difficulty
    except ImportError:
        return jsonify({'error': 'Player data unavailable'}), 500
    diff = (request.args.get('difficulty') or 'easy').lower()
    if diff not in ('easy', 'medium', 'hard'):
        diff = 'easy'
    n = int(request.args.get('n', 10))
    n = max(1, min(20, n))
    pool = get_players_by_difficulty(diff)
    if len(pool) < n:
        # Fallback: pad from full pool if difficulty is sparse
        from footy_players import PLAYERS
        pool = list(pool) + [p for p in PLAYERS if p not in pool]
    sample = random.sample(pool, min(n, len(pool)))
    out = []
    for p in sample:
        out.append({
            'id': normalize_player_input(p['name']),   # client-side identifier
            'name': p['name'],
            'nationality': p['nationality'],
            'position': p['position'],
            'difficulty': p['difficulty'],
            'path': [{'years': yrs, 'club': club} for (yrs, club) in p['path']]
        })
    return jsonify({'difficulty': diff, 'players': out})


@app.route('/api/footymind/check', methods=['POST'])
def api_footymind_check():
    """Check if a guess matches the expected player."""
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    expected = data.get('expected', '')   # canonical name
    guess = data.get('guess', '')
    matched = lookup_player(guess)
    correct = (matched is not None and matched == expected)
    return jsonify({
        'correct': correct,
        'matched': matched,
        'expected': expected
    })


# ---- Football manager game (solo vs CPU) ----
import football_data as _fbdata
import football_game as _fbgame
import football_match as _fbmatch
import football_league as _fbleague


def _fb_player_json(p):
    return {'id': p['id'], 'name': p['name'], 'short': p['short'], 'pos': p['pos'],
            'positions': p.get('positions', [p['pos']]), 'rating': p['rating'],
            'price': p['price'], 'club': p['club'], 'country': p.get('country', ''),
            'age': p.get('age', 0), 'attrs': p['attrs']}


def _fb_load_league():
    """Load the global table from storage. Real entrants only — no synthetic
    managers. The table is empty until real players record results."""
    s = _storage.kv_get_obj(_fbleague.LEAGUE_KEY, None)
    if not s:
        s = {}
    return s


# ---- Football player database (uploadable via admin CSV) ----

_FB_PLAYERS_KEY = "fb_players_v1"
# CSV columns the template uses (order matters for the downloadable template).
_FB_CSV_COLUMNS = ["name", "short_name", "club", "country", "positions",
                   "rating", "price", "age"]


def _fb_rows_to_pool(rows):
    """Normalize stored field-rows into engine player dicts."""
    out = []
    for r in rows:
        out.append(_fbdata.player_from_fields(
            name=r.get("name", ""), short=r.get("short_name") or r.get("short"),
            pos=r.get("positions") or r.get("pos") or "MID",
            rating=r.get("rating", 75), club=r.get("club", ""),
            country=r.get("country", ""), age=r.get("age", 0),
            price=r.get("price")))
    return out


def _fb_validate_pool(pool):
    """Enough players per position to draft a squad and a CPU? Returns (ok, msg)."""
    from collections import Counter
    c = Counter(p["pos"] for p in pool)
    need = {"GK": 2, "DEF": 6, "MID": 6, "FWD": 4}
    missing = [f"{pos} (have {c.get(pos,0)}, need {n})"
               for pos, n in need.items() if c.get(pos, 0) < n]
    if missing:
        return False, "Not enough players: " + "; ".join(missing)
    if len(pool) < 20:
        return False, f"Need at least 20 players, got {len(pool)}"
    return True, ""


def _fb_load_players_from_storage():
    """On boot, swap in an admin-uploaded pool if one exists; else built-in."""
    try:
        rows = _storage.kv_get_list(_FB_PLAYERS_KEY)
        if rows:
            pool = _fb_rows_to_pool(rows)
            ok, _ = _fb_validate_pool(pool)
            if ok:
                _fbdata.set_players(pool)
                print(f"[football] loaded {len(pool)} uploaded players")
                return
    except Exception as e:
        print("[football] player load failed, using built-in:", e)
    _fbdata.reset_to_builtin()


def _fb_players_csv_template():
    """A CSV template with the right header and a few example rows."""
    import io, csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(_FB_CSV_COLUMNS)
    examples = [
        ["Erling Haaland", "Haaland", "Man City", "Norway", "FWD", 91, 13.5, 24],
        ["Bukayo Saka", "Saka", "Arsenal", "England", "MID/FWD", 87, 9.5, 23],
        ["Virgil van Dijk", "Van Dijk", "Liverpool", "Netherlands", "DEF", 89, 6.5, 33],
        ["Alisson", "Alisson", "Liverpool", "Brazil", "GK", 89, 5.5, 32],
        ["Budget Defender", "Budget Def", "Lower FC", "England", "DEF", 64, 4.0, 21],
    ]
    for row in examples:
        w.writerow(row)
    return buf.getvalue()


def _fb_parse_players_csv(text):
    """Parse uploaded CSV text into field-rows. Returns (rows, error)."""
    import io, csv as _csv
    try:
        text = text.lstrip("\ufeff")  # strip BOM
        reader = _csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return None, "Empty file"
        # case-insensitive header map
        hmap = {(h or "").strip().lower(): h for h in reader.fieldnames}
        def col(row, *names):
            for n in names:
                if n in hmap and hmap[n] in row:
                    v = row[hmap[n]]
                    if v is not None and str(v).strip() != "":
                        return str(v).strip()
            return ""
        rows, seen = [], set()
        for raw in reader:
            name = col(raw, "name", "player", "full_name")
            if not name:
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            rows.append({
                "name": name,
                "short_name": col(raw, "short_name", "short", "display") or name,
                "club": col(raw, "club", "team"),
                "country": col(raw, "country", "nation", "nationality"),
                "positions": col(raw, "positions", "position", "pos") or "MID",
                "rating": col(raw, "rating", "ovr", "overall") or "75",
                "price": col(raw, "price", "cost", "value"),
                "age": col(raw, "age"),
            })
        if not rows:
            return None, "No valid rows (need at least a 'name' column with values)"
        return rows, None
    except Exception as e:
        return None, f"Could not parse CSV: {e}"


@app.route('/api/admin/football/players', methods=['GET'])
def admin_fb_players_status():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    rows = _storage.kv_get_list(_FB_PLAYERS_KEY)
    return jsonify({
        'ok': True,
        'count': len(_fbdata.get_pool()),
        'source': 'uploaded' if rows else 'built-in',
        'builtin_count': _fbdata.builtin_count(),
        'by_position': _fbdata.position_counts(),
    })


@app.route('/api/admin/football/players/template', methods=['GET'])
def admin_fb_players_template():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    csv_text = _fb_players_csv_template()
    resp = make_response(csv_text)
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="football_players_template.csv"'
    return resp


@app.route('/api/admin/football/players', methods=['POST'])
def admin_fb_players_upload():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    # accept either a file upload or raw text in JSON
    text = ''
    if request.files.get('file'):
        try:
            text = request.files['file'].read().decode('utf-8', errors='replace')
        except Exception:
            return jsonify({'ok': False, 'error': 'Could not read file'}), 400
    else:
        data = request.get_json(silent=True) or {}
        text = data.get('csv', '') or ''
    if not text.strip():
        return jsonify({'ok': False, 'error': 'No CSV provided'}), 400
    rows, err = _fb_parse_players_csv(text)
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    pool = _fb_rows_to_pool(rows)
    ok, msg = _fb_validate_pool(pool)
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400
    try:
        _storage.kv_set_list(_FB_PLAYERS_KEY, rows)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Save failed: {e}'}), 500
    _fbdata.set_players(pool)
    return jsonify({'ok': True, 'count': len(pool),
                    'by_position': _fbdata.position_counts()})


@app.route('/api/admin/football/players/reset', methods=['POST'])
def admin_fb_players_reset():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    try:
        _storage.kv_set_list(_FB_PLAYERS_KEY, [])
    except Exception:
        pass
    _fbdata.reset_to_builtin()
    return jsonify({'ok': True, 'count': len(_fbdata.get_pool())})


@app.route('/api/admin/football/league', methods=['GET'])
def admin_fb_league_status():
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    s = _fb_load_league()
    return jsonify({'ok': True, 'managers': len(s)})


@app.route('/api/admin/football/league/reset', methods=['POST'])
def admin_fb_league_reset():
    """Wipe the global Manager Rating table. Clears any leftover synthetic
    managers from older builds; the table then refills with real entrants only."""
    if not _admin_authed():
        return jsonify({'error': 'unauthorized'}), 401
    try:
        _storage.kv_set_obj(_fbleague.LEAGUE_KEY, {})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    return jsonify({'ok': True, 'managers': 0})


def _fb_get_rating(uid):
    """Current global rating for a manager (START_RATING if not yet on the table)."""
    if not uid:
        return _fbleague.START_RATING
    s = _fb_load_league()
    row = s.get(uid)
    return (row or {}).get('rating', _fbleague.START_RATING)


def _fb_record_result(uid, name, outcome, opp_rating, gf, ga):
    """Record a match result into the persistent global Manager Rating table.
       opp_rating is the rating of whoever was played (CPU or human)."""
    if not uid:
        return None
    s = _fb_load_league()
    _fbleague.apply_result(s, uid, name or 'Manager', outcome, opp_rating, gf, ga)
    try:
        _storage.kv_set_obj(_fbleague.LEAGUE_KEY, s)
    except Exception:
        pass
    table = _fbleague.ranked_table(s)
    return next((r for r in table if r['uid'] == uid), None)


def _fb_award_forfeit(state, leaver_sid, leaver_name, winner):
    """Award the remaining 1v1 manager a recorded 3-0 walkover and set the room
    result. Returns the result dict, or None if a match result already exists
    (a played match is never overwritten) or there is no football_mp."""
    fbmp = state.get('football_mp')
    if not fbmp or (fbmp.get('result') and fbmp.get('stage') == 'ft'):
        return None
    uids = fbmp.get('uids', {})
    names = fbmp.get('names', {})
    win_sid = winner['sid']
    win_uid = uids.get(win_sid) or winner.get('user_id')
    win_name = names.get(win_sid) or winner.get('name', 'Manager')
    lose_uid = uids.get(leaver_sid)
    lose_name = names.get(leaver_sid) or leaver_name or 'Manager'
    win_pre = win_post = None
    try:
        win_pre = _fb_get_rating(win_uid)
        lose_pre = _fb_get_rating(lose_uid)
        _fb_record_result(win_uid, win_name, 'win', lose_pre, 3, 0)
        _fb_record_result(lose_uid, lose_name, 'loss', win_pre, 0, 3)
        win_post = _fb_get_rating(win_uid)
    except Exception as e:
        print('[fb forfeit] league record failed:', e)
    res = {
        'mode': 'faceoff', 'forfeit': True,
        'home_sid': win_sid, 'away_sid': leaver_sid,
        'home_name': win_name, 'away_name': lose_name,
        'home_score': 3, 'away_score': 0, 'events': [],
        'stats': {'possession_home': 50, 'possession_away': 50, 'shots_home': 0,
                  'shots_away': 0, 'sot_home': 0, 'sot_away': 0},
        'home_zones': {}, 'away_zones': {}, 'result_id': int(time.time() * 1000),
    }
    if win_post is not None:
        res['home_rating'] = win_post
        res['home_delta'] = win_post - (win_pre or win_post)
        res['home_tier'] = _fbleague.tier_for(win_post)['name']
    fbmp['result'] = res
    fbmp['phase'] = 'match'
    return res


@app.route('/api/football/new')
def api_football_new():
    """Fresh drafted squad + the full player pool (transfer market) + config."""
    formation = request.args.get('formation', _fbgame.DEFAULT_FORMATION)
    if formation not in _fbgame.FORMATIONS:
        formation = _fbgame.DEFAULT_FORMATION
    squad = _fbgame.draft_squad(formation, _fbgame.BUDGET)
    return jsonify({
        'budget': _fbgame.BUDGET,
        'formations': _fbgame.FORMATIONS,
        'bench': _fbgame.BENCH,
        'tactics': list(_fbmatch.TACTICS.keys()),
        'cpu_levels': list(_fbgame.CPU_META.keys()),
        'squad': {
            'formation': squad['formation'],
            'starting': [_fb_player_json(squad['players'][pid]) for pid in squad['starting']],
            'bench': [_fb_player_json(squad['players'][pid]) for pid in squad['bench']],
            'cost': squad['cost'],
        },
        'pool': [_fb_player_json(p) for p in _fbdata.get_pool()],
        'zones': _fbgame.zone_strengths(squad),
    })


@app.route('/api/football/simulate', methods=['POST'])
def api_football_simulate():
    """Validate the player's squad, build a CPU opponent at the chosen level,
    simulate, and return the full result (score + minute-stamped events)."""
    data = request.get_json(silent=True) or {}
    sq = data.get('squad') or {}
    tactic = data.get('tactic', _fbmatch.DEFAULT_TACTIC)
    if tactic not in _fbmatch.TACTICS:
        tactic = _fbmatch.DEFAULT_TACTIC
    cpu_level = data.get('cpu_level', 'medium')
    if cpu_level not in _fbgame.CPU_META:
        cpu_level = 'medium'

    squad = {
        'formation': sq.get('formation', _fbgame.DEFAULT_FORMATION),
        'starting': list(sq.get('starting', [])),
        'bench': list(sq.get('bench', [])),
    }
    ok, why = _fbgame.validate_squad(squad)
    if not ok:
        return jsonify({'ok': False, 'msg': why}), 400

    cpu = _fbgame.build_cpu_squad(cpu_level)
    m = _fbmatch.simulate_match(
        squad, cpu, home_tactic=tactic, away_tactic=cpu['tactic'],
        give_home_edge=True, away_ai=True,
        home_name='Your XI', away_name=cpu['name'])

    if m['home_score'] > m['away_score']:
        outcome = 'win'
    elif m['home_score'] < m['away_score']:
        outcome = 'loss'
    else:
        outcome = 'draw'

    return jsonify({
        'ok': True,
        'result': m,
        'your_zones': _fbgame.zone_strengths(squad),
        'cpu_zones': _fbgame.zone_strengths(cpu),
        'cpu_name': cpu['name'],
        'cpu_tactic': cpu['tactic'],
        'cpu_formation': cpu['formation'],
        'outcome': outcome,
    })


@app.route('/api/football/firsthalf', methods=['POST'])
def api_football_firsthalf():
    """Play minutes 1-45 and hand back a match_state to resume the second half
    after the manager's half-time changes."""
    data = request.get_json(silent=True) or {}
    sq = data.get('squad') or {}
    tactic = data.get('tactic', _fbmatch.DEFAULT_TACTIC)
    if tactic not in _fbmatch.TACTICS:
        tactic = _fbmatch.DEFAULT_TACTIC
    cpu_level = data.get('cpu_level', 'medium')
    if cpu_level not in _fbgame.CPU_META:
        cpu_level = 'medium'

    squad = {
        'formation': sq.get('formation', _fbgame.DEFAULT_FORMATION),
        'starting': list(sq.get('starting', [])),
        'bench': list(sq.get('bench', [])),
    }
    ok, why = _fbgame.validate_squad(squad)
    if not ok:
        return jsonify({'ok': False, 'msg': why}), 400

    cpu = _fbgame.build_cpu_squad(cpu_level)
    seed = random.randint(1, 10_000_000)
    m = _fbmatch.simulate_match(
        squad, cpu, home_tactic=tactic, away_tactic=cpu['tactic'],
        give_home_edge=True, away_ai=True,
        home_name='Your XI', away_name=cpu['name'],
        minute_start=1, minute_end=_fbmatch.HALF_MINUTES)

    rs = m.get('resume_state', {})
    match_state = {
        'cpu': {'formation': cpu['formation'], 'starting': cpu['starting'],
                'bench': cpu['bench'], 'name': cpu['name'], 'tactic': cpu['tactic']},
        'cpu_level': cpu_level,
        'seed2': random.randint(1, 10_000_000),
        'resume': rs,
    }
    return jsonify({
        'ok': True,
        'result': {'events': m['events'], 'home_name': m['home_name'],
                   'away_name': m['away_name'],
                   'home_score': m['home_score'], 'away_score': m['away_score']},
        'cpu_name': cpu['name'],
        'cpu_tactic': cpu['tactic'],
        'cpu_formation': cpu['formation'],
        'cpu_value': _fbgame.squad_cost(cpu),
        'your_zones': _fbgame.zone_strengths(squad),
        'cpu_zones': _fbgame.zone_strengths(cpu),
        'match_state': match_state,
    })


@app.route('/api/football/secondhalf', methods=['POST'])
def api_football_secondhalf():
    """Resume minutes 46-90 with the manager's half-time XI and tactic."""
    data = request.get_json(silent=True) or {}
    sq = data.get('squad') or {}
    tactic = data.get('tactic', _fbmatch.DEFAULT_TACTIC)
    if tactic not in _fbmatch.TACTICS:
        tactic = _fbmatch.DEFAULT_TACTIC
    ms = data.get('match_state') or {}
    cpu = ms.get('cpu') or {}
    rs = ms.get('resume') or {}

    formation = sq.get('formation', _fbgame.DEFAULT_FORMATION)
    starting = list(sq.get('starting', []))
    ok, why = _fbgame.validate_starting_xi(starting, formation)
    if not ok:
        return jsonify({'ok': False, 'msg': why}), 400
    if not cpu.get('starting') or not rs:
        return jsonify({'ok': False, 'msg': 'Missing match state'}), 400

    home = {'formation': formation, 'starting': starting, 'bench': []}
    away = {'formation': cpu.get('formation', '4-3-3'),
            'starting': list(cpu.get('starting', [])),
            'bench': list(cpu.get('bench', []))}
    cpu_name = cpu.get('name', 'Rivals')

    m = _fbmatch.simulate_match(
        home, away, home_tactic=tactic, away_tactic=cpu.get('tactic', 'balanced'),
        give_home_edge=True, away_ai=True,
        home_name='Your XI', away_name=cpu_name,
        seed=ms.get('seed2'),
        minute_start=_fbmatch.HALF_MINUTES + 1, minute_end=90,
        init_hs=rs.get('hs', 0), init_as=rs.get('as', 0),
        away_start_init=rs.get('away_start'), away_tactic_init=rs.get('away_tactic'),
        away_subs_made_init=rs.get('away_subs_made', 0),
        away_bench_init=rs.get('away_bench_avail'),
        init_shots=rs.get('shots'), init_sot=rs.get('sot'), init_poss=rs.get('poss'))

    if m['home_score'] > m['away_score']:
        outcome = 'win'
    elif m['home_score'] < m['away_score']:
        outcome = 'loss'
    else:
        outcome = 'draw'

    # Record into the persistent global Manager Rating (server-authoritative
    # score). A quick match counts: the CPU has a calibrated rating, so beating
    # a harder CPU lifts you more and losing to an easy one costs more.
    league_you = None
    if data.get('ranked') and data.get('user_id'):
        cpu_level = ms.get('cpu_level', 'medium')
        opp_rating = _fbleague.CPU_RATINGS.get(cpu_level, _fbleague.START_RATING)
        league_you = _fb_record_result(
            data.get('user_id'), data.get('name'),
            outcome, opp_rating, m['home_score'], m['away_score'])

    return jsonify({
        'ok': True,
        'result': m,
        'your_zones': _fbgame.zone_strengths(home),
        'cpu_zones': _fbgame.zone_strengths(away),
        'cpu_name': cpu_name,
        'outcome': outcome,
        'league_you': league_you,
    })


@app.route('/api/football/league')
def api_football_league():
    """Read the persistent global league table."""
    uid = request.args.get('user_id', '')
    s = _fb_load_league()
    table = _fbleague.ranked_table(s)
    you = next((r for r in table if r['uid'] == uid), None)
    return jsonify({'ok': True, 'table': table[:50], 'count': len(table), 'you': you})


# ---- Football manager 1v1 (multiplayer) ----

def fbmp_public_state(fbmp):
    """Per-client view of a football 1v1 room (light: the player pool comes
    over HTTP, so only readiness and the finished result travel in state)."""
    if not fbmp:
        return None
    subs = fbmp.get('submissions') or {}
    names = fbmp.get('names', {})
    ready = {s: bool((subs.get(s) or {}).get('ready')) for s in names}
    out = {
        'phase': fbmp.get('phase', 'draft'),
        'mode': fbmp.get('mode', 'faceoff'),
        'budget': fbmp.get('budget', _fbgame.BUDGET),
        'sids': fbmp.get('sids', [s for s in names]),
        'home_sid': fbmp.get('home_sid'),
        'away_sid': fbmp.get('away_sid'),
        'names': names,
        'ready': ready,
    }
    out['stage'] = fbmp.get('stage')
    ht = fbmp.get('ht') or {}
    out['ht_ready'] = {s: bool((ht.get(s) or {}).get('ready')) for s in names}
    if fbmp.get('phase') == 'match' and fbmp.get('result'):
        out['result'] = fbmp['result']
    return out


def _fb_run_group(fbmp):
    """Simulate a round-robin mini-league among all ready managers and build a
    final table. Each pairing also moves both managers' global ratings, using
    frozen pre-tournament ratings so the order of matches does not matter."""
    sids = fbmp.get('sids') or list(fbmp.get('names', {}).keys())
    subs = fbmp['submissions']
    names = fbmp['names']
    uids = fbmp.get('uids', {})
    table = {s: {'sid': s, 'name': names.get(s, 'Manager'), 'P': 0, 'W': 0,
                 'D': 0, 'L': 0, 'GF': 0, 'GA': 0, 'Pts': 0} for s in sids}
    matches = []
    pre = {s: _fb_get_rating(uids.get(s)) for s in sids}
    league = _fb_load_league()
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            a, b = sids[i], sids[j]
            m = _fbmatch.simulate_match(
                subs[a]['squad'], subs[b]['squad'],
                home_tactic=subs[a]['tactic'], away_tactic=subs[b]['tactic'],
                give_home_edge=False, away_ai=False,
                home_name=names[a], away_name=names[b])
            hsc, asc = m['home_score'], m['away_score']
            matches.append({'a': a, 'b': b, 'a_name': names[a], 'b_name': names[b],
                            'a_score': hsc, 'b_score': asc})
            table[a]['P'] += 1; table[b]['P'] += 1
            table[a]['GF'] += hsc; table[a]['GA'] += asc
            table[b]['GF'] += asc; table[b]['GA'] += hsc
            if hsc > asc:
                a_oc, b_oc = 'win', 'loss'
                table[a]['W'] += 1; table[a]['Pts'] += 3; table[b]['L'] += 1
            elif hsc < asc:
                a_oc, b_oc = 'loss', 'win'
                table[b]['W'] += 1; table[b]['Pts'] += 3; table[a]['L'] += 1
            else:
                a_oc = b_oc = 'draw'
                table[a]['D'] += 1; table[b]['D'] += 1
                table[a]['Pts'] += 1; table[b]['Pts'] += 1
            if uids.get(a):
                _fbleague.apply_result(league, uids[a], names[a], a_oc, pre[b], hsc, asc)
            if uids.get(b):
                _fbleague.apply_result(league, uids[b], names[b], b_oc, pre[a], asc, hsc)
    try:
        _storage.kv_set_obj(_fbleague.LEAGUE_KEY, league)
    except Exception as e:
        print('[fbmp] group league save failed:', e)
    rows = sorted(table.values(),
                  key=lambda r: (-r['Pts'], -(r['GF'] - r['GA']), -r['GF'], r['name']))
    for k, r in enumerate(rows):
        r['pos'] = k + 1
        r['GD'] = r['GF'] - r['GA']
        uid = uids.get(r['sid'])
        post = (league.get(uid) or {}).get('rating') if uid else None
        r['rating'] = post
        r['delta'] = (post - pre[r['sid']]) if post is not None else 0
        r['tier'] = _fbleague.tier_for(post)['name'] if post is not None else ''
    fbmp['result'] = {
        'mode': 'group',
        'table': rows,
        'matches': matches,
        'result_id': int(time.time() * 1000),
    }
    fbmp['phase'] = 'match'


@socketio.on('football_ready')
def on_football_ready(data):
    """A player locks in their squad + tactic. When everyone is ready the server
    simulates the match(es) -- a single 90 minutes in faceoff, or a full
    round-robin in a group -- and broadcasts the result, updating ratings."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    data = data or {}
    sq = data.get('squad') or {}
    tactic = data.get('tactic', _fbmatch.DEFAULT_TACTIC)
    if tactic not in _fbmatch.TACTICS:
        tactic = _fbmatch.DEFAULT_TACTIC
    squad = {
        'formation': sq.get('formation', _fbgame.DEFAULT_FORMATION),
        'starting': list(sq.get('starting', [])),
        'bench': list(sq.get('bench', [])),
    }
    ok, why = _fbgame.validate_squad(squad)
    if not ok:
        emit('error_msg', {'msg': why})
        return
    with room['lock']:
        state = room['state']
        fbmp = state.get('football_mp')
        if not fbmp or state.get('phase') != 'fb_draft':
            return
        if sid not in fbmp.get('names', {}):
            return
        fbmp['submissions'][sid] = {
            'squad': squad, 'tactic': tactic, 'ready': True,
            'name': fbmp['names'].get(sid, 'Manager'),
        }
        sids = fbmp.get('sids') or list(fbmp.get('names', {}).keys())
        all_ready = all((fbmp['submissions'].get(s) or {}).get('ready') for s in sids)
        if all_ready:
            if fbmp.get('mode') == 'group':
                _fb_run_group(fbmp)
            else:
                _fb_run_faceoff_h1(fbmp)
            state['phase'] = 'fb_match'
        touch_room(room)
    broadcast_state(room['state'], code)


def _fb_run_faceoff(fbmp):
    """Single 90-minute 1v1: simulate, build the result, update both ratings."""
    home_sid = fbmp['home_sid']
    away_sid = fbmp['away_sid']
    hs = fbmp['submissions'][home_sid]
    as_ = fbmp['submissions'][away_sid]
    m = _fbmatch.simulate_match(
        hs['squad'], as_['squad'],
        home_tactic=hs['tactic'], away_tactic=as_['tactic'],
        give_home_edge=False, away_ai=False,
        home_name=fbmp['names'][home_sid], away_name=fbmp['names'][away_sid])
    if m['home_score'] > m['away_score']:
        home_oc, away_oc = 'win', 'loss'
    elif m['home_score'] < m['away_score']:
        home_oc, away_oc = 'loss', 'win'
    else:
        home_oc = away_oc = 'draw'
    fbmp['result'] = {
        'mode': 'faceoff',
        'home_sid': home_sid, 'away_sid': away_sid,
        'home_name': fbmp['names'][home_sid], 'away_name': fbmp['names'][away_sid],
        'home_score': m['home_score'], 'away_score': m['away_score'],
        'events': m['events'], 'stats': m['stats'],
        'home_zones': _fbgame.zone_strengths(hs['squad']),
        'away_zones': _fbgame.zone_strengths(as_['squad']),
        'home_value': _fbgame.squad_cost(hs['squad']),
        'away_value': _fbgame.squad_cost(as_['squad']),
        'result_id': int(time.time() * 1000),
    }
    fbmp['phase'] = 'match'
    uids = fbmp.get('uids', {})
    try:
        home_uid = uids.get(home_sid)
        away_uid = uids.get(away_sid)
        home_pre = _fb_get_rating(home_uid)
        away_pre = _fb_get_rating(away_uid)
        _fb_record_result(home_uid, fbmp['names'][home_sid],
                          home_oc, away_pre, m['home_score'], m['away_score'])
        _fb_record_result(away_uid, fbmp['names'][away_sid],
                          away_oc, home_pre, m['away_score'], m['home_score'])
        home_post = _fb_get_rating(home_uid)
        away_post = _fb_get_rating(away_uid)
        fbmp['result']['home_rating'] = home_post
        fbmp['result']['away_rating'] = away_post
        fbmp['result']['home_delta'] = home_post - home_pre
        fbmp['result']['away_delta'] = away_post - away_pre
        fbmp['result']['home_tier'] = _fbleague.tier_for(home_post)['name']
        fbmp['result']['away_tier'] = _fbleague.tier_for(away_post)['name']
    except Exception as e:
        print('[fbmp] league record failed:', e)


def _fb_run_faceoff_h1(fbmp):
    """First half of a 1v1 (minutes 1-45). Hands the clients a half-time result
    so each manager can change shape / make subs before the second half; the
    opponent sees that they are making changes. No ratings move until full time."""
    home_sid = fbmp['home_sid']
    away_sid = fbmp['away_sid']
    hs = fbmp['submissions'][home_sid]
    as_ = fbmp['submissions'][away_sid]
    m = _fbmatch.simulate_match(
        hs['squad'], as_['squad'],
        home_tactic=hs['tactic'], away_tactic=as_['tactic'],
        give_home_edge=False, away_ai=False,
        home_name=fbmp['names'][home_sid], away_name=fbmp['names'][away_sid],
        minute_start=1, minute_end=_fbmatch.HALF_MINUTES)
    rs = m.get('resume_state', {}) or {}
    sh = rs.get('shots') or {}
    so = rs.get('sot') or {}
    po = rs.get('poss') or {}
    _ph = po.get('home', 0)
    _pa = po.get('away', 0)
    _tot = (_ph + _pa) or 1
    poss_home = max(25, min(75, round(100 * _ph / _tot)))
    h1_stats = {
        'possession_home': poss_home, 'possession_away': 100 - poss_home,
        'shots_home': sh.get('home', 0), 'shots_away': sh.get('away', 0),
        'sot_home': so.get('home', 0), 'sot_away': so.get('away', 0),
    }
    fbmp['h1'] = {
        'resume': rs,
        'hs': m['home_score'], 'as': m['away_score'],
        'events': m['events'],
    }
    fbmp['ht'] = {}
    fbmp['stage'] = 'h1'
    fbmp['result'] = {
        'mode': 'faceoff', 'stage': 'h1',
        'home_sid': home_sid, 'away_sid': away_sid,
        'home_name': fbmp['names'][home_sid], 'away_name': fbmp['names'][away_sid],
        'home_score': m['home_score'], 'away_score': m['away_score'],
        'events': m['events'], 'stats': h1_stats,
        'home_zones': _fbgame.zone_strengths(hs['squad']),
        'away_zones': _fbgame.zone_strengths(as_['squad']),
        'home_formation': hs['squad'].get('formation', '4-3-3'),
        'away_formation': as_['squad'].get('formation', '4-3-3'),
        'home_value': _fbgame.squad_cost(hs['squad']),
        'away_value': _fbgame.squad_cost(as_['squad']),
        'result_id': int(time.time() * 1000),
    }
    fbmp['phase'] = 'match'


def _fb_run_faceoff_h2(fbmp):
    """Second half (46-90) using each manager's half-time XI + tactic, resuming
    from the first-half score. Builds the full-time result and moves ratings."""
    home_sid = fbmp['home_sid']
    away_sid = fbmp['away_sid']
    h1 = fbmp.get('h1', {})
    rs = h1.get('resume', {}) or {}
    ht = fbmp.get('ht', {}) or {}

    def side_cfg(sid):
        sub = fbmp['submissions'][sid]
        h = ht.get(sid) or {}
        return (h.get('squad') or sub['squad']), (h.get('tactic') or sub['tactic'])

    home_squad, home_tactic = side_cfg(home_sid)
    away_squad, away_tactic = side_cfg(away_sid)
    m = _fbmatch.simulate_match(
        home_squad, away_squad,
        home_tactic=home_tactic, away_tactic=away_tactic,
        give_home_edge=False, away_ai=False,
        home_name=fbmp['names'][home_sid], away_name=fbmp['names'][away_sid],
        minute_start=_fbmatch.HALF_MINUTES + 1, minute_end=90,
        init_hs=h1.get('hs', 0), init_as=h1.get('as', 0),
        init_shots=rs.get('shots'), init_sot=rs.get('sot'), init_poss=rs.get('poss'))
    all_events = (h1.get('events') or []) + m['events']
    if m['home_score'] > m['away_score']:
        home_oc, away_oc = 'win', 'loss'
    elif m['home_score'] < m['away_score']:
        home_oc, away_oc = 'loss', 'win'
    else:
        home_oc = away_oc = 'draw'
    fbmp['result'] = {
        'mode': 'faceoff', 'stage': 'ft',
        'home_sid': home_sid, 'away_sid': away_sid,
        'home_name': fbmp['names'][home_sid], 'away_name': fbmp['names'][away_sid],
        'home_score': m['home_score'], 'away_score': m['away_score'],
        'h1_home': h1.get('hs', 0), 'h1_away': h1.get('as', 0),
        'events': all_events, 'stats': m['stats'],
        'home_zones': _fbgame.zone_strengths(home_squad),
        'away_zones': _fbgame.zone_strengths(away_squad),
        'home_formation': home_squad.get('formation', '4-3-3'),
        'away_formation': away_squad.get('formation', '4-3-3'),
        'home_value': _fbgame.squad_cost(home_squad),
        'away_value': _fbgame.squad_cost(away_squad),
        'result_id': int(time.time() * 1000),
    }
    fbmp['stage'] = 'ft'
    fbmp['phase'] = 'match'
    uids = fbmp.get('uids', {})
    try:
        home_uid = uids.get(home_sid)
        away_uid = uids.get(away_sid)
        home_pre = _fb_get_rating(home_uid)
        away_pre = _fb_get_rating(away_uid)
        _fb_record_result(home_uid, fbmp['names'][home_sid],
                          home_oc, away_pre, m['home_score'], m['away_score'])
        _fb_record_result(away_uid, fbmp['names'][away_sid],
                          away_oc, home_pre, m['away_score'], m['home_score'])
        home_post = _fb_get_rating(home_uid)
        away_post = _fb_get_rating(away_uid)
        fbmp['result']['home_rating'] = home_post
        fbmp['result']['away_rating'] = away_post
        fbmp['result']['home_delta'] = home_post - home_pre
        fbmp['result']['away_delta'] = away_post - away_pre
        fbmp['result']['home_tier'] = _fbleague.tier_for(home_post)['name']
        fbmp['result']['away_tier'] = _fbleague.tier_for(away_post)['name']
    except Exception as e:
        print('[fbmp] league record failed:', e)


@socketio.on('football_ht_ready')
def on_football_ht_ready(data):
    """A manager locks in their half-time changes (subs + tactic). When both are
    in, the second half is simulated with the new line-ups."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    data = data or {}
    sq = data.get('squad') or {}
    tactic = data.get('tactic', _fbmatch.DEFAULT_TACTIC)
    if tactic not in _fbmatch.TACTICS:
        tactic = _fbmatch.DEFAULT_TACTIC
    with room['lock']:
        state = room['state']
        fbmp = state.get('football_mp')
        if not fbmp or fbmp.get('stage') != 'h1':
            return
        if sid not in fbmp.get('names', {}):
            return
        base = (fbmp.get('submissions', {}).get(sid) or {}).get('squad') or {}
        squad = {
            'formation': sq.get('formation', base.get('formation', _fbgame.DEFAULT_FORMATION)),
            'starting': list(sq.get('starting', base.get('starting', []))),
            'bench': list(sq.get('bench', base.get('bench', []))),
        }
        ok, why = _fbgame.validate_squad(squad)
        if not ok:
            emit('error_msg', {'msg': why})
            return
        fbmp.setdefault('ht', {})[sid] = {'squad': squad, 'tactic': tactic, 'ready': True}
        sids = fbmp.get('sids') or list(fbmp.get('names', {}).keys())
        if all((fbmp['ht'].get(s) or {}).get('ready') for s in sids):
            _fb_run_faceoff_h2(fbmp)
        touch_room(room)
    broadcast_state(room['state'], code)


@socketio.on('football_rematch')
def on_football_rematch():
    """Send both players back to the draft for another match."""
    sid = request.sid
    room, code = _get_room_for_sid(sid)
    if not room:
        return
    with room['lock']:
        state = room['state']
        fbmp = state.get('football_mp')
        if not fbmp or state.get('game_type') != 'football':
            return
        fbmp['submissions'] = {}
        fbmp['result'] = None
        fbmp['phase'] = 'draft'
        fbmp['stage'] = None
        fbmp['ht'] = {}
        fbmp['h1'] = {}
        state['phase'] = 'fb_draft'
        touch_room(room)
    broadcast_state(room['state'], code)


# ---- TriviaRush API ----

@app.route('/api/trivia/round')
def api_trivia_round():
    """Return N trivia questions. Client can pass excluded ids in body
       (not query-friendly with long lists), but for solo we accept a comma
       list as a fallback."""
    try:
        import trivia_questions as tq
    except ImportError:
        return jsonify({'error': 'Trivia data unavailable'}), 500
    n = int(request.args.get('n', 10))
    n = max(1, min(20, n))
    cats = request.args.get('categories', '')
    cats_list = [c.strip() for c in cats.split(',') if c.strip()] if cats else None
    exclude = request.args.get('exclude', '')
    excl_set = set([s.strip() for s in exclude.split('|') if s.strip()]) if exclude else None
    qs = tq.get_questions(n, cats_list, excl_set)
    out = [tq.question_to_public(q) for q in qs]
    return jsonify({'questions': out, 'total_pool': tq.total_count()})


@app.route('/api/trivia/check', methods=['POST'])
def api_trivia_check():
    """Check a single trivia answer. Returns correctness and explanation."""
    from flask import request as flask_request
    try:
        import trivia_questions as tq
    except ImportError:
        return jsonify({'error': 'Trivia data unavailable'}), 500
    data = flask_request.get_json(force=True, silent=True) or {}
    qid = data.get('id', '')
    answer = data.get('answer')
    correct, correct_ans, explain = tq.check_answer(qid, answer)
    return jsonify({
        'correct': correct,
        'correct_answer': correct_ans,
        'explain': explain
    })


# ---- Geography API ----

@app.route('/api/geo/round')
def api_geo_round():
    """Return a round of geography questions for the requested sub-mode.

    Query params:
      mode: flags | capitals | continents | landmarks
      n: int (1-20, default 10)
      difficulty: easy | medium | hard | mixed
    """
    try:
        import geography_data as gd
    except ImportError:
        return jsonify({'error': 'Geography data unavailable'}), 500
    mode = (request.args.get('mode') or 'flags').lower()
    diff = (request.args.get('difficulty') or 'mixed').lower()
    n = int(request.args.get('n', 10))
    n = max(1, min(20, n))

    if mode == 'flags':
        items = gd.get_flags_round(n, diff)
    elif mode == 'capitals':
        items = gd.get_capitals_round(n, diff)
    elif mode == 'continents':
        items = gd.get_continents_round(n, diff)
    elif mode == 'landmarks':
        items = gd.get_landmarks_round(n, diff)
    else:
        return jsonify({'error': f'Unknown mode {mode}'}), 400
    return jsonify({'mode': mode, 'difficulty': diff, 'items': items})


@app.route('/api/geo/check', methods=['POST'])
def api_geo_check():
    """Check a free-text geography answer (flags, landmarks).
    The client passes the canonical answer and the user's guess; we
    normalize both and compare. For multiple-choice sub-modes the
    client compares locally — no server check needed."""
    from flask import request as flask_request
    data = flask_request.get_json(force=True, silent=True) or {}
    expected = data.get('expected', '')
    guess = data.get('guess', '')
    norm_e = normalize_country_input(expected)
    norm_g = normalize_country_input(guess)
    return jsonify({
        'correct': norm_e == norm_g and bool(norm_e),
        'expected': expected
    })


# =========================================================================
# JANITOR (cleans up dead rooms)
# =========================================================================

def janitor_thread():
    _tick = 0
    while True:
        socketio.sleep(15)
        _tick += 1
        # Flush profiles to durable storage if anything changed. Runs every
        # 15s so a restart loses at most ~15s of play. One HTTP call, and only
        # when something actually changed.
        try:
            if PROFILES_DIRTY:
                save_profiles()
        except Exception as e:
            print(f"[janitor] profile flush failed: {e}")
        # Room cleanup only needs to run once a minute, not every 15s.
        if _tick % 4 != 0:
            continue
        now = time.time()
        to_delete = []
        with ROOMS_DICT_LOCK:
            for code, room in ROOMS.items():
                state = room['state']
                active = [p for p in state['players'].values()
                          if not p.get('is_bot') and p.get('disconnected_at') is None]
                if len(active) == 0 and (now - room['last_activity_at']) > ROOM_INACTIVITY_TTL:
                    to_delete.append(code)
        for code in to_delete:
            delete_room(code)


# =========================================================================
# BOOT — runs at import time so gunicorn workers get a fully initialized
# server. The __main__ block below is ONLY for `python server.py` (dev).
# =========================================================================

_BOOT_LOCK = threading.Lock()
_BOOTED = False

def refresh_all_admin_content():
    """Reload admin-added content into every game's bank. Called on boot and
    after any /admin add/delete so changes take effect without a redeploy."""
    for modname in ('trivia_questions', 'pictionary_data', 'footy_players',
                    'geography_data'):
        try:
            mod = __import__(modname)
            if hasattr(mod, 'refresh_admin_content'):
                mod.refresh_admin_content()
        except Exception as e:
            print(f"[admin] refresh {modname} failed: {e}")

def boot_once():
    global _BOOTED
    with _BOOT_LOCK:
        if _BOOTED:
            return
        _BOOTED = True
        try:
            load_wordlist()
        except Exception as e:
            print(f"[boot] load_wordlist failed: {e}")
        try:
            load_profiles()
        except Exception as e:
            print(f"[boot] load_profiles failed: {e}")
        try:
            _fb_load_players_from_storage()
        except Exception as e:
            print(f"[boot] football player load failed: {e}")
        try:
            refresh_all_admin_content()
        except Exception as e:
            print(f"[boot] admin content refresh failed: {e}")
        try:
            socketio.start_background_task(janitor_thread)
        except Exception as e:
            print(f"[boot] janitor start failed: {e}")
        print(f"[boot] ready (async_mode={_ASYNC_MODE})")

# Run boot at module import (gunicorn imports server:app — this fires).
boot_once()


if __name__ == '__main__':
    # Dev mode: python server.py — Flask dev server with the Werkzeug hack.
    ip = get_lan_ip()
    port = int(os.environ.get('PORT', 5000))
    print()
    print("=" * 60)
    print("  GameRoom server is running (DEV — use gunicorn for prod)")
    print("=" * 60)
    print(f"  On THIS device, open:    http://localhost:{port}")
    print(f"  On other devices (same WiFi), open:")
    print(f"                           http://{ip}:{port}")
    print("=" * 60)
    print("  Anyone with a room link (.../r/CODE) can join.")
    print("  Press Ctrl+C to stop the server.")
    print()
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
