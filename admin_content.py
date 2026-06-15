"""
Admin content store for GameRoom.

Lets the site owner add content (trivia questions, pictionary puzzles, footy
players, geography flags/landmarks) through the /admin panel WITHOUT editing
Python files or redeploying. Added content is stored in the same durable
backend as profiles (Upstash Redis in production, local JSON in dev) and is
MERGED on top of the built-in content each time a game loads its bank.

Design choices:
  - Built-in content (the .py files) is the permanent baseline and is never
    touched. Admin content is purely additive.
  - Each content type has its own storage key, so they're managed separately.
  - Every admin item gets a unique 'id' so it can be individually deleted.
  - If the backend is unavailable, callers fall back to built-in content only
    (admin additions just won't appear) — never a crash.

Public API:
    list_items(kind) -> list[dict]          # admin-added items of a kind
    add_item(kind, item) -> dict            # add one, returns it with an id
    delete_item(kind, item_id) -> bool      # remove by id
    KINDS                                    # the valid content kinds
"""
import json
import time
import uuid
import threading

import storage as _storage

KINDS = ('trivia', 'pictionary', 'footy', 'geo_flag', 'geo_landmark')

# Storage keys (separate from profiles). storage.py persists arbitrary keys.
_KEY_PREFIX = "gameroom:admin:"

_LOCK = threading.Lock()


def _key(kind: str) -> str:
    return _KEY_PREFIX + kind


def _load_raw(kind: str) -> list:
    """Load the raw list of admin items for a kind. [] on any error."""
    if kind not in KINDS:
        return []
    try:
        # storage exposes a generic kv via load/save of the profiles blob; we
        # reuse its backend through dedicated helpers added below.
        return _storage.kv_get_list(_key(kind))
    except Exception as e:
        print(f"[admin] load {kind} failed: {e}")
        return []


def _save_raw(kind: str, items: list):
    try:
        _storage.kv_set_list(_key(kind), items)
    except Exception as e:
        print(f"[admin] save {kind} failed: {e}")


def list_items(kind: str) -> list:
    with _LOCK:
        return _load_raw(kind)


def add_item(kind: str, item: dict) -> dict:
    """Add one item. Stamps an id + created_at. Returns the stored item."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    with _LOCK:
        items = _load_raw(kind)
        item = dict(item)
        item['id'] = 'a_' + uuid.uuid4().hex[:12]
        item['created_at'] = time.time()
        items.append(item)
        _save_raw(kind, items)
        return item


def delete_item(kind: str, item_id: str) -> bool:
    if kind not in KINDS:
        return False
    with _LOCK:
        items = _load_raw(kind)
        new_items = [it for it in items if it.get('id') != item_id]
        if len(new_items) == len(items):
            return False
        _save_raw(kind, new_items)
        return True


def count_all() -> dict:
    """How many admin items exist per kind (for the panel dashboard)."""
    return {k: len(_load_raw(k)) for k in KINDS}


# ----- Merge helpers: convert admin items into the game's native format -----

def merged_trivia(builtin_questions: list) -> list:
    """builtin + admin trivia, in the game's native dict format."""
    out = list(builtin_questions)
    for it in list_items('trivia'):
        try:
            q = {
                'cat': it.get('cat', 'pop'),
                'type': it.get('type', 'mc'),
                'q': it['q'],
                'explain': it.get('explain', ''),
            }
            if q['type'] == 'mc':
                q['options'] = it['options']
                q['answer'] = int(it['answer'])       # index of correct option
            elif q['type'] == 'tf':
                q['answer'] = bool(it['answer'])
            else:
                continue   # unsupported type from admin
            out.append(q)
        except Exception as e:
            print(f"[admin] skip bad trivia item {it.get('id')}: {e}")
    return out


def merged_pictionary(builtin_puzzles: list) -> list:
    """builtin + admin pictionary, as (emoji, answer, category, [alts]) tuples."""
    out = list(builtin_puzzles)
    for it in list_items('pictionary'):
        try:
            emoji = it['emoji']
            answer = it['answer']
            category = it.get('category', 'phrase')
            alts = it.get('alternates', []) or []
            if isinstance(alts, str):
                alts = [a.strip() for a in alts.split(',') if a.strip()]
            out.append((emoji, answer, category, alts))
        except Exception as e:
            print(f"[admin] skip bad pictionary item {it.get('id')}: {e}")
    return out


def merged_footy(builtin_players: list) -> list:
    """builtin + admin footy players, in the game's native dict format."""
    out = list(builtin_players)
    for it in list_items('footy'):
        try:
            # path comes in as list of [years, club] pairs
            raw_path = it.get('path', [])
            path = [(p[0], p[1]) for p in raw_path if len(p) == 2]
            if not path or not it.get('name'):
                continue
            aliases = it.get('aliases', []) or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(',') if a.strip()]
            # always include the lowercased full name as an alias
            if it['name'].lower() not in [a.lower() for a in aliases]:
                aliases.append(it['name'].lower())
            out.append({
                'name': it['name'],
                'aliases': aliases,
                'nationality': it.get('nationality', ''),
                'position': it.get('position', ''),
                'difficulty': it.get('difficulty', 'medium'),
                'path': path,
            })
        except Exception as e:
            print(f"[admin] skip bad footy item {it.get('id')}: {e}")
    return out


def merged_geo_flags(builtin_flags: list) -> list:
    """builtin + admin flags, as (name, iso2, difficulty) tuples.
    Admin flags may instead carry a direct image_url (no iso2); we encode
    that by putting the URL in the iso2 slot prefixed with 'url:' so the
    loader can tell them apart."""
    out = list(builtin_flags)
    for it in list_items('geo_flag'):
        try:
            name = it['name']
            diff = it.get('difficulty', 'medium')
            if it.get('iso2'):
                out.append((name, it['iso2'].lower(), diff))
            elif it.get('image_url'):
                out.append((name, 'url:' + it['image_url'], diff))
        except Exception as e:
            print(f"[admin] skip bad geo_flag item {it.get('id')}: {e}")
    return out


def merged_geo_landmarks(builtin_landmarks: list) -> list:
    """builtin + admin landmarks, as (name, country, image_url, difficulty)."""
    out = list(builtin_landmarks)
    for it in list_items('geo_landmark'):
        try:
            out.append((
                it['name'],
                it.get('country', ''),
                it['image_url'],
                it.get('difficulty', 'medium'),
            ))
        except Exception as e:
            print(f"[admin] skip bad geo_landmark item {it.get('id')}: {e}")
    return out
