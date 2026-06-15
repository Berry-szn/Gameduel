"""
Storage backend for GameRoom profiles.

Problem this solves: Render's free tier has an EPHEMERAL filesystem — anything
written to disk is wiped on every redeploy/restart. (And previously profiles
were never even written to disk.) So player level / XP / achievements vanished
whenever the service restarted.

This module provides a tiny key-value persistence layer with two backends,
chosen automatically at import time:

  1. Upstash Redis (REST API over HTTPS) — used when the environment provides
     UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN. Durable across restarts.
     Uses the `requests` library (already a dependency) — no TCP, no extra deps.

  2. Local JSON file — used otherwise (local development). Identical behaviour
     to the old profiles.json so nothing changes when running on your machine.

The whole profiles dict is stored under a single key as a JSON blob. For a
hobby project with a few thousand players this is simpler and safer (atomic
read/write) than sharding per-user keys, and well within Upstash's free tier.

Public API:
    backend_name() -> str
    load_profiles() -> dict          # returns {} if nothing stored yet
    save_profiles(profiles: dict)    # persists the whole dict
"""
import json
import os
import threading

try:
    import requests
except ImportError:
    requests = None


# Key under which the entire profiles dict is stored in Redis.
_REDIS_KEY = "gameroom:profiles"

# Local fallback path (same location the old code used).
_LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'profiles.json')

# Resolve Upstash credentials. Support both the standard Upstash names and a
# couple of common aliases so deployment is forgiving.
_UPSTASH_URL = (os.environ.get('UPSTASH_REDIS_REST_URL')
                or os.environ.get('KV_REST_API_URL')
                or os.environ.get('REDIS_REST_URL'))
_UPSTASH_TOKEN = (os.environ.get('UPSTASH_REDIS_REST_TOKEN')
                  or os.environ.get('KV_REST_API_TOKEN')
                  or os.environ.get('REDIS_REST_TOKEN'))

_USE_REDIS = bool(_UPSTASH_URL and _UPSTASH_TOKEN and requests is not None)

_LOCK = threading.Lock()


def backend_name() -> str:
    """Human-readable name of the active backend (for boot logging)."""
    if _USE_REDIS:
        return f"Upstash Redis ({_UPSTASH_URL.split('//')[-1][:24]}...)"
    return f"local JSON ({_LOCAL_PATH})"


def _redis_get(key: str):
    """GET a key from Upstash via REST. Returns the string value or None."""
    url = _UPSTASH_URL.rstrip('/') + '/get/' + key
    headers = {'Authorization': f'Bearer {_UPSTASH_TOKEN}'}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # Upstash returns {"result": <value or null>}
    return data.get('result')


def _redis_set(key: str, value: str):
    """SET a key in Upstash via REST. Value goes in the POST body so large
    JSON blobs aren't crammed into the URL."""
    url = _UPSTASH_URL.rstrip('/') + '/set/' + key
    headers = {'Authorization': f'Bearer {_UPSTASH_TOKEN}'}
    # The REST API accepts the value as the raw request body for /set/{key}
    resp = requests.post(url, headers=headers, data=value.encode('utf-8'),
                         timeout=10)
    resp.raise_for_status()
    return resp.json()


def load_profiles() -> dict:
    """Load the entire profiles dict from the active backend.
    Returns {} if nothing is stored yet or on any error (fail-safe)."""
    with _LOCK:
        if _USE_REDIS:
            try:
                raw = _redis_get(_REDIS_KEY)
                if not raw:
                    return {}
                return json.loads(raw)
            except Exception as e:
                print(f"[storage] Redis load failed ({e}); starting empty.")
                return {}
        else:
            try:
                if os.path.exists(_LOCAL_PATH):
                    with open(_LOCAL_PATH, 'r', encoding='utf-8') as f:
                        return json.load(f)
                return {}
            except Exception as e:
                print(f"[storage] Local load failed ({e}); starting empty.")
                return {}


def save_profiles(profiles: dict):
    """Persist the entire profiles dict to the active backend."""
    with _LOCK:
        if _USE_REDIS:
            try:
                blob = json.dumps(profiles, separators=(',', ':'))
                _redis_set(_REDIS_KEY, blob)
            except Exception as e:
                print(f"[storage] Redis save failed: {e}")
        else:
            try:
                tmp = _LOCAL_PATH + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(profiles, f, indent=2)
                os.replace(tmp, _LOCAL_PATH)
            except Exception as e:
                print(f"[storage] Local save failed: {e}")


# ----- Generic key-value helpers (used by admin content store) -----
# These persist arbitrary JSON lists under arbitrary keys. In Redis each key
# is independent; in local mode each key maps to its own small JSON file next
# to profiles.json so admin content survives dev restarts too.

def _local_path_for(key: str) -> str:
    safe = key.replace(':', '_').replace('/', '_')
    return os.path.join(os.path.dirname(_LOCAL_PATH), f"{safe}.json")


def kv_get_list(key: str) -> list:
    """Load a JSON list stored under `key`. Returns [] if missing."""
    with _LOCK:
        if _USE_REDIS:
            try:
                raw = _redis_get(key)
                if not raw:
                    return []
                val = json.loads(raw)
                return val if isinstance(val, list) else []
            except Exception as e:
                print(f"[storage] kv_get_list({key}) failed: {e}")
                return []
        else:
            path = _local_path_for(key)
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        val = json.load(f)
                        return val if isinstance(val, list) else []
                return []
            except Exception as e:
                print(f"[storage] local kv_get_list({key}) failed: {e}")
                return []


def kv_set_list(key: str, items: list):
    """Persist a JSON list under `key`."""
    with _LOCK:
        if _USE_REDIS:
            try:
                blob = json.dumps(items, separators=(',', ':'))
                _redis_set(key, blob)
            except Exception as e:
                print(f"[storage] kv_set_list({key}) failed: {e}")
        else:
            path = _local_path_for(key)
            try:
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(items, f, indent=2)
                os.replace(tmp, path)
            except Exception as e:
                print(f"[storage] local kv_set_list({key}) failed: {e}")


def kv_get_obj(key: str, default=None):
    """Load a JSON object/dict stored under `key`. Returns `default` if missing."""
    if default is None:
        default = {}
    with _LOCK:
        if _USE_REDIS:
            try:
                raw = _redis_get(key)
                if not raw:
                    return dict(default)
                val = json.loads(raw)
                return val if isinstance(val, dict) else dict(default)
            except Exception as e:
                print(f"[storage] kv_get_obj({key}) failed: {e}")
                return dict(default)
        else:
            path = _local_path_for(key)
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        val = json.load(f)
                        return val if isinstance(val, dict) else dict(default)
                return dict(default)
            except Exception as e:
                print(f"[storage] local kv_get_obj({key}) failed: {e}")
                return dict(default)


def kv_set_obj(key: str, obj: dict):
    """Persist a JSON object/dict under `key`."""
    with _LOCK:
        if _USE_REDIS:
            try:
                blob = json.dumps(obj, separators=(',', ':'))
                _redis_set(key, blob)
            except Exception as e:
                print(f"[storage] kv_set_obj({key}) failed: {e}")
        else:
            path = _local_path_for(key)
            try:
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(obj, f, indent=2)
                os.replace(tmp, path)
            except Exception as e:
                print(f"[storage] local kv_set_obj({key}) failed: {e}")
