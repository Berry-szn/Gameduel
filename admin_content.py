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


# ===== Settings store (game toggles, announcement, banned names) =====
# A single Redis key holds an admin settings dict. Kept separate from content.
_SETTINGS_KEY = _KEY_PREFIX + "settings"
_DEFAULT_SETTINGS = {
    'disabled_games': [],      # list of game keys hidden from the home screen
    'announcement': {'text': '', 'enabled': False},
    'banned_names': [],        # lowercased names that can't be used
}


def get_settings() -> dict:
    """Return the admin settings dict, with all default keys guaranteed present."""
    with _LOCK:
        try:
            s = _storage.kv_get_obj(_SETTINGS_KEY, _DEFAULT_SETTINGS)
        except Exception as e:
            print(f"[admin] get_settings failed: {e}")
            s = {}
    # Ensure all default keys exist (forward-compatible)
    out = dict(_DEFAULT_SETTINGS)
    out.update(s or {})
    if not isinstance(out.get('disabled_games'), list):
        out['disabled_games'] = []
    if not isinstance(out.get('banned_names'), list):
        out['banned_names'] = []
    if not isinstance(out.get('announcement'), dict):
        out['announcement'] = {'text': '', 'enabled': False}
    return out


def save_settings(settings: dict):
    with _LOCK:
        try:
            _storage.kv_set_obj(_SETTINGS_KEY, settings)
        except Exception as e:
            print(f"[admin] save_settings failed: {e}")


def set_game_disabled(game_key: str, disabled: bool):
    s = get_settings()
    dg = set(s.get('disabled_games', []))
    if disabled:
        dg.add(game_key)
    else:
        dg.discard(game_key)
    s['disabled_games'] = sorted(dg)
    save_settings(s)
    return s['disabled_games']


def set_announcement(text: str, enabled: bool):
    s = get_settings()
    s['announcement'] = {'text': (text or '')[:300], 'enabled': bool(enabled)}
    save_settings(s)
    return s['announcement']


def add_banned_name(name: str):
    s = get_settings()
    n = (name or '').strip().lower()
    if n and n not in s['banned_names']:
        s['banned_names'].append(n)
        save_settings(s)
    return s['banned_names']


def remove_banned_name(name: str):
    s = get_settings()
    n = (name or '').strip().lower()
    s['banned_names'] = [b for b in s.get('banned_names', []) if b != n]
    save_settings(s)
    return s['banned_names']


def is_name_banned(name: str) -> bool:
    n = (name or '').strip().lower()
    if not n:
        return False
    try:
        return n in get_settings().get('banned_names', [])
    except Exception:
        return False


# ===== Bulk add =====

def bulk_add(kind: str, items: list) -> dict:
    """Add many items at once. Returns {added, failed:[{index,error}]}."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    added = 0
    failed = []
    with _LOCK:
        existing = _load_raw(kind)
        for i, item in enumerate(items):
            try:
                it = dict(item)
                it['id'] = 'a_' + uuid.uuid4().hex[:12]
                it['created_at'] = time.time()
                existing.append(it)
                added += 1
            except Exception as e:
                failed.append({'index': i, 'error': str(e)})
        _save_raw(kind, existing)
    return {'added': added, 'failed': failed}


# ===== Spreadsheet import (CSV / XLSX) =====
# Column headers expected per kind. Matching is case-insensitive and ignores
# spaces/underscores, so "Correct Answer", "correct_answer", "CorrectAnswer"
# all map to the same field.

IMPORT_COLUMNS = {
    'trivia':       ['category', 'question', 'correct_answer', 'wrong_answer_1',
                     'wrong_answer_2', 'wrong_answer_3', 'explanation'],
    'pictionary':   ['emoji', 'answer', 'category', 'alternates'],
    'footy':        ['player_name', 'nationality', 'position', 'difficulty',
                     'aliases', 'career'],
    'geo_flag':     ['country_name', 'iso2_code', 'image_url', 'difficulty'],
    'geo_landmark': ['landmark_name', 'country', 'image_url', 'difficulty'],
}


def _norm_header(h: str) -> str:
    return ''.join(ch for ch in (h or '').lower() if ch.isalnum())


def _rows_to_items(kind: str, header: list, rows: list) -> dict:
    """Map parsed spreadsheet rows to native admin items.
    Returns {items:[...], errors:[{row,error}]}."""
    norm_map = {_norm_header(h): i for i, h in enumerate(header)}

    def cell(row, colname):
        idx = norm_map.get(_norm_header(colname))
        if idx is None or idx >= len(row):
            return ''
        v = row[idx]
        return ('' if v is None else str(v)).strip()

    items, errors = [], []
    for rnum, row in enumerate(rows, start=2):  # row 1 is the header
        if not any((c is not None and str(c).strip()) for c in row):
            continue  # skip blank lines
        try:
            if kind == 'trivia':
                q = cell(row, 'question')
                correct = cell(row, 'correct_answer')
                wrongs = [cell(row, 'wrong_answer_1'), cell(row, 'wrong_answer_2'),
                          cell(row, 'wrong_answer_3')]
                opts = [correct] + [w for w in wrongs if w]
                if not q or not correct or len(opts) < 2:
                    errors.append({'row': rnum, 'error': 'need question, correct_answer, and at least one wrong answer'})
                    continue
                items.append({'cat': (cell(row, 'category') or 'pop').lower(),
                              'type': 'mc', 'q': q, 'options': opts, 'answer': 0,
                              'explain': cell(row, 'explanation')})
            elif kind == 'pictionary':
                emoji = cell(row, 'emoji'); answer = cell(row, 'answer')
                if not emoji or not answer:
                    errors.append({'row': rnum, 'error': 'need emoji and answer'}); continue
                items.append({'emoji': emoji, 'answer': answer,
                              'category': cell(row, 'category') or 'word',
                              'alternates': cell(row, 'alternates')})
            elif kind == 'footy':
                name = cell(row, 'player_name')
                career_raw = cell(row, 'career')
                # career format: "2004-2021:Barcelona; 2021-2023:PSG"
                path = []
                for seg in career_raw.replace('\n', ';').split(';'):
                    seg = seg.strip()
                    if not seg:
                        continue
                    if ':' in seg:
                        yrs, club = seg.split(':', 1)
                        if club.strip():
                            path.append([yrs.strip(), club.strip()])
                if not name or not path:
                    errors.append({'row': rnum, 'error': 'need player_name and career (format: "years:club; years:club")'}); continue
                items.append({'name': name, 'nationality': cell(row, 'nationality'),
                              'position': cell(row, 'position'),
                              'difficulty': (cell(row, 'difficulty') or 'medium').lower(),
                              'aliases': cell(row, 'aliases'), 'path': path})
            elif kind == 'geo_flag':
                name = cell(row, 'country_name')
                iso2 = cell(row, 'iso2_code'); url = cell(row, 'image_url')
                if not name or (not iso2 and not url):
                    errors.append({'row': rnum, 'error': 'need country_name and (iso2_code or image_url)'}); continue
                items.append({'name': name, 'iso2': iso2, 'image_url': url,
                              'difficulty': (cell(row, 'difficulty') or 'medium').lower()})
            elif kind == 'geo_landmark':
                name = cell(row, 'landmark_name'); url = cell(row, 'image_url')
                if not name or not url:
                    errors.append({'row': rnum, 'error': 'need landmark_name and image_url'}); continue
                items.append({'name': name, 'country': cell(row, 'country'),
                              'image_url': url,
                              'difficulty': (cell(row, 'difficulty') or 'medium').lower()})
        except Exception as e:
            errors.append({'row': rnum, 'error': str(e)})
    return {'items': items, 'errors': errors}


def parse_spreadsheet(kind: str, filename: str, data: bytes) -> dict:
    """Parse uploaded CSV or XLSX bytes into native items.
    Returns {items, errors, header}."""
    import io
    fn = (filename or '').lower()
    header, rows = [], []
    if fn.endswith('.xlsx') or fn.endswith('.xlsm'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        all_rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        if all_rows:
            header = [('' if h is None else str(h)) for h in all_rows[0]]
            rows = all_rows[1:]
    else:
        # CSV (also handles tab/semicolon by sniffing)
        import csv
        text = data.decode('utf-8-sig', errors='replace')
        try:
            dialect = csv.Sniffer().sniff(text[:2000], delimiters=',;\t')
        except Exception:
            dialect = csv.excel
        reader = list(csv.reader(io.StringIO(text), dialect))
        if reader:
            header = reader[0]
            rows = reader[1:]
    if not header:
        return {'items': [], 'errors': [{'row': 0, 'error': 'file appears empty'}], 'header': []}
    parsed = _rows_to_items(kind, header, rows)
    parsed['header'] = header
    return parsed


def import_spreadsheet(kind: str, filename: str, data: bytes) -> dict:
    """Parse + add. Returns {added, errors, total_rows}."""
    parsed = parse_spreadsheet(kind, filename, data)
    result = bulk_add(kind, parsed['items']) if parsed['items'] else {'added': 0, 'failed': []}
    return {'added': result['added'], 'errors': parsed['errors'],
            'rejected_count': len(parsed['errors'])}


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
