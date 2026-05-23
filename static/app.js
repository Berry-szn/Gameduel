// =========================================================================
// GameRoom client (online edition).
// =========================================================================

const socket = io({
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 500,
    reconnectionDelayMax: 4000,
    timeout: 15000
});

// =========================================================================
// PROGRESSION SYSTEM (XP, levels, achievements, streak)
// =========================================================================

const XP_TABLE = [0, 100, 250, 500, 1000, 1750, 2750, 4000, 5500, 7500, 10000];
const TITLES = [
    'Rookie', 'Apprentice', 'Sharpshooter', 'Marksman', 'Hawk-Eye',
    'Mentalist', 'Diviner', 'Oracle', 'Prophet', 'Mastermind', 'Legend'
];

const ACHIEVEMENTS = [
    { id: 'first_blood',     name: 'First Blood',     desc: 'Crack an opponent efficiently (low guess count)', icon: '🩸' },
    { id: 'mind_reader',     name: 'Mind Reader',     desc: 'Crack on your first guess of a round',            icon: '🎯' },
    { id: 'survivor',        name: 'Survivor',        desc: 'Survive 5+ rounds in one group game',             icon: '🛡' },
    { id: 'bracket_buster',  name: 'Bracket Buster',  desc: 'Win a bracket tournament',                        icon: '🏆' },
    { id: 'king',            name: 'King of the Hill',desc: 'Win a king-of-the-hill game',                     icon: '♛' },
    { id: 'sniper',          name: 'Sniper',          desc: 'Win a face-off with zero forfeits',               icon: '🎯' },
    { id: 'double_tap',      name: 'Double Tap',      desc: 'Crack two rounds in a row',                       icon: '⚡' },
    { id: 'flawless',        name: 'Flawless',        desc: 'Win a game with zero forfeits',                   icon: '✨' },
    { id: 'veteran',         name: 'Veteran',         desc: 'Play 10 games',                                   icon: '⭐' },
    { id: 'centurion',       name: 'Centurion',       desc: 'Play 100 games',                                  icon: '💯' },
    { id: 'streak_master',   name: 'Streak Master',   desc: '7-day play streak',                               icon: '🔥' },
    { id: 'triple_threat',   name: 'Triple Threat',   desc: 'Win 3 games in a row',                            icon: '🔱' },
    { id: 'globetrotter',    name: 'Globetrotter',    desc: 'Play all 6 game modes',                           icon: '🌍' }
];

const PROFILE_KEY = 'guessduel_profile_v1';

function freshProfile() {
    return {
        xp: 0,
        games_played: 0,
        wins: 0,
        win_streak: 0,
        streak: 0,
        last_played_date: null,
        modes_played: {},
        achievements: []
    };
}

function loadProfile() {
    try {
        const raw = localStorage.getItem(PROFILE_KEY);
        if (!raw) return freshProfile();
        const obj = JSON.parse(raw);
        return Object.assign(freshProfile(), obj);
    } catch (e) { return freshProfile(); }
}

function saveProfile(p) {
    try { localStorage.setItem(PROFILE_KEY, JSON.stringify(p)); } catch (e) {}
}

function levelFromXP(xp) {
    for (let i = XP_TABLE.length - 1; i >= 0; i--) {
        if (xp >= XP_TABLE[i]) return i + 1;
    }
    return 1;
}

function titleForLevel(level) {
    return TITLES[Math.min(level - 1, TITLES.length - 1)];
}

function progressInLevel(xp) {
    const lvl = levelFromXP(xp);
    if (lvl >= XP_TABLE.length) {
        return { current: 0, needed: 0, percent: 100, capped: true };
    }
    const base = XP_TABLE[lvl - 1];
    const next = XP_TABLE[lvl];
    return {
        current: xp - base,
        needed: next - base,
        percent: ((xp - base) / (next - base)) * 100,
        capped: false
    };
}

function todayDateString() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function daysBetween(a, b) {
    // Both YYYY-MM-DD strings
    const da = new Date(a + 'T00:00:00');
    const db = new Date(b + 'T00:00:00');
    return Math.round((db - da) / 86400000);
}

function computeXPGain(gameOverData, myStats, won) {
    let xp = 0;
    if (won) xp += 50;
    if (myStats) {
        xp += (myStats.cracks || 0) * 10;
        xp += (myStats.rounds_survived || 0) * 5;
        xp += (myStats.first_try_cracks || 0) * 25;
    }
    if (won && gameOverData.mode === 'group' && gameOverData.group_variant === 'bracket') xp += 50;
    if (won && gameOverData.mode === 'group' && gameOverData.group_variant === 'koth') xp += 30;
    return xp;
}

function checkAchievements(gameOverData, myStats, won, profile) {
    const newly = [];
    const unlock = (id) => {
        if (!profile.achievements.includes(id)) {
            profile.achievements.push(id);
            const ach = ACHIEVEMENTS.find(a => a.id === id);
            if (ach) newly.push(ach);
        }
    };
    if (myStats) {
        if (myStats.first_try_cracks > 0) unlock('mind_reader');
        if (myStats.best_consecutive_cracks >= 2) unlock('double_tap');
        if (myStats.rounds_survived >= 5) unlock('survivor');
        if (myStats.cracks > 0 && myStats.guess_count > 0 &&
            (myStats.guess_count / myStats.cracks) <= 3) unlock('first_blood');
    }
    if (won && gameOverData.mode === 'group' && gameOverData.group_variant === 'bracket') unlock('bracket_buster');
    if (won && gameOverData.mode === 'group' && gameOverData.group_variant === 'koth') unlock('king');
    if (won && gameOverData.mode === 'faceoff' && myStats && (myStats.forfeits || 0) === 0) unlock('sniper');
    if (won && myStats && (myStats.forfeits || 0) === 0 && (myStats.guess_count || 0) > 0) unlock('flawless');
    if (profile.games_played >= 10) unlock('veteran');
    if (profile.games_played >= 100) unlock('centurion');
    if (profile.streak >= 7) unlock('streak_master');
    if (profile.win_streak >= 3) unlock('triple_threat');
    if (Object.keys(profile.modes_played || {}).length >= 6) unlock('globetrotter');
    return newly;
}

function modeKey(gameOverData) {
    if (gameOverData.mode === 'group') return 'group_' + (gameOverData.group_variant || 'chain');
    return gameOverData.mode || 'unknown';
}

function applyGameOver(gameOverData) {
    // Update profile based on result. Called once per game_over.
    const profile = loadProfile();
    const myStats = (gameOverData.player_stats || []).find(s => s.sid === State.mySid);
    const won = gameOverData.winner_sid === State.mySid;
    const xpGain = computeXPGain(gameOverData, myStats, won);
    const oldLevel = levelFromXP(profile.xp);

    profile.xp += xpGain;
    profile.games_played += 1;
    if (won) {
        profile.wins += 1;
        profile.win_streak = (profile.win_streak || 0) + 1;
    } else {
        profile.win_streak = 0;
    }
    profile.modes_played = profile.modes_played || {};
    profile.modes_played[modeKey(gameOverData)] = true;

    // Streak: if last played was yesterday, +1. Same day, no change. Else reset to 1.
    const today = todayDateString();
    if (profile.last_played_date) {
        const gap = daysBetween(profile.last_played_date, today);
        if (gap === 0) {
            // same day
        } else if (gap === 1) {
            profile.streak = (profile.streak || 0) + 1;
        } else {
            profile.streak = 1;
        }
    } else {
        profile.streak = 1;
    }
    profile.last_played_date = today;

    const newAchievements = checkAchievements(gameOverData, myStats, won, profile);
    saveProfile(profile);

    const newLevel = levelFromXP(profile.xp);
    return {
        xpGain,
        newLevel,
        leveledUp: newLevel > oldLevel,
        oldLevel,
        newAchievements,
        myStats,
        won,
        profile
    };
}

// =========================================================================
// CORE STATE
// =========================================================================

const State = {
    mySid: null,
    myName: '',
    myUserId: null,               // stable browser UUID — survives SID changes & reconnects
    roomCode: '',                 // current room code
    isSpectator: false,           // joined mid-game as spectator
    selectedGame: 'guessduel',    // 'guessduel' | 'wordchain' | 'oneshot' | 'footymind' | 'trivia'
    pickedMode: null,             // 'solo' | 'faceoff' | 'group' — chosen on screen-mode-pick
    phase: null,
    serverState: null,
    turnTimerInterval: null,
    pauseTimerInterval: null,
    pauseStartedClientTime: null,
    confettiAnimation: null,
    selectedMode: null,
    selectedBot: 'medium',
    selectedFirstTo: 1,
    selectedGroupVariant: 'chain',
    selectedBracketSize: 4,
    selectedKothTarget: 3,
    selectedDifficulty: 'easy',
    selectedTimer: 20,
    // WordChain
    selectedWcMode: null,
    selectedWcDifficulty: 'easy',
    selectedWcTimer: 30,
    selectedWcBot: 'medium',
    wcPendingWord: '',
    pendingTarget: null,           // for pick_target selection
    sound: { enabled: true, tick: true, ctx: null },
    lastGameOverData: null,
    lastGameResult: null
};

const Themes = ['default', 'bold'];

// =========================================================================
// INITIAL ROOM (from /r/<code>)
// =========================================================================

function getInitialRoomCode() {
    const code = (window.INITIAL_ROOM_CODE || '').toUpperCase().trim();
    if (code && /^[A-Z0-9]{4,8}$/.test(code)) return code;
    return '';
}

// =========================================================================
// THEME
// =========================================================================

function applyTheme(theme) {
    if (!Themes.includes(theme)) theme = 'default';
    document.body.dataset.theme = theme;
    document.querySelectorAll('.theme-card').forEach(c => {
        c.classList.toggle('active', c.dataset.theme === theme);
    });
    try { localStorage.setItem('guessduel_theme', theme); } catch (e) {}
}

function loadTheme() {
    let theme = 'default';
    try { theme = localStorage.getItem('guessduel_theme') || 'default'; } catch (e) {}
    applyTheme(theme);
}

// =========================================================================
// SOUND
// =========================================================================

function loadSoundPrefs() {
    try {
        const s = localStorage.getItem('guessduel_sound');
        const t = localStorage.getItem('guessduel_tick');
        if (s !== null) State.sound.enabled = s === 'true';
        if (t !== null) State.sound.tick = t === 'true';
    } catch (e) {}
    syncSoundToggles();
}
function saveSoundPrefs() {
    try {
        localStorage.setItem('guessduel_sound', String(State.sound.enabled));
        localStorage.setItem('guessduel_tick', String(State.sound.tick));
    } catch (e) {}
}
function syncSoundToggles() {
    document.getElementById('toggle-sound').classList.toggle('on', State.sound.enabled);
    document.getElementById('toggle-tick').classList.toggle('on', State.sound.tick);
}
function getAudio() {
    if (!State.sound.enabled) return null;
    try {
        if (!State.sound.ctx) {
            State.sound.ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (State.sound.ctx.state === 'suspended') State.sound.ctx.resume();
        return State.sound.ctx;
    } catch (e) { return null; }
}
function playTone(freq, duration, type='sine', volume=0.05) {
    const ctx = getAudio();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(volume, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + duration);
}
function soundClick() { playTone(800, 0.08, 'square', 0.04); }

/** Light haptic feedback on supporting devices (mostly Android). iOS Safari
 *  ignores this; that's fine. Falls back silently if unavailable. */
function haptic(ms) {
    try {
        if (navigator && typeof navigator.vibrate === 'function') {
            navigator.vibrate(ms || 10);
        }
    } catch (e) {}
}
function hapticTap() { haptic(10); }
function hapticSuccess() { haptic([15, 40, 25]); }
function hapticFail()    { haptic(40); }
function soundTick() { if (State.sound.tick) playTone(1200, 0.05, 'square', 0.03); }
function soundCrack() {
    [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => playTone(f, 0.2, 'triangle', 0.06), i * 70));
}
function soundWin() {
    [523, 659, 784, 1047, 1319].forEach((f, i) => setTimeout(() => playTone(f, 0.3, 'sine', 0.07), i * 100));
}
function soundLose() { playTone(220, 0.4, 'sawtooth', 0.05); }

// =========================================================================
// SCREEN MANAGEMENT
// =========================================================================

function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
    State._currentScreen = id;
}

// Screens where leaving mid-flow should prompt the user. Includes
// solo-only games (geo, trivia, footy, oneshot) and the live phases of
// the multiplayer games (which also have State.roomCode set).
const LIVE_PLAY_SCREENS = new Set([
    'screen-playing', 'screen-secrets',
    'screen-wc-playing', 'screen-wc-round-intro',
    'screen-ts-round', 'screen-ts-round-end',
    'screen-geo-play', 'screen-trivia-play',
    'screen-footy-play', 'screen-oneshot'
]);
function isOnLivePlayScreen() {
    return LIVE_PLAY_SCREENS.has(State._currentScreen);
}
function $(id) { return document.getElementById(id); }

function showOverlay(id) { $(id).classList.remove('hidden'); }
function hideOverlay(id) { $(id).classList.add('hidden'); }

function toast(msg) {
    const container = $('toast-container');
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

// =========================================================================
// DEBUG LOG — on-screen panel showing socket events.
// Enabled by adding ?debug=1 to URL, or tapping the room-pill 5 times.
// Critical for diagnosing the multiplayer connection bug on mobile where
// users can't see the laptop terminal.
// =========================================================================

const DebugLog = {
    enabled: false,
    lines: [],
    max: 30
};

function debugLogInit() {
    try {
        const params = new URLSearchParams(window.location.search);
        if (params.get('debug') === '1') DebugLog.enabled = true;
        if (localStorage.getItem('gameroom_debug') === '1') DebugLog.enabled = true;
    } catch (e) {}
    debugLogRender();
}

// Build version this JS file expects. Must match server's /version response.
// Auto-reload if they diverge (catches stale browser caches even when the
// no-cache headers are bypassed by a proxy / service worker).
const GAMEROOM_BUILD = 'v25';
async function checkBuildVersion() {
    try {
        const res = await fetch('/version', {cache: 'no-store'});
        const data = await res.json();
        if (data.version && data.version !== GAMEROOM_BUILD) {
            console.warn('[gameroom] build mismatch: loaded=' + GAMEROOM_BUILD
                + ' server=' + data.version + ' — reloading');
            // Small delay so the warning is visible in console
            setTimeout(() => { window.location.reload(true); }, 300);
        }
    } catch (e) {}
}
// Check once at boot, then every 60 seconds while tab is open
setTimeout(checkBuildVersion, 2000);
setInterval(checkBuildVersion, 60000);

function debugLog(msg) {
    const stamp = new Date().toISOString().slice(11, 19);
    DebugLog.lines.push(stamp + ' | ' + msg);
    if (DebugLog.lines.length > DebugLog.max) {
        DebugLog.lines = DebugLog.lines.slice(-DebugLog.max);
    }
    // Always log to console so desktop users can see it too
    try { console.log('[gameroom]', msg); } catch (e) {}
    if (DebugLog.enabled) debugLogRender();
}

function debugLogRender() {
    let panel = document.getElementById('debug-log');
    if (!DebugLog.enabled) {
        if (panel) panel.style.display = 'none';
        return;
    }
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'debug-log';
        panel.style.cssText = 'position:fixed;bottom:0;left:0;right:0;max-height:40vh;'
            + 'overflow:auto;background:rgba(0,0,0,0.85);color:#0f0;font-family:monospace;'
            + 'font-size:10px;padding:8px;z-index:99999;border-top:2px solid #0f0;';
        panel.onclick = () => { DebugLog.enabled = false; debugLogRender(); };
        document.body.appendChild(panel);
    }
    panel.style.display = 'block';
    panel.textContent = DebugLog.lines.slice(-15).join('\n')
        + '\n\n(tap to hide)';
    panel.scrollTop = panel.scrollHeight;
}

function debugLogToggle() {
    DebugLog.enabled = !DebugLog.enabled;
    try {
        localStorage.setItem('gameroom_debug', DebugLog.enabled ? '1' : '0');
    } catch (e) {}
    debugLogRender();
    toast('Debug log ' + (DebugLog.enabled ? 'ON' : 'OFF'));
}

function setRoomPill(code) {
    const pill = $('room-pill');
    if (!pill) return;
    // Solo games have no opponent to share with — never show the room pill.
    const hint = State.serverState && State.serverState.mode_hint;
    const isSolo = hint === 'solo';
    if (code && !isSolo) {
        pill.classList.remove('hidden');
        $('room-pill-code').textContent = code;
    } else {
        pill.classList.add('hidden');
    }
}

function getInviteUrl() {
    if (!State.roomCode) return '';
    // mode_hint tells us whether to use /m/ (face-off, 4-char) or /r/ (group, 6-char)
    const hint = State.serverState && State.serverState.mode_hint
        ? State.serverState.mode_hint
        : 'group';
    const prefix = (hint === 'faceoff') ? '/m/' : '/r/';
    return window.location.origin + prefix + State.roomCode;
}

// =========================================================================
// SOCKET (incoming)
// =========================================================================

socket.on('connect', () => {
    State.mySid = socket.id;
    // Tell the server our stable browser identity. Server uses this to
    // recognize "this is the same person reconnecting" even if their SID changed.
    if (State.myUserId) {
        socket.emit('hello', { user_id: State.myUserId, name: State.myName || '' });
    }
    debugLog('socket connected, sid=' + (socket.id || '?'));
});

socket.on('connected', (data) => { State.mySid = data.sid; });

socket.on('disconnect', (reason) => {
    debugLog('socket disconnected: ' + reason);
});

socket.on('connect_error', (err) => {
    debugLog('connect_error: ' + (err && err.message ? err.message : err));
});

socket.io.on('reconnect_attempt', (n) => {
    debugLog('reconnect attempt #' + n);
});

socket.io.on('reconnect', (n) => {
    debugLog('reconnected after ' + n + ' attempts');
});

socket.on('room_created', (data) => {
    State.roomCode = data.code;
    setRoomPill(data.code);
    // Now actually join the room with our name.
    socket.emit('join_room', { code: data.code, name: State.myName });
});

socket.on('joined_room', (data) => {
    State.roomCode = data.code;
    State.isSpectator = !!data.as_spectator;
    setRoomPill(data.code);
    // Persist session so a refresh can auto-rejoin.
    try {
        localStorage.setItem('gameroom_session_v3', JSON.stringify({
            code: data.code,
            name: State.myName,
            at: Date.now()
        }));
    } catch (e) {}
    // Update URL so refresh keeps us here. Use /m/ for face-off, /r/ for group.
    try {
        const hint = (data.mode_hint || (State.serverState && State.serverState.mode_hint)
                     || 'group');
        const prefix = (hint === 'faceoff' && data.code.length <= 4) ? '/m/' : '/r/';
        const newUrl = prefix + data.code;
        if (window.location.pathname !== newUrl) {
            window.history.replaceState({}, '', newUrl);
        }
    } catch (e) {}
    if (data.as_spectator) {
        toast('Joined as spectator — a game is in progress');
    }
});

socket.on('error_msg', (data) => {
    toast(data.msg || 'Something went wrong');
    // If we were auto-rejoining a stale session, clear it
    if (!State.roomCode) {
        try { localStorage.removeItem('gameroom_session_v3'); } catch (e) {}
    }
    // If we were on the join-code screen, also show error there
    const errSlot = $('join-code-error');
    if ($('screen-join-code').classList.contains('active') && errSlot) {
        errSlot.textContent = data.msg || '';
    }
    if ($('screen-guest').classList.contains('active')) {
        $('name-error').textContent = data.msg || '';
    }
});

socket.on('go_home', () => {
    hideOverlay('crack-overlay');
    hideOverlay('round-banner');
    hideOverlay('pause-overlay');
    hideOverlay('menu-overlay');
    document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
    hideInviteModal();
    clearTurnTimer();
    clearPauseTimer();
    State.roomCode = '';
    State.serverState = null;
    State.phase = null;
    State.isSpectator = false;
    setRoomPill('');
    try { localStorage.removeItem('gameroom_session_v3'); } catch (e) {}
    try { window.history.replaceState({}, '', '/'); } catch (e) {}
    refreshProfileUI();
    showScreen('screen-home');
});

/**
 * Called whenever the user navigates away from a room context (game card
 * click, Create new game, Back to home, etc.) so the server doesn't keep
 * them tied to a stale room and the client doesn't show a stale invite link
 * from a previous session.
 */
/** Show the leave-game confirmation modal. If the player is in a live
 *  multiplayer game (1v1 or group), shows a strong forfeit-loss warning. */
function showLeaveModal() {
    const s = State.serverState;
    const inMultiplayer = s && (s.mode_hint === 'faceoff' || s.mode_hint === 'group')
        && (s.players || []).filter(p => !p.is_bot).length > 1;
    const LIVE_PHASES = ['playing', 'secrets', 'pick_target', 'setup', 'cointoss',
                         'wc_playing', 'wc_round_intro', 'wc_round_end',
                         'ts_round', 'ts_round_end',
                         'geo_round', 'geo_round_end'];
    const inServerLive = s && LIVE_PHASES.includes(s.phase);
    // Also count purely-client solo screens (geo, trivia, footy, oneshot HTTP flows)
    const inClientLive = isOnLivePlayScreen();
    // ANY live game leave counts as a loss — solo, faceoff, or group.
    const showPenalty = inServerLive || inClientLive;
    const penalty = document.getElementById('leave-modal-penalty');
    const confirmBtn = document.getElementById('btn-leave-confirm');
    const blurb = document.getElementById('leave-modal-blurb');
    if (blurb) {
        blurb.textContent = showPenalty
            ? 'Leaving now will be recorded as a loss and reset your win streak.'
            : 'You will be returned to the home screen.';
    }
    if (penalty) {
        penalty.style.display = showPenalty ? '' : 'none';
        // For solo show a gentler warning; for MP say "your opponent wins by forfeit"
        penalty.textContent = inMultiplayer
            ? '⚠️ This counts as a loss. Your opponent wins by forfeit.'
            : '⚠️ This will count as a loss in your stats.';
    }
    if (confirmBtn) confirmBtn.textContent = showPenalty ? 'Leave (lose game)' : 'Leave';
    const modal = document.getElementById('leave-modal');
    if (modal) modal.classList.remove('hidden');
}

function leaveCurrentRoomIfAny() {
    if (State.roomCode) {
        debugLog('leaving room ' + State.roomCode);
        socket.emit('leave_game');
    }
    hideInviteModal();
    // Locally reset even if server doesn't reply (defensive)
    State.roomCode = '';
    State.serverState = null;
    State.phase = null;
    State.isSpectator = false;
    State.selectedMode = null;
    State.selectedWcMode = null;
    State.pickedMode = null;
    setRoomPill('');
    try { localStorage.removeItem('gameroom_session_v3'); } catch (e) {}
    try {
        const p = window.location.pathname;
        if (p.startsWith('/r/') || p.startsWith('/m/')) {
            window.history.replaceState({}, '', '/');
        }
    } catch (e) {}
}

socket.on('state', (snapshot) => {
    State.serverState = snapshot;
    State.phase = snapshot.phase;
    if (snapshot.room_code) setRoomPill(snapshot.room_code);
    handlePauseChange(snapshot.pause);
    syncInviteModal(snapshot);

    // Challenge-accept auto-start: when both players have arrived in a
    // challenge-created room, the host (challenger) fires start_game so
    // neither has to manually press Start in the lobby.
    if (State._challengeAutoStartCode
        && snapshot.room_code === State._challengeAutoStartCode
        && (snapshot.phase === 'lobby' || snapshot.phase === 'wc_lobby')) {
        const humans = (snapshot.players || []).filter(p => !p.is_bot);
        const iAmHost = snapshot.host_sid && snapshot.host_sid === State.mySid;
        if (humans.length >= 2 && iAmHost) {
            const gt = snapshot.game_type || 'guessduel';
            State._challengeAutoStartCode = null;  // consume
            if (gt === 'wordchain') {
                socket.emit('start_game', {
                    mode: 'faceoff', wc_difficulty: 'easy',
                    wc_turn_timer: 30, bot_difficulty: 'medium',
                    first_to: State.selectedFirstTo || 1
                });
            } else if (gt === 'timeshot') {
                socket.emit('start_game', {
                    mode: 'faceoff', ts_difficulty: 'medium', first_to: 3
                });
            } else if (gt === 'geography') {
                // Defaults for direct-challenge geo: flags, 5 rounds, mixed difficulty
                socket.emit('start_game', {
                    mode: 'faceoff', geo_mode: 'flags',
                    geo_difficulty: 'mixed', total_rounds: 5
                });
            } else {
                socket.emit('start_game', {
                    mode: 'faceoff', bot_difficulty: 'medium', first_to: 1
                });
            }
            return;
        }
    }

    // TimeShot: if we created a room and we're now in the lobby for it, kick off start_game
    if (snapshot.game_type === 'timeshot' && snapshot.phase === 'lobby') {
        if (tsAutoStartIfNeeded(snapshot)) return;
    }

    // Auto-solo: if room is tagged mode_hint='solo' AND we're in the lobby
    // alone, start the game immediately. We use mode_hint (server-side truth)
    // rather than State.pickedMode (which can be null on session restore).
    const isSoloRoom = snapshot.mode_hint === 'solo';
    const inLobbyAlone = (snapshot.phase === 'lobby' || snapshot.phase === 'wc_lobby')
        && (snapshot.players || []).filter(p => !p.is_bot).length <= 1;
    if (isSoloRoom && inLobbyAlone && !State._autoStarted) {
        State._autoStarted = true;   // guard against double-fire
        const gameType = snapshot.game_type || 'guessduel';
        if (gameType === 'timeshot') {
            // Already handled above via tsAutoStartIfNeeded; skip
            return;
        }
        if (gameType === 'wordchain') {
            socket.emit('start_game', {
                mode: 'solo',
                wc_difficulty: State.selectedWcDifficulty || 'easy',
                wc_turn_timer: State.selectedWcTimer || 30,
                bot_difficulty: State.selectedWcBot || 'medium'
            });
        } else {
            socket.emit('start_game', {
                mode: 'solo',
                bot_difficulty: State.selectedBot || 'medium',
                first_to: State.selectedFirstTo || 1
            });
        }
        return;
    }
    // Reset the guard when we leave the lobby
    if (snapshot.phase !== 'lobby' && snapshot.phase !== 'wc_lobby') {
        State._autoStarted = false;
    }
    routePhase(snapshot);
});

/**
 * Decide whether the invite popup should be visible right now.
 * Rules:
 *   - Only the HOST sees it (the person who created the room).
 *   - Only when waiting in the lobby (room is created, no one else has joined).
 *   - Only for face-off or group rooms (NEVER for solo).
 *   - Hide as soon as another human joins or the game starts.
 */
function syncInviteModal(snapshot) {
    const modal = $('invite-modal');
    if (!modal) return;
    if (!snapshot) { modal.classList.add('hidden'); return; }

    const hint = snapshot.mode_hint;
    const isMulti = (hint === 'faceoff' || hint === 'group');
    const inLobby = (snapshot.phase === 'lobby' || snapshot.phase === 'wc_lobby');
    const iAmHost = snapshot.host_sid && snapshot.host_sid === State.mySid;
    const humans = (snapshot.players || []).filter(p => !p.is_bot && !p.is_spectator);
    const aloneInRoom = humans.length <= 1;

    if (isMulti && inLobby && iAmHost && aloneInRoom) {
        showInviteModal(snapshot);
    } else {
        modal.classList.add('hidden');
    }
}

function showInviteModal(snapshot) {
    const modal = $('invite-modal');
    if (!modal) return;
    const hint = snapshot.mode_hint;
    const isFaceoff = (hint === 'faceoff');
    $('invite-mode-tag').textContent = isFaceoff ? '1V1 FACE-OFF' : 'FRIEND GROUP';
    $('invite-modal-title').textContent = isFaceoff
        ? 'Waiting for opponent...'
        : 'Waiting for friends to join...';
    $('invite-modal-subtitle').textContent = isFaceoff
        ? 'Send the code below to your opponent.'
        : 'Send the code below to your friends. You can start once they\'re in.';
    $('invite-code-big').textContent = snapshot.room_code || '----';
    modal.classList.remove('hidden');
}

function hideInviteModal() {
    const modal = $('invite-modal');
    if (modal) modal.classList.add('hidden');
}

socket.on('crack', (data) => {
    const label = data.first_try ? 'BULLSEYE' : 'CRACKED IT';
    document.querySelector('.crack-label').textContent = label;
    $('crack-name').textContent = data.name + ' cracked ' + data.target;
    showOverlay('crack-overlay');
    soundCrack();
    if (data.first_try) {
        // tiny screen-shake for emphasis
        document.body.classList.add('shake');
        setTimeout(() => document.body.classList.remove('shake'), 600);
    }
    setTimeout(() => hideOverlay('crack-overlay'), 1800);
});

socket.on('guess_made', () => {});

socket.on('round_reveal', (reveal) => {
    const list = $('reveal-list');
    list.innerHTML = '';
    Object.values(reveal).forEach(r => {
        const row = document.createElement('div');
        row.className = 'reveal-row' + (r.eliminated_this_round ? ' eliminated-this-round' : '');
        row.innerHTML = `
            <div>
                <div class="name" style="font-weight:700">${escapeHtml(r.name)}</div>
                <div class="muted small">${r.guess_count} ${r.guess_count === 1 ? 'guess' : 'guesses'}${r.eliminated_this_round ? ' &mdash; eliminated' : ''}</div>
            </div>
            <div class="secret-value">${r.secret !== null ? r.secret : '?'}</div>`;
        list.appendChild(row);
    });
});

socket.on('game_over', (data) => {
    State.lastGameOverData = data;
    const result = applyGameOver(data);
    State.lastGameResult = result;

    if (data.winner_sid === State.mySid) {
        soundWin();
        hapticSuccess();
        triggerConfetti();
    } else {
        soundLose();
        hapticFail();
    }

    // If this was a 1v1 face-off, remember the opponent for quick rechallenge
    try {
        const s = State.serverState;
        if (s && s.mode_hint === 'faceoff') {
            const opp = (s.players || []).find(p =>
                !p.is_bot && p.sid !== State.mySid);
            if (opp && opp.user_id) {
                rememberOpponent(opp.user_id, opp.name);
            }
        }
    } catch (e) {}

    // Achievement toasts (one at a time, staggered)
    (result.newAchievements || []).forEach((ach, i) => {
        setTimeout(() => achievementToast(ach), 1200 + i * 1800);
    });

    if (result.leveledUp) {
        setTimeout(() => levelUpToast(result.newLevel), 600);
    }

    const final = $('final-secrets');
    final.innerHTML = '';
    (data.secrets || []).forEach(s => {
        const row = document.createElement('div');
        row.className = 'reveal-row';
        let nameDisplay = escapeHtml(s.name);
        if (s.sid === data.winner_sid) nameDisplay += ' <span style="color:var(--success);font-weight:700">[winner]</span>';
        if (s.is_bot) nameDisplay += ' <span class="muted small">(computer)</span>';
        row.innerHTML = `<div class="name">${nameDisplay}</div>
                         <div class="secret-value">${s.secret !== null ? s.secret : '?'}</div>`;
        final.appendChild(row);
    });
});

socket.on('double_tap', (data) => {
    if (!data.names || data.names.length === 0) return;
    const meName = State.serverState && State.serverState.me && State.serverState.me.name;
    const includesMe = data.names.includes(meName);
    showDoubleTapBanner(data.names.join(', '), includesMe);
});

socket.on('toast', (data) => { toast(data.msg); });

// =========================================================================
// HELPERS
// =========================================================================

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

function activityText(ev) {
    switch (ev.kind) {
        case 'joined': return `${ev.name} joined the room`;
        case 'left': return `${ev.name} left`;
        case 'left_game': return `${ev.name} left the game`;
        case 'rejoined': return `${ev.name} rejoined`;
        case 'cointoss': return `${ev.winner_name} won the coin toss and will set the rules`;
        case 'rules_set': return `Rules locked: ${ev.difficulty}, ${ev.range_min} to ${ev.range_max}`;
        case 'rules_set_by_bot': return `Computer set the rules: ${ev.difficulty}, ${ev.range_min} to ${ev.range_max}`;
        case 'round_start': return `Round ${ev.round} started`;
        case 'round_play_start': return `Turn 1 of round ${ev.round}`;
        case 'guess':
            return `${ev.name} guessed ${ev.value} (${ev.feedback === 'higher' ? 'go higher' : 'go lower'})`;
        case 'crack': return `${ev.name} cracked ${ev.target}`;
        case 'forfeit': return `${ev.name} ran out of time`;
        case 'eliminated': return `Eliminated this round: ${ev.names.join(', ')}`;
        case 'match_won': return `${ev.name} won match ${ev.match}`;
        case 'game_won': return `${ev.name} won the game`;
        case 'paused': return `${ev.name} paused the game`;
        case 'resumed': return `${ev.name} resumed`;
        case 'pause_timeout': return `Pause timed out`;
        case 'new_lobby': return `Back to lobby`;
        case 'leaderboard_reset': return `Leaderboard cleared`;
        case 'target_picked': return `${ev.name} is going after ${ev.target}`;
        case 'koth_round_start': return `${ev.king} is king for round ${ev.round}`;
        case 'koth_defended': return `${ev.king} defended the hill`;
        case 'koth_cracked': return `${ev.cracker} cracked ${ev.king}`;
        case 'bracket_intro': return `Bracket: ${ev.size} players`;
        case 'bracket_match_start': return `${ev.p1} vs ${ev.p2}`;
        default: return '';
    }
}

// =========================================================================
// PHASE ROUTING
// =========================================================================

function routePhase(s) {
    const phase = s.phase;
    if (phase === 'lobby') renderLobby(s);
    else if (phase === 'sidelined') renderSidelined(s);
    else if (phase === 'cointoss') renderCoinToss(s);
    else if (phase === 'setup') renderSetup(s);
    else if (phase === 'secrets') renderSecrets(s);
    else if (phase === 'pick_target') renderPickTarget(s);
    else if (phase === 'playing') renderPlaying(s);
    else if (phase === 'round_end') renderRoundEnd(s);
    else if (phase === 'koth_round_end') renderKothRoundEnd(s);
    else if (phase === 'bracket_intro') renderBracketIntro(s);
    else if (phase === 'bracket_match_end') renderBracketMatchEnd(s);
    else if (phase === 'match_end') renderMatchEnd(s);
    else if (phase === 'wc_round_intro') renderWcRoundIntro(s);
    else if (phase === 'wc_playing') renderWcPlaying(s);
    else if (phase === 'ts_round') renderTsRound(s);
    else if (phase === 'ts_round_end') renderTsRoundEnd(s);
    else if (phase === 'geo_round') renderGeoMpRound(s);
    else if (phase === 'geo_round_end') renderGeoMpRoundEnd(s);
    else if (phase === 'game_over' && s.game_type === 'timeshot') renderTsGameOver(s);
    else if (phase === 'game_over' && s.game_type === 'geography') renderGeoMpGameOver(s);
    else if (phase === 'game_over') renderGameOver(s);
}

// =========================================================================
// HEADER (round/series indicators)
// =========================================================================

function updateHeader(s) {
    const seriesBadge = $('series-badge');
    const roundIndicator = $('round-indicator');
    if (s.series && s.series.active) {
        seriesBadge.classList.remove('hidden');
        const sids = Object.keys(s.series.scores);
        const me = sids.includes(State.mySid) ? State.mySid : sids[0];
        const opp = sids.find(x => x !== me);
        $('series-score-left').textContent = s.series.scores[me] || 0;
        $('series-score-right').textContent = (opp && s.series.scores[opp]) || 0;
        $('series-target').textContent = s.series.target;
    } else {
        seriesBadge.classList.add('hidden');
    }
    if (['playing', 'secrets', 'round_end', 'pick_target', 'koth_round_end', 'bracket_match_end'].includes(s.phase)) {
        roundIndicator.classList.remove('hidden');
        $('round-num').textContent = s.round_number || 1;
        const left = (s.players || []).filter(p => !p.eliminated).length;
        $('players-left').textContent = left;
    } else {
        roundIndicator.classList.add('hidden');
    }
}

// =========================================================================
// LOBBY
// =========================================================================

// Render mini profile cards for opponent(s) in the lobby — face-off only.
// Mounted just under the "Players in this room" card.
async function renderOpponentProfiles(s) {
    const hint = s.mode_hint;
    if (hint !== 'faceoff') {
        const old = document.getElementById('opponent-profiles');
        if (old) old.innerHTML = '';
        return;
    }
    // Find opponents (humans who are not me)
    const me = State.mySid;
    const opps = (s.players || []).filter(p => p.sid !== me && !p.is_bot);
    if (!opps.length) {
        const old = document.getElementById('opponent-profiles');
        if (old) old.innerHTML = '';
        return;
    }
    // Container — create if missing
    let wrap = document.getElementById('opponent-profiles');
    if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'opponent-profiles';
        const playerCard = document.querySelector('#lobby-players');
        if (playerCard && playerCard.parentElement) {
            playerCard.parentElement.appendChild(wrap);
        }
    }
    wrap.innerHTML = '';
    for (const opp of opps) {
        // Fetch the profile from server
        let prof = null;
        try {
            const r = await fetch('/api/profile/' + encodeURIComponent(opp.name));
            if (r.ok) prof = await r.json();
        } catch (e) {}
        const lvl = (prof && prof.level) || 1;
        const title = (prof && prof.title) || 'Newcomer';
        const coins = (prof && prof.coins) || 0;
        const wins = (prof && prof.wins) || 0;
        const losses = (prof && prof.losses) || 0;
        const card = document.createElement('div');
        card.className = 'opponent-card';
        const initial = (opp.name || '?').charAt(0).toUpperCase();
        card.innerHTML = `
            <div class="opponent-avatar">${escapeHtml(initial)}</div>
            <div class="opponent-info">
                <div class="opponent-name">${escapeHtml(opp.name)}</div>
                <div class="opponent-stats">
                    <span>Lvl <span class="opponent-stat-val">${lvl}</span></span>
                    <span>${escapeHtml(title)}</span>
                    <span>🪙 <span class="opponent-stat-val">${coins}</span></span>
                    <span>W/L <span class="opponent-stat-val">${wins}/${losses}</span></span>
                </div>
            </div>`;
        wrap.appendChild(card);
    }
}

function renderLobby(s) {
    showScreen('screen-lobby');
    updateHeader(s);

    // Invite link is now in the modal popup only — inline card has been
    // removed. Guard for any stragglers that may still query the old node.
    const inviteLinkEl = document.getElementById('invite-link');
    if (inviteLinkEl) {
        const url = getInviteUrl();
        inviteLinkEl.textContent = url || '...';
    }
    updateInviteVisibility();

    // Render opponent profile cards (face-off only) — shows level/coins/wins
    renderOpponentProfiles(s);

    // Show right card based on game type
    const gameType = s.game_type || 'guessduel';
    const gdCard = $('lobby-guessduel-card');
    const wcCard = $('lobby-wordchain-card');
    const geoCard = $('lobby-geography-card');
    if (gdCard) gdCard.classList.add('hidden');
    if (wcCard) wcCard.classList.add('hidden');
    if (geoCard) geoCard.classList.add('hidden');
    if (gameType === 'wordchain') {
        if (wcCard) wcCard.classList.remove('hidden');
    } else if (gameType === 'geography') {
        if (geoCard) geoCard.classList.remove('hidden');
    } else {
        if (gdCard) gdCard.classList.remove('hidden');
    }

    const playerList = $('lobby-players');
    playerList.innerHTML = '';
    (s.players || []).forEach(p => {
        const row = document.createElement('div');
        row.className = 'player-row' + (p.sid === State.mySid ? ' you' : '');
        const initial = (p.name || '?').charAt(0).toUpperCase();
        let avatarHtml;
        if (p.avatar_image) {
            avatarHtml = `<span class="row-avatar" style="background: center / cover no-repeat url('${p.avatar_image}'); color: transparent;"></span>`;
        } else {
            const c = p.avatar_color || '#c2e835';
            avatarHtml = `<span class="row-avatar" style="background: ${c};">${escapeHtml(initial)}</span>`;
        }
        row.innerHTML = `<div class="name">${avatarHtml}<span>${escapeHtml(p.name)}</span></div>
                         <div class="status">${p.disconnected ? 'reconnecting' : 'ready'}</div>`;
        playerList.appendChild(row);
    });

    // Match history (last 10, newest first)
    const hist = (s.match_history || []).slice().reverse();
    const histCard = $('match-history-card');
    const histList = $('match-history-list');
    if (hist.length === 0) {
        histCard.classList.add('hidden');
    } else {
        histCard.classList.remove('hidden');
        histList.innerHTML = '';
        hist.forEach(h => {
            const row = document.createElement('div');
            row.className = 'history-row';
            const modeLabel = h.mode === 'group'
                ? (h.group_variant || 'group')
                : (h.mode || 'game');
            const winnerName = h.winner_name || 'No winner';
            const sub = h.player_names && h.player_names.length
                ? `<span class="muted small"> beat ${escapeHtml(h.player_names.filter(n => n !== h.winner_name).join(', '))}</span>`
                : '';
            row.innerHTML = `<div><span class="winner">${escapeHtml(winnerName)}</span>${sub}</div>
                             <div><span class="mode-tag">${escapeHtml(modeLabel)}</span></div>`;
            histList.appendChild(row);
        });
    }

    if (gameType === 'wordchain') {
        syncWordChainUI();
    } else {
        syncModeUI();
    }
}

function syncWordChainUI() {
    document.querySelectorAll('#lobby-wordchain-card .mode-card[data-wcmode]').forEach(b => {
        b.classList.toggle('active', b.dataset.wcmode === State.selectedWcMode);
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wcdiff]').forEach(b => {
        b.classList.toggle('active', b.dataset.wcdiff === State.selectedWcDifficulty);
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wctimer]').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.wctimer) === State.selectedWcTimer);
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wcbot]').forEach(b => {
        b.classList.toggle('active', b.dataset.wcbot === State.selectedWcBot);
    });
    const soloOpts = $('wc-solo-options');
    if (soloOpts) {
        soloOpts.classList.toggle('hidden', State.selectedWcMode !== 'solo');
    }
    const desc = {
        easy:   'Easy: round 1 starts at 3 letters, mostly common letters.',
        medium: 'Medium: round 1 starts at 4 letters, occasional rare letters.',
        hard:   'Hard: round 1 starts at 5 letters, biased toward rare letters (X, Y, Z, Q, J).'
    };
    const descEl = $('wc-diff-desc');
    if (descEl) descEl.textContent = desc[State.selectedWcDifficulty] || '';
    updateInviteVisibility();
}

function syncModeUI() {
    document.querySelectorAll('#lobby-guessduel-card .mode-card').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === State.selectedMode);
    });
    $('solo-options').classList.toggle('hidden', State.selectedMode !== 'solo');
    $('faceoff-options').classList.toggle('hidden', State.selectedMode !== 'faceoff');
    $('group-options').classList.toggle('hidden', State.selectedMode !== 'group');

    document.querySelectorAll('#lobby-guessduel-card .variant-card').forEach(b => {
        b.classList.toggle('active', b.dataset.variant === State.selectedGroupVariant);
    });
    $('bracket-sub').classList.toggle('hidden',
        !(State.selectedMode === 'group' && State.selectedGroupVariant === 'bracket'));
    $('koth-sub').classList.toggle('hidden',
        !(State.selectedMode === 'group' && State.selectedGroupVariant === 'koth'));

    document.querySelectorAll('#solo-options .seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.bot === State.selectedBot);
    });
    document.querySelectorAll('#faceoff-options .seg-btn').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.firstto) === State.selectedFirstTo);
    });
    document.querySelectorAll('#bracket-sub .seg-btn').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.bracket) === State.selectedBracketSize);
    });
    document.querySelectorAll('#koth-sub .seg-btn').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.koth) === State.selectedKothTarget);
    });

    const desc = { easy: 'Easy: random guesses, beatable.',
                   medium: 'Medium: solid play, makes mistakes sometimes.',
                   hard: 'Hard: nearly optimal binary search.' };
    $('bot-desc').textContent = desc[State.selectedBot] || '';

    updateInviteVisibility();
}

function updateInviteVisibility() {
    /* The invite card is gone (replaced by the modal popup #invite-modal).
       This stub remains as a no-op so existing call-sites don't crash. */
    const card = document.getElementById('invite-card');
    if (!card) return;
    card.classList.add('hidden');
}

// =========================================================================
// SIDELINED
// =========================================================================

function renderSidelined(s) {
    showScreen('screen-sidelined');
    updateHeader(s);
    $('sidelined-by-name').textContent = s.sidelined_by || 'Someone';
}

// =========================================================================
// COIN TOSS
// =========================================================================

function renderCoinToss(s) {
    showScreen('screen-cointoss');
    updateHeader(s);
    const coin = $('coin');
    coin.style.animation = 'none';
    void coin.offsetWidth;
    coin.style.animation = 'coinFlip 2.2s ease-out forwards';
    $('cointoss-winner').classList.add('hidden');
    setTimeout(() => {
        const host = (s.players || []).find(p => p.sid === s.host_sid);
        if (host) {
            $('cointoss-name').textContent = host.name;
            $('cointoss-winner').classList.remove('hidden');
        }
    }, 2300);
}

// =========================================================================
// SETUP (host sets rules)
// =========================================================================

function renderSetup(s) {
    showScreen('screen-setup');
    updateHeader(s);
    const isHost = s.host_sid === State.mySid;
    $('setup-host-view').classList.toggle('hidden', !isHost);
    $('setup-waiting-view').classList.toggle('hidden', isHost);
    if (!isHost) {
        const host = (s.players || []).find(p => p.sid === s.host_sid);
        $('setup-host-name').textContent = host ? host.name : 'Someone';
    } else {
        document.querySelectorAll('#setup-host-view .seg-btn[data-difficulty]').forEach(b => {
            b.classList.toggle('active', b.dataset.difficulty === State.selectedDifficulty);
        });
        document.querySelectorAll('#setup-host-view .seg-btn[data-timer]').forEach(b => {
            b.classList.toggle('active', parseInt(b.dataset.timer) === State.selectedTimer);
        });
        const desc = {
            easy:   'Easy: whole numbers, positive range only.',
            medium: 'Medium: decimals to 2 places, positive range.',
            hard:   'Hard: decimals AND negative numbers allowed.'
        };
        $('difficulty-desc').textContent = desc[State.selectedDifficulty] || '';
        if (typeof syncSetupInputsForDifficulty === 'function') {
            syncSetupInputsForDifficulty(State.selectedDifficulty);
        }
    }
}

// =========================================================================
// SECRETS
// =========================================================================

function renderSecrets(s) {
    showScreen('screen-secrets');
    updateHeader(s);
    const r = s.settings;
    $('secret-range').textContent = `${r.range_min} and ${r.range_max}`;

    // Special heading for KOTH: only king picks
    if (s.koth) {
        const isKing = State.mySid === s.koth.king_sid;
        if (isKing) {
            $('secrets-heading').textContent = 'You are king. Pick your secret.';
            $('input-secret').disabled = false;
            $('btn-submit-secret').disabled = false;
            $('btn-submit-secret').classList.remove('hidden');
            $('input-secret').classList.remove('hidden');
            $('secrets-waiting-label').textContent = 'Challengers will guess your number.';
            $('secrets-pending').innerHTML = '';
        } else {
            const king = (s.players || []).find(p => p.sid === s.koth.king_sid);
            $('secrets-heading').textContent = 'King is choosing a secret';
            $('input-secret').classList.add('hidden');
            $('btn-submit-secret').classList.add('hidden');
            $('secrets-waiting-label').textContent = 'Waiting on:';
            $('secrets-pending').innerHTML = '';
            const row = document.createElement('div');
            row.className = 'player-row king';
            row.innerHTML = `<div class="name">${escapeHtml(king ? king.name : 'King')}</div>
                             <div class="status">${king && king.has_secret ? 'ready' : 'choosing'}</div>`;
            $('secrets-pending').appendChild(row);
        }
        const me = s.me;
        if (me && me.secret !== null && me.secret !== undefined) {
            $('input-secret').value = me.secret;
            $('input-secret').disabled = true;
            $('btn-submit-secret').disabled = true;
            $('btn-submit-secret').textContent = 'Locked in: ' + me.secret;
        } else {
            $('input-secret').value = '';
            $('btn-submit-secret').textContent = 'Lock it in';
        }
        return;
    }

    // Bracket spectator: not in this match
    if (s.bracket && me && me.eliminated) {
        $('secrets-heading').textContent = 'The two players are setting their secrets';
        $('input-secret').classList.add('hidden');
        $('btn-submit-secret').classList.add('hidden');
        $('secrets-waiting-label').textContent = 'In this match:';
        const pending = $('secrets-pending');
        pending.innerHTML = '';
        (s.players || []).filter(p => !p.eliminated).forEach(p => {
            const row = document.createElement('div');
            row.className = 'player-row';
            row.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
                             <div class="status">${p.has_secret ? 'ready' : 'choosing'}</div>`;
            pending.appendChild(row);
        });
        return;
    }

    // Default secrets flow
    $('secrets-heading').textContent = 'Set your secret';
    $('input-secret').classList.remove('hidden');
    $('btn-submit-secret').classList.remove('hidden');
    $('secrets-waiting-label').textContent = 'Waiting on:';

    const me = s.me;
    if (me && me.secret !== null && me.secret !== undefined) {
        $('input-secret').value = me.secret;
        $('input-secret').disabled = true;
        $('btn-submit-secret').disabled = true;
        $('btn-submit-secret').textContent = 'Locked in: ' + me.secret;
    } else {
        $('input-secret').value = '';
        $('input-secret').disabled = false;
        $('btn-submit-secret').disabled = false;
        $('btn-submit-secret').textContent = 'Lock it in';
    }
    $('input-secret').step = (r.difficulty === 'easy') ? '1' : '0.01';
    $('input-secret').min = r.range_min;
    $('input-secret').max = r.range_max;

    const pending = $('secrets-pending');
    pending.innerHTML = '';
    (s.players || []).filter(p => !p.eliminated && !p.has_secret).forEach(p => {
        const row = document.createElement('div');
        row.className = 'player-row';
        row.innerHTML = `<div class="name">${escapeHtml(p.name)}${p.is_bot ? ' <span class="muted small">(computer)</span>' : ''}</div>
                         <div class="status">${p.is_bot ? 'choosing' : 'choosing'}</div>`;
        pending.appendChild(row);
    });
}

// =========================================================================
// PICK TARGET (group: pick_target variant)
// =========================================================================

function renderPickTarget(s) {
    showScreen('screen-pick-target');
    updateHeader(s);
    const grid = $('target-grid');
    grid.innerHTML = '';

    const me = s.me;
    const myLocked = me && me.pick_locked;

    (s.players || []).filter(p => !p.eliminated && p.sid !== State.mySid).forEach(p => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'target-card';
        if (State.pendingTarget === p.sid) card.classList.add('active');
        if (myLocked && me.picked_target_sid === p.sid) card.classList.add('active');
        card.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
                          <div class="sub">${p.is_bot ? 'computer' : 'human'}</div>`;
        card.disabled = !!myLocked;
        card.onclick = () => {
            if (myLocked) return;
            State.pendingTarget = p.sid;
            renderPickTarget(State.serverState);
        };
        grid.appendChild(card);
    });

    const btn = $('btn-lock-target');
    if (myLocked) {
        btn.textContent = 'Locked in';
        btn.disabled = true;
    } else {
        btn.disabled = !State.pendingTarget;
        btn.textContent = 'Lock in target';
    }

    const pending = $('pick-pending');
    pending.innerHTML = '';
    (s.players || []).filter(p => !p.eliminated && !p.pick_locked).forEach(p => {
        const row = document.createElement('div');
        row.className = 'player-row' + (p.sid === State.mySid ? ' you' : '');
        row.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
                         <div class="status">picking</div>`;
        pending.appendChild(row);
    });
}

// =========================================================================
// PLAYING
// =========================================================================

function renderPlaying(s) {
    showScreen('screen-playing');
    updateHeader(s);

    const isMyTurn = s.current_turn_sid === State.mySid;
    const myEliminated = s.me && s.me.eliminated;
    const amSpectator = State.isSpectator || (s.me && s.me.is_spectator);
    const turnBanner = $('turn-banner');
    const myTurnCard = $('my-turn-card');
    const waitingCard = $('waiting-turn-card');

    if (amSpectator) {
        turnBanner.classList.remove('my-turn');
        const current = (s.players || []).find(p => p.sid === s.current_turn_sid);
        $('turn-label').textContent = current ? `${current.name}'s turn (watching)` : 'Watching';
        myTurnCard.classList.add('hidden');
        waitingCard.classList.remove('hidden');
        $('active-player-name').textContent = current ? `${current.name} is guessing` : 'Game in progress';
    } else if (isMyTurn) {
        turnBanner.classList.add('my-turn');
        $('turn-label').textContent = 'Your turn';
        myTurnCard.classList.remove('hidden');
        waitingCard.classList.add('hidden');
        const target = (s.players || []).find(p => p.sid === s.me.target_sid);
        $('target-name').textContent = target ? target.name : '...';
        const r = s.settings;
        $('play-range').textContent = `${r.range_min} to ${r.range_max}`;
        const guessInput = $('input-guess');
        guessInput.step = r.difficulty === 'easy' ? '1' : '0.01';
        guessInput.min = r.range_min;
        guessInput.max = r.range_max;
        guessInput.value = '';
        $('btn-submit-guess').disabled = false;
        $('guess-error').textContent = '';
    } else {
        turnBanner.classList.remove('my-turn');
        const current = (s.players || []).find(p => p.sid === s.current_turn_sid);
        $('turn-label').textContent = current ? current.name + "'s turn" : 'Waiting';
        myTurnCard.classList.add('hidden');
        waitingCard.classList.remove('hidden');
        if (s.bracket && myEliminated) {
            // Bracket spectator (not in this match — could be yet to play, or eliminated)
            const stage = s.bracket.stages[s.bracket.current_stage];
            const match = stage[s.bracket.current_match];
            const p1 = (s.players || []).find(p => p.sid === match.p1_sid);
            const p2 = (s.players || []).find(p => p.sid === match.p2_sid);
            const p1Name = p1 ? p1.name : '?';
            const p2Name = p2 ? p2.name : '?';
            $('active-player-name').textContent = `Watching: ${p1Name} vs ${p2Name}`;
        } else if (myEliminated) {
            $('active-player-name').textContent = 'Game in progress (you are out)';
        } else {
            $('active-player-name').textContent = current ? current.name : 'Someone';
        }
    }

    startTurnTimer(s.turn_started_at, s.settings.turn_timer);

    // KOTH UI
    if (s.koth) {
        $('koth-panel').classList.remove('hidden');
        $('shared-guesses-card').classList.remove('hidden');
        $('chain-card').classList.add('hidden');
        $('bracket-panel').classList.add('hidden');
        $('koth-hint').classList.remove('hidden');
        const king = (s.players || []).find(p => p.sid === s.koth.king_sid);
        $('koth-king-name').textContent = king ? king.name : '...';
        $('koth-target-display').textContent = s.koth.target_wins;
        renderKothScores($('koth-scores'), s);
        renderSharedKothGuesses(s);
    } else if (s.bracket) {
        $('koth-panel').classList.add('hidden');
        $('shared-guesses-card').classList.add('hidden');
        $('chain-card').classList.add('hidden');
        $('bracket-panel').classList.remove('hidden');
        $('koth-hint').classList.add('hidden');
        renderBracketTree($('bracket-display'), s.bracket, s);
    } else {
        $('koth-panel').classList.add('hidden');
        $('shared-guesses-card').classList.add('hidden');
        $('bracket-panel').classList.add('hidden');
        $('koth-hint').classList.add('hidden');
        if (s.settings && s.settings.mode === 'group' && s.settings.group_variant === 'pick_target') {
            $('chain-card-title').textContent = 'Targets this round';
        } else {
            $('chain-card-title').textContent = 'The chain';
        }
        $('chain-card').classList.remove('hidden');
        renderChain(s);
    }

    renderMyGuesses(s);

    const playPlayers = $('play-players');
    playPlayers.innerHTML = '';
    (s.players || []).forEach(p => {
        const row = document.createElement('div');
        let classes = 'player-row';
        if (p.sid === State.mySid) classes += ' you';
        if (p.is_bot) classes += ' bot';
        if (p.eliminated) classes += ' eliminated';
        if (p.safe_this_round) classes += ' safe';
        if (p.sid === s.current_turn_sid) classes += ' current-turn';
        if (s.koth && p.sid === s.koth.king_sid) classes += ' king';
        row.className = classes;
        const status = p.eliminated ? 'eliminated' :
                       p.safe_this_round ? 'safe' :
                       p.sid === s.current_turn_sid ? 'guessing' : 'waiting';
        row.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
                         <div class="status">${status}</div>`;
        playPlayers.appendChild(row);
    });

    if (s.activity && s.activity.length) {
        const last = s.activity[s.activity.length - 1];
        const txt = activityText(last);
        if (txt) $('ticker-content').textContent = txt;
    }
}

function renderChain(s) {
    const chainEl = $('chain-display');
    chainEl.innerHTML = '';
    const playersBySid = {};
    (s.players || []).forEach(p => { playersBySid[p.sid] = p; });
    (s.chain || []).forEach((sid, i) => {
        const p = playersBySid[sid];
        if (!p) return;
        const link = document.createElement('div');
        let cls = 'chain-link';
        if (sid === State.mySid) cls += ' you';
        if (p.safe_this_round) cls += ' safe';
        if (p.eliminated) cls += ' eliminated';
        if (sid === s.current_turn_sid) cls += ' current';
        link.className = cls;
        link.textContent = p.name;
        chainEl.appendChild(link);
        if (i < s.chain.length - 1) {
            const arrow = document.createElement('span');
            arrow.className = 'chain-arrow';
            arrow.textContent = '>';
            chainEl.appendChild(arrow);
        }
    });
}

function renderMyGuesses(s) {
    const list = $('guess-list');
    list.innerHTML = '';
    const me = s.me;
    if (!me || me.guesses.length === 0) {
        list.innerHTML = '<p class="empty-state muted small">No guesses yet.</p>';
        return;
    }
    me.guesses.slice().reverse().forEach(g => {
        const row = document.createElement('div');
        row.className = 'guess-row ' + g.feedback;
        let fbText = g.feedback === 'higher' ? 'TRY HIGHER' :
                     g.feedback === 'lower' ? 'TRY LOWER' :
                     g.feedback === 'correct' ? 'CRACKED' : 'FORFEIT';
        row.innerHTML = `<div><span class="value">${g.value !== null ? g.value : '(no guess)'}</span></div>
                         <div class="feedback">${fbText}</div>`;
        list.appendChild(row);
    });
}

function renderSharedKothGuesses(s) {
    const list = $('shared-guesses');
    list.innerHTML = '';
    const guesses = (s.koth && s.koth.round_guesses) || [];
    if (guesses.length === 0) {
        list.innerHTML = '<p class="empty-state muted small">No guesses yet this round.</p>';
        return;
    }
    guesses.slice().reverse().forEach(g => {
        const row = document.createElement('div');
        row.className = 'guess-row ' + g.feedback;
        const fbText = g.feedback === 'higher' ? 'TRY HIGHER' :
                       g.feedback === 'lower'  ? 'TRY LOWER'  :
                       g.feedback === 'correct' ? 'CRACKED'   : 'FORFEIT';
        row.innerHTML = `<div>
                           <span class="value">${g.value !== null && g.value !== undefined ? g.value : '(no guess)'}</span>
                           <span class="by-name"> &nbsp;by ${escapeHtml(g.guesser_name)}</span>
                         </div>
                         <div class="feedback">${fbText}</div>`;
        list.appendChild(row);
    });
}

function renderKothScores(container, s) {
    container.innerHTML = '';
    const koth = s.koth;
    (s.players || []).forEach(p => {
        const pill = document.createElement('span');
        let cls = 'koth-score-pill';
        if (p.sid === koth.king_sid) cls += ' is-king';
        if (p.sid === State.mySid) cls += ' you';
        pill.className = cls;
        const score = koth.scores[p.sid] || 0;
        pill.textContent = `${p.name}: ${score}`;
        container.appendChild(pill);
    });
}

function renderBracketTree(container, bracket, s) {
    container.innerHTML = '';
    const playerBySid = {};
    (s.players || []).forEach(p => { playerBySid[p.sid] = p; });
    bracket.stages.forEach((stage, sIdx) => {
        const stageEl = document.createElement('div');
        stageEl.className = 'bracket-stage';
        const labels = ['Quarters', 'Semis', 'Final'];
        const labelIdx = Math.max(0, labels.length - bracket.stages.length + sIdx);
        const stageLabel = document.createElement('div');
        stageLabel.className = 'bracket-stage-label';
        stageLabel.textContent = bracket.stages.length === 2
            ? (sIdx === 0 ? 'Semis' : 'Final')
            : (sIdx === 0 ? 'Quarters' : sIdx === 1 ? 'Semis' : 'Final');
        stageEl.appendChild(stageLabel);
        stage.forEach((match, mIdx) => {
            const isCurrent = sIdx === bracket.current_stage && mIdx === bracket.current_match;
            const matchEl = document.createElement('div');
            matchEl.className = 'bracket-match' + (isCurrent ? ' current' : '');
            [match.p1_sid, match.p2_sid].forEach(sid => {
                const slot = document.createElement('div');
                slot.className = 'bracket-slot';
                if (!sid) { slot.classList.add('empty'); slot.textContent = '...'; }
                else {
                    const p = playerBySid[sid];
                    const isWinner = match.played && match.winner_sid === sid;
                    const isLoser = match.played && match.winner_sid !== sid;
                    if (isWinner) slot.classList.add('winner');
                    if (isLoser) slot.classList.add('loser');
                    slot.textContent = p ? p.name : '?';
                }
                matchEl.appendChild(slot);
            });
            stageEl.appendChild(matchEl);
        });
        container.appendChild(stageEl);
    });
}

// =========================================================================
// ROUND END / KOTH ROUND END
// =========================================================================

function renderRoundEnd(s) {
    showScreen('screen-round-end');
    updateHeader(s);
    $('round-end-stamp').textContent = `ROUND ${s.round_number} OVER`;
}

function renderKothRoundEnd(s) {
    showScreen('screen-koth-round-end');
    updateHeader(s);
    const koth = s.koth;
    if (!koth) return;
    const outgoingKing = (s.players || []).find(p => p.sid === koth.last_outgoing_king_sid);
    const newKing = (s.players || []).find(p => p.sid === koth.last_new_king_sid);
    let stamp = 'ROUND DONE';
    let nextLabel = 'Next round...';
    if (koth.last_outcome === 'defended') {
        stamp = 'KING DEFENDED';
        nextLabel = `${outgoingKing ? outgoingKing.name : 'King'} stays on the hill`;
    } else if (koth.last_outcome === 'cracked') {
        stamp = 'KING CRACKED';
        nextLabel = `${newKing ? newKing.name : 'New king'} takes the hill`;
    }
    $('koth-round-stamp').textContent = stamp;
    $('koth-next-king').textContent = nextLabel;
    $('koth-secret-reveal').textContent =
        koth.last_revealed_secret !== null && koth.last_revealed_secret !== undefined
            ? koth.last_revealed_secret
            : '?';
    renderKothScores($('koth-scores-end'), s);
}

// =========================================================================
// BRACKET INTRO / MATCH END
// =========================================================================

function renderBracketIntro(s) {
    showScreen('screen-bracket-intro');
    updateHeader(s);
    if (s.bracket) renderBracketTree($('bracket-intro-display'), s.bracket, s);
}

function renderBracketMatchEnd(s) {
    showScreen('screen-bracket-match-end');
    updateHeader(s);
    if (!s.bracket) return;
    const br = s.bracket;
    const stage = br.stages[br.current_stage];
    const match = stage[br.current_match];
    const winner = (s.players || []).find(p => p.sid === match.winner_sid);
    $('bracket-match-winner').textContent = winner ? winner.name : '...';
    renderBracketTree($('bracket-match-end-display'), br, s);
    // Determine what's next
    const isLastMatchOfBracket = (br.current_stage === br.stages.length - 1)
                                  && (br.current_match === stage.length - 1);
    $('bracket-next-label').textContent = isLastMatchOfBracket
        ? 'Tournament complete'
        : 'Next match starting';
}

// =========================================================================
// MATCH END (face-off series)
// =========================================================================

function renderMatchEnd(s) {
    showScreen('screen-match-end');
    updateHeader(s);
    const winner = (s.players || []).find(p => p.sid === s.winner_sid);
    $('match-winner-name').textContent = winner ? winner.name : '...';
    if (s.series && s.series.active) {
        const sids = Object.keys(s.series.scores);
        const me = sids.includes(State.mySid) ? State.mySid : sids[0];
        const opp = sids.find(x => x !== me);
        const myPlayer = (s.players || []).find(p => p.sid === me);
        const oppPlayer = (s.players || []).find(p => p.sid === opp);
        $('me-block-name').textContent = myPlayer ? myPlayer.name : 'You';
        $('opp-block-name').textContent = oppPlayer ? oppPlayer.name : 'Opponent';
        const myScore = s.series.scores[me] || 0;
        const oppScore = s.series.scores[opp] || 0;
        $('me-block-score').textContent = myScore;
        $('opp-block-score').textContent = oppScore;
        $('match-end-target').textContent = s.series.target;
        document.querySelectorAll('.score-block').forEach(b => b.classList.remove('leading'));
        if (myScore > oppScore) $('me-block-name').closest('.score-block').classList.add('leading');
        else if (oppScore > myScore) $('opp-block-name').closest('.score-block').classList.add('leading');
    }
}

// =========================================================================
// GAME OVER
// =========================================================================

// =========================================================================
// WORDCHAIN
// =========================================================================

function renderWcRoundIntro(s) {
    showScreen('screen-wc-round-intro');
    updateHeader(s);
    const wc = s.wordchain || {};
    // Anti-cheating: everyone sees the ACTIVE PLAYER's letter (not their own
    // upcoming letter). At round-intro before play starts, default to the
    // first-up player's letter; once turn starts current_turn_sid drives it.
    const activeSid = s.current_turn_sid || (wc.turn_order && wc.turn_order[0]);
    const activeLetter = ((wc.player_letters || {})[activeSid]) || wc.letter || '?';
    $('wc-round-num').textContent = wc.round_number || 1;
    $('wc-letter-intro').textContent = activeLetter.toUpperCase();
    $('wc-letter-text').textContent = activeLetter.toUpperCase();
    $('wc-min-len').textContent = wc.min_length || 3;
}

function renderWcPlaying(s) {
    showScreen('screen-wc-playing');
    updateHeader(s);
    const wc = s.wordchain || {};
    const isMyTurn = s.current_turn_sid === State.mySid;
    const amSpectator = State.isSpectator || (s.me && s.me.is_spectator);
    const amEliminated = s.me && s.me.eliminated && !amSpectator;

    // ANTI-CHEATING DISPLAY: everyone sees the ACTIVE PLAYER's letter, not
    // their own upcoming letter. If it's MY turn, this resolves to my letter;
    // otherwise I see the current opponent's letter (so I can follow along).
    // I never see what MY letter will be until it's my turn.
    const activeSid = s.current_turn_sid || State.mySid;
    const activeLetter = ((wc.player_letters || {})[activeSid]) || wc.letter || '?';
    $('wc-letter-display').textContent = activeLetter.toUpperCase();
    $('wc-play-round').textContent = wc.round_number || 1;
    $('wc-play-min-len').textContent = wc.min_length || 3;
    $('wc-letter-prompt').textContent = activeLetter.toUpperCase();
    $('wc-min-len-prompt').textContent = wc.min_length || 3;

    const turnBanner = $('wc-turn-banner');
    const myTurnCard = $('wc-my-turn-card');
    const waitingCard = $('wc-waiting-card');

    if (isMyTurn && !amSpectator && !amEliminated) {
        turnBanner.classList.add('my-turn');
        $('wc-turn-label').textContent = 'Your turn';
        myTurnCard.classList.remove('hidden');
        waitingCard.classList.add('hidden');
        const input = $('wc-input-word');
        input.value = '';
        input.disabled = false;
        $('wc-btn-submit').disabled = false;
        $('wc-error').textContent = '';
        // Auto focus on first render of my turn
        setTimeout(() => { try { input.focus(); } catch (e) {} }, 50);
    } else {
        turnBanner.classList.remove('my-turn');
        const current = (s.players || []).find(p => p.sid === s.current_turn_sid);
        if (amSpectator) {
            $('wc-turn-label').textContent = current ? `${current.name} is up (watching)` : 'Watching';
        } else if (amEliminated) {
            $('wc-turn-label').textContent = current ? `${current.name}'s turn` : 'Waiting';
        } else {
            $('wc-turn-label').textContent = current ? `${current.name}'s turn` : 'Waiting';
        }
        myTurnCard.classList.add('hidden');
        waitingCard.classList.remove('hidden');
        $('wc-active-name').textContent = current ? current.name : 'Someone';
    }

    // Timer
    startWcTimer(s.turn_started_at, s.settings.wc_turn_timer || 30);

    // Words used this round (only this round; round changes wipe the list visually)
    const wordsThisRound = (wc.used_words || []).slice().reverse();
    const wordsEl = $('wc-words-this-round');
    if (!wordsThisRound.length) {
        wordsEl.innerHTML = '<p class="empty-state muted small">No words yet.</p>';
    } else {
        wordsEl.innerHTML = '';
        wordsThisRound.forEach(w => {
            const row = document.createElement('div');
            row.className = 'wc-word-row' + (w.sid === State.mySid ? ' mine' : '');
            row.innerHTML = `<div><span class="word">${escapeHtml(w.word)}</span></div>
                             <div class="by-name">${escapeHtml(w.name)}</div>`;
            wordsEl.appendChild(row);
        });
    }

    // Player list
    const pl = $('wc-players-list');
    pl.innerHTML = '';
    (s.players || []).forEach(p => {
        if (p.is_spectator) return;
        const row = document.createElement('div');
        let cls = 'player-row';
        if (p.sid === State.mySid) cls += ' you';
        if (p.is_bot) cls += ' bot';
        if (p.eliminated) cls += ' eliminated';
        if (p.sid === s.current_turn_sid) cls += ' current-turn';
        row.className = cls;
        const status = p.eliminated ? 'out' :
                       p.sid === s.current_turn_sid ? 'thinking' : 'waiting';
        row.innerHTML = `<div class="name">${escapeHtml(p.name)}</div>
                         <div class="status">${status}</div>`;
        pl.appendChild(row);
    });
}

let WC_TIMER_INTERVAL = null;
function clearWcTimer() {
    if (WC_TIMER_INTERVAL) {
        clearInterval(WC_TIMER_INTERVAL);
        WC_TIMER_INTERVAL = null;
    }
}
function startWcTimer(startedAt, duration) {
    clearWcTimer();
    if (!startedAt) {
        $('wc-timer').textContent = duration;
        return;
    }
    const update = () => {
        if (State.serverState && State.serverState.pause && State.serverState.pause.paused) return;
        const now = Date.now() / 1000;
        const remaining = Math.max(0, duration - (now - startedAt));
        const sec = Math.ceil(remaining);
        const el = $('wc-timer');
        if (el) {
            el.textContent = sec;
            el.classList.toggle('urgent', sec <= 5);
        }
        if (remaining <= 0) clearWcTimer();
    };
    update();
    WC_TIMER_INTERVAL = setInterval(update, 250);
}

function wireWordChain() {
    const submit = () => {
        const word = ($('wc-input-word').value || '').trim();
        if (!word) {
            $('wc-error').textContent = 'Type a word';
            return;
        }
        $('wc-error').textContent = '';
        $('wc-btn-submit').disabled = true;
        socket.emit('wc_submit_word', { word });
    };
    $('wc-btn-submit').onclick = () => { soundClick(); submit(); };
    $('wc-input-word').onkeydown = (e) => {
        if (e.key === 'Enter' && !$('wc-btn-submit').disabled) submit();
    };
}

socket.on('wc_word_accepted', (data) => {
    soundCrack();
    // Just refresh on next state update
});

socket.on('wc_word_rejected', (data) => {
    $('wc-error').textContent = data.reason || 'Invalid word';
    $('wc-btn-submit').disabled = false;
    soundLose();
});


function renderGameOver(s) {
    showScreen('screen-game-over');
    updateHeader(s);
    const winner = (s.players || []).find(p => p.sid === s.winner_sid);
    $('winner-name').textContent = winner ? winner.name : '...';

    // Build stats panel from last game_over data
    const gameOver = State.lastGameOverData;
    const result = State.lastGameResult;
    const statsPanel = $('game-stats-panel');
    statsPanel.innerHTML = '';

    if (gameOver && result) {
        // MVP card
        if (gameOver.mvp) {
            const mvp = document.createElement('div');
            mvp.className = 'stats-card mvp-card';
            mvp.innerHTML = `
                <div class="stats-card-label">MVP</div>
                <div class="stats-card-value">${escapeHtml(gameOver.mvp.name)}</div>
                <div class="stats-card-sub">${gameOver.mvp.cracks} cracks</div>`;
            statsPanel.appendChild(mvp);
        }
        // My stats
        if (result.myStats) {
            const me = result.myStats;
            const mine = document.createElement('div');
            mine.className = 'stats-card';
            mine.innerHTML = `
                <div class="stats-card-label">Your game</div>
                <div class="stats-grid">
                  <div><span class="sg-num">${me.cracks}</span><span class="sg-lab">cracks</span></div>
                  <div><span class="sg-num">${me.rounds_survived}</span><span class="sg-lab">rounds</span></div>
                  <div><span class="sg-num">${me.first_try_cracks}</span><span class="sg-lab">first-try</span></div>
                  <div><span class="sg-num">${me.accuracy}%</span><span class="sg-lab">accuracy</span></div>
                </div>`;
            statsPanel.appendChild(mine);
        }
        // XP card with animated bar
        const xp = document.createElement('div');
        xp.className = 'stats-card xp-card';
        const prog = progressInLevel(result.profile.xp);
        const lvl = result.newLevel;
        xp.innerHTML = `
            <div class="xp-row">
              <div>
                <div class="stats-card-label">Level ${lvl} &middot; ${titleForLevel(lvl)}</div>
                <div class="xp-gain">+${result.xpGain} XP</div>
              </div>
              ${result.leveledUp ? '<div class="level-up-flair">LEVEL UP!</div>' : ''}
            </div>
            <div class="xp-bar-track">
              <div class="xp-bar-fill" id="xp-bar-fill" style="width:0%"></div>
            </div>
            <div class="muted small xp-progress">
              ${prog.capped ? 'Max level' : `${prog.current} / ${prog.needed} to Level ${lvl + 1}`}
            </div>`;
        statsPanel.appendChild(xp);
        // Animate the bar after a beat
        setTimeout(() => {
            const fill = document.getElementById('xp-bar-fill');
            if (fill) fill.style.width = prog.percent + '%';
        }, 250);
    }

    const lb = $('leaderboard');
    lb.innerHTML = '';
    (s.leaderboard || []).forEach(row => {
        const r = document.createElement('div');
        r.className = 'lb-row';
        r.innerHTML = `<div>${escapeHtml(row.name)}</div>
                       <div class="lb-stats">${row.wins} / ${row.games}</div>`;
        lb.appendChild(r);
    });
    if (s.leaderboard.length === 0) {
        lb.innerHTML = '<p class="empty-state muted small">No games yet.</p>';
    }
}

// =========================================================================
// PROGRESSION FLOURISHES
// =========================================================================

function achievementToast(ach) {
    const container = $('toast-container');
    const t = document.createElement('div');
    t.className = 'toast achievement-toast';
    t.innerHTML = `
        <div class="ach-icon">${ach.icon}</div>
        <div class="ach-text">
            <div class="ach-label">Achievement unlocked</div>
            <div class="ach-name">${escapeHtml(ach.name)}</div>
            <div class="ach-desc">${escapeHtml(ach.desc)}</div>
        </div>`;
    container.appendChild(t);
    soundCrack();
    setTimeout(() => t.remove(), 4500);
}

function levelUpToast(newLevel) {
    const container = $('toast-container');
    const t = document.createElement('div');
    t.className = 'toast levelup-toast';
    t.innerHTML = `
        <div class="lvl-icon">⬆</div>
        <div class="ach-text">
            <div class="ach-label">Level up</div>
            <div class="ach-name">Level ${newLevel} &middot; ${titleForLevel(newLevel)}</div>
        </div>`;
    container.appendChild(t);
    soundWin();
    setTimeout(() => t.remove(), 4000);
}

function showDoubleTapBanner(names, isMe) {
    const banner = $('round-banner');
    $('round-banner-big').textContent = isMe ? 'DOUBLE CRACK' : names.toUpperCase();
    $('round-banner-sub').textContent = isMe ? 'two rounds in a row' : 'on a streak';
    showOverlay('round-banner');
    if (isMe) soundWin();
    setTimeout(() => hideOverlay('round-banner'), 1800);
}

// =========================================================================
// SERVER-AWARE PROFILE / XP HELPERS
// =========================================================================

/** Award XP for a game event. Returns the server's response payload
    ({gained, leveled_up, new_level, new_title, ...}) or null on failure. */
async function awardXP({ game, event, multiplayer = false }) {
    if (!State.myName) return null;
    try {
        const res = await fetch('/api/profile/award', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: State.myName, user_id: State.myUserId,
                game, event, multiplayer
            })
        });
        if (!res.ok) return null;
        return await res.json();
    } catch (e) { return null; }
}

/** Fetch the server-side profile. For the current user, pass their uid so
    we look up by user_id (handles same-name collisions correctly). */
async function fetchProfile(name, uid) {
    if (!name) return null;
    try {
        const url = '/api/profile/' + encodeURIComponent(name)
                  + (uid ? '?uid=' + encodeURIComponent(uid) : '');
        const res = await fetch(url);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) { return null; }
}

/** Floats a +XP / +coin / level-up banner on screen for ~3 seconds.
    Call after awardXP() resolves. */
function showXPBanner(award) {
    if (!award || !award.gained) return;
    let banner = document.getElementById('xp-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.id = 'xp-banner';
        banner.className = 'xp-banner';
        document.body.appendChild(banner);
    }
    let html = `<div class="xp-banner-row">
                  <span class="xp-tag">+${award.gained} XP</span>`;
    if (award.coins_gained) {
        html += `<span class="xp-coin">+${award.coins_gained} 🪙</span>`;
    }
    html += `</div>`;
    if (award.leveled_up) {
        html += `<div class="xp-levelup">Level ${award.old_level} → ${award.new_level}</div>`;
        if (award.title_changed) {
            html += `<div class="xp-newtitle">New title: ${escapeHtml(award.new_title)}</div>`;
        }
        triggerConfetti();
    }
    banner.innerHTML = html;
    banner.classList.remove('hidden');
    banner.classList.add('shown');
    clearTimeout(banner._t);
    banner._t = setTimeout(() => {
        banner.classList.remove('shown');
        setTimeout(() => banner.classList.add('hidden'), 400);
    }, 3500);
}

function refreshProfileUI() {
    const card = $('home-profile-card');
    if (!card) return;
    if (State.myName) {
        fetchProfile(State.myName, State.myUserId).then(prof => {
            if (!prof) { renderProfileCardLocal(); return; }
            renderProfileCardServer(prof);
        });
    } else {
        renderProfileCardLocal();
    }
    refreshRecentOpponents();
}

// =========================================================================
// RECENT OPPONENTS — quick-rechallenge tray on home
// =========================================================================

const RECENT_OPPONENTS_KEY = 'gameroom_recent_opponents_v1';
const RECENT_OPPONENTS_MAX = 3;

function loadRecentOpponents() {
    try {
        const raw = localStorage.getItem(RECENT_OPPONENTS_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
}
function saveRecentOpponents(arr) {
    try {
        localStorage.setItem(RECENT_OPPONENTS_KEY, JSON.stringify(arr));
    } catch (e) {}
}
/** Record someone we just finished a 1v1 against. Dedup by user_id. */
function rememberOpponent(user_id, name) {
    if (!user_id || !name) return;
    if (user_id === State.myUserId) return;   // never record yourself
    const arr = loadRecentOpponents()
        .filter(o => o.user_id !== user_id);
    arr.unshift({ user_id, name, at: Date.now() });
    saveRecentOpponents(arr.slice(0, RECENT_OPPONENTS_MAX));
}
function refreshRecentOpponents() {
    const row = document.getElementById('recent-opponents-row');
    const list = document.getElementById('recent-opponents-list');
    if (!row || !list) return;
    const opponents = loadRecentOpponents();
    if (!opponents.length) {
        row.classList.add('hidden');
        list.innerHTML = '';
        return;
    }
    row.classList.remove('hidden');
    list.innerHTML = '';
    opponents.forEach(o => {
        const btn = document.createElement('button');
        btn.className = 'recent-opp-chip';
        const initial = (o.name || '?').charAt(0).toUpperCase();
        btn.innerHTML =
            `<span class="recent-opp-avatar">${escapeHtml(initial)}</span>` +
            `<span class="recent-opp-name">${escapeHtml(o.name)}</span>` +
            `<span class="recent-opp-cta">Challenge</span>`;
        btn.onclick = () => {
            soundClick();
            // Reuse the existing challenge flow — opens the game picker
            sendChallenge(o.user_id, o.name);
        };
        list.appendChild(btn);
    });
}

function renderProfileCardServer(prof) {
    const card = $('home-profile-card');
    if (!card) return;
    card.classList.remove('hidden');
    // Welcome banner + avatar
    const welcomeEl = document.getElementById('profile-welcome-name');
    if (welcomeEl) welcomeEl.textContent = State.myName || prof.name || 'friend';
    // If the server has avatar fields, cache them locally so the next page
    // load can paint the avatar before the network responds.
    if (prof.avatar_color) {
        try { localStorage.setItem('gameroom_avatar_color', prof.avatar_color); } catch (e) {}
    }
    if (prof.avatar_image) {
        try { localStorage.setItem('gameroom_avatar_image', prof.avatar_image); } catch (e) {}
    } else if (prof.avatar_image === null) {
        try { localStorage.removeItem('gameroom_avatar_image'); } catch (e) {}
    }
    const avatarEl = document.getElementById('profile-avatar');
    applyAvatarToEl(avatarEl, State.myName || prof.name,
                    prof.avatar_color || getAvatarColor(),
                    prof.avatar_image || getAvatarImage());

    $('profile-level-num').textContent = prof.level || 1;
    $('profile-title').textContent = prof.title || 'Newcomer';
    const streakBlock = $('profile-streak-block');
    if (streakBlock) {
        streakBlock.innerHTML = `<span class="streak-flame">🪙</span>
                                 <span class="streak-num">${prof.coins || 0}</span>
                                 <span class="streak-lab">coins</span>`;
    }
    const inLevelXP = (prof.xp || 0) - (prof.xp_for_current || 0);
    const levelSpan = (prof.xp_for_next || 100) - (prof.xp_for_current || 0);
    const pct = levelSpan > 0 ? Math.max(0, Math.min(100, (inLevelXP / levelSpan) * 100)) : 0;
    $('profile-xp-fill').style.width = pct + '%';
    const remaining = Math.max(0, (prof.xp_for_next || 100) - (prof.xp || 0));
    $('profile-xp-text').innerHTML = `${(prof.xp || 0).toLocaleString()} XP &middot; ${remaining.toLocaleString()} to Level ${(prof.level || 1) + 1}`;
    // Mini stats on home — wins / losses / streak right under the XP bar
    const winsEl = document.getElementById('profile-wins');
    const lossesEl = document.getElementById('profile-losses');
    const streakCountEl = document.getElementById('profile-streak-count');
    if (winsEl) winsEl.textContent = prof.wins || 0;
    if (lossesEl) lossesEl.textContent = prof.losses || 0;
    if (streakCountEl) streakCountEl.textContent = prof.current_streak || 0;
}

function renderProfileCardLocal() {
    const p = loadProfile();
    const card = $('home-profile-card');
    if (!card) return;
    card.classList.remove('hidden');
    const welcomeEl = document.getElementById('profile-welcome-name');
    if (welcomeEl) welcomeEl.textContent = State.myName || 'friend';
    const avatarEl = document.getElementById('profile-avatar');
    applyAvatarToEl(avatarEl, State.myName, getAvatarColor(), getAvatarImage());
    const lvl = levelFromXP(p.xp || 0);
    $('profile-level-num').textContent = lvl;
    $('profile-title').textContent = titleForLevel(lvl);
    const streakBlock = $('profile-streak-block');
    if (streakBlock) {
        streakBlock.innerHTML = `<span class="streak-flame">🪙</span>
                                 <span class="streak-num">${p.coins || 0}</span>
                                 <span class="streak-lab">coins</span>`;
    }
    const prog = progressInLevel(p.xp || 0);
    $('profile-xp-fill').style.width = prog.percent + '%';
    $('profile-xp-text').innerHTML = prog.capped
        ? (p.xp || 0) + ' XP (max level)'
        : `${p.xp || 0} XP &middot; ${prog.needed - prog.current} to Level ${lvl + 1}`;
}

// =========================================================================
// (Legacy local-profile refresh follows)
// =========================================================================

function renderAchievementsModal() {
    const profile = loadProfile();
    const list = $('achievements-list');
    list.innerHTML = '';
    let unlocked = 0;
    ACHIEVEMENTS.forEach(ach => {
        const have = profile.achievements.includes(ach.id);
        if (have) unlocked++;
        const tile = document.createElement('div');
        tile.className = 'ach-tile' + (have ? ' unlocked' : '');
        tile.innerHTML = `
            <div class="ach-icon">${ach.icon}</div>
            <div class="ach-name">${escapeHtml(ach.name)}</div>
            <div class="ach-desc">${escapeHtml(ach.desc)}</div>`;
        list.appendChild(tile);
    });
    $('ach-progress').textContent = `${unlocked} / ${ACHIEVEMENTS.length}`;
}

function renderProgressModal() {
    // Fetch the SERVER profile (has losses, streaks, MP wins, avatar) so the
    // progress modal shows the real numbers. Fall back to local on failure.
    fetchProfile(State.myName, State.myUserId).then(prof => {
        if (prof) renderProgressFromServer(prof);
        else renderProgressFromLocal();
    });
}

function renderProgressFromServer(prof) {
    const summary = $('progress-summary');
    const xpFor = prof.xp_for_current || 0;
    const xpNext = prof.xp_for_next || 100;
    const span = Math.max(1, xpNext - xpFor);
    const pct = Math.max(0, Math.min(100, ((prof.xp - xpFor) / span) * 100));
    summary.innerHTML = `
        <div class="profile-top">
            <div class="profile-level-block">
                <div class="profile-level">Lvl ${prof.level || 1}</div>
                <div class="profile-title">${escapeHtml(prof.title || 'Newcomer')}</div>
            </div>
            <div class="profile-streak">
                <span class="streak-flame">🔥</span>
                <span class="streak-num">${prof.current_streak || 0}</span>
                <span class="streak-lab">win streak</span>
            </div>
        </div>
        <div class="xp-bar-track"><div class="xp-bar-fill" style="width:${pct}%"></div></div>
        <div class="muted small" style="opacity:0.7;margin-top:6px">${(prof.xp || 0).toLocaleString()} XP &middot; ${Math.max(0, xpNext - prof.xp).toLocaleString()} to next</div>`;

    const games = prof.games_played || 0;
    const wins = prof.wins || 0;
    const losses = prof.losses || 0;
    const winRate = games > 0 ? Math.round((wins / games) * 100) : 0;
    const stats = $('lifetime-stats');
    stats.innerHTML = `
        <div class="stats-card"><div class="stats-card-label">Games</div><div class="stats-card-value">${games}</div></div>
        <div class="stats-card"><div class="stats-card-label">Wins</div><div class="stats-card-value">${wins}</div></div>
        <div class="stats-card"><div class="stats-card-label">Losses</div><div class="stats-card-value">${losses}</div></div>
        <div class="stats-card"><div class="stats-card-label">Win rate</div><div class="stats-card-value">${winRate}%</div></div>
        <div class="stats-card"><div class="stats-card-label">Current streak</div><div class="stats-card-value">${prof.current_streak || 0}</div></div>
        <div class="stats-card"><div class="stats-card-label">Best streak</div><div class="stats-card-value">${prof.best_streak || 0}</div></div>
        <div class="stats-card"><div class="stats-card-label">Coins</div><div class="stats-card-value">${prof.coins || 0}</div></div>`;
}

function renderProgressFromLocal() {
    const profile = loadProfile();
    const lvl = levelFromXP(profile.xp);
    const prog = progressInLevel(profile.xp);
    const summary = $('progress-summary');
    summary.innerHTML = `
        <div class="profile-top">
            <div class="profile-level-block">
                <div class="profile-level">Lvl ${lvl}</div>
                <div class="profile-title">${escapeHtml(titleForLevel(lvl))}</div>
            </div>
            <div class="profile-streak">
                <span class="streak-flame">🔥</span>
                <span class="streak-num">${profile.streak || 0}</span>
                <span class="streak-lab">day streak</span>
            </div>
        </div>
        <div class="xp-bar-track"><div class="xp-bar-fill" style="width:${prog.percent}%"></div></div>
        <div class="muted small" style="opacity:0.7;margin-top:6px">${profile.xp} XP ${prog.capped ? '(max)' : '&middot; ' + (prog.needed - prog.current) + ' to next'}</div>`;

    const winRate = profile.games_played > 0
        ? Math.round((profile.wins / profile.games_played) * 100)
        : 0;
    const stats = $('lifetime-stats');
    stats.innerHTML = `
        <div class="stats-card"><div class="stats-card-label">Games</div><div class="stats-card-value">${profile.games_played}</div></div>
        <div class="stats-card"><div class="stats-card-label">Wins</div><div class="stats-card-value">${profile.wins}</div></div>
        <div class="stats-card"><div class="stats-card-label">Win rate</div><div class="stats-card-value">${winRate}%</div></div>
        <div class="stats-card"><div class="stats-card-label">Win streak</div><div class="stats-card-value">${profile.win_streak || 0}</div></div>`;
}

// =========================================================================
// TURN TIMER
// =========================================================================

function clearTurnTimer() {
    if (State.turnTimerInterval) {
        clearInterval(State.turnTimerInterval);
        State.turnTimerInterval = null;
    }
}
function startTurnTimer(startedAt, duration) {
    clearTurnTimer();
    if (!startedAt) {
        $('timer').textContent = duration;
        return;
    }
    const update = () => {
        if (State.serverState && State.serverState.pause && State.serverState.pause.paused) return;
        const now = Date.now() / 1000;
        const remaining = Math.max(0, duration - (now - startedAt));
        const sec = Math.ceil(remaining);
        $('timer').textContent = sec;
        $('timer').classList.toggle('urgent', sec <= 5);
        if (sec <= 5 && sec > 0 && State.sound.tick) soundTick();
        if (remaining <= 0) clearTurnTimer();
    };
    update();
    State.turnTimerInterval = setInterval(update, 250);
}

// =========================================================================
// PAUSE
// =========================================================================

function handlePauseChange(pause) {
    if (!pause) return;
    if (pause.paused) {
        if ($('pause-overlay').classList.contains('hidden')) {
            State.pauseStartedClientTime = Date.now() / 1000;
        }
        $('pause-by-name').textContent = pause.paused_by_name || 'someone';
        showOverlay('pause-overlay');
        startPauseTimer();
    } else {
        hideOverlay('pause-overlay');
        clearPauseTimer();
    }
}
function clearPauseTimer() {
    if (State.pauseTimerInterval) {
        clearInterval(State.pauseTimerInterval);
        State.pauseTimerInterval = null;
    }
}
function startPauseTimer() {
    clearPauseTimer();
    const start = State.pauseStartedClientTime || (Date.now() / 1000);
    const max = 300;
    const update = () => {
        const elapsed = (Date.now() / 1000) - start;
        const remaining = Math.max(0, max - elapsed);
        const m = Math.floor(remaining / 60);
        const sec = Math.floor(remaining % 60);
        $('pause-timer').textContent = `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
        const pausedBySid = State.serverState && State.serverState.pause && State.serverState.pause.paused_by_sid;
        const isPauser = pausedBySid === State.mySid;
        const resumeBtn = $('btn-resume');
        const hint = $('pause-hint');
        if (elapsed < 60 && !isPauser) {
            resumeBtn.disabled = true;
            hint.textContent = `Only the player who paused can resume in the first minute. ${Math.ceil(60 - elapsed)}s left.`;
        } else {
            resumeBtn.disabled = false;
            hint.textContent = isPauser
                ? 'Tap Resume when ready.'
                : 'Anyone can resume now.';
        }
        if (remaining <= 0) clearPauseTimer();
    };
    update();
    State.pauseTimerInterval = setInterval(update, 500);
}

// =========================================================================
// CONFETTI
// =========================================================================

function triggerConfetti() {
    const canvas = $('confetti-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const colors = ['#1f5fff', '#c8e020', '#d4351c', '#198754', '#0f0f10'];
    const pieces = [];
    for (let i = 0; i < 100; i++) {
        pieces.push({
            x: Math.random() * canvas.width,
            y: -20 - Math.random() * 200,
            vx: (Math.random() - 0.5) * 4,
            vy: 2 + Math.random() * 4,
            rot: Math.random() * Math.PI * 2,
            vr: (Math.random() - 0.5) * 0.2,
            color: colors[Math.floor(Math.random() * colors.length)],
            size: 8 + Math.random() * 6
        });
    }
    if (State.confettiAnimation) cancelAnimationFrame(State.confettiAnimation);
    const start = Date.now();
    function frame() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        pieces.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            p.vy += 0.1;
            p.rot += p.vr;
            ctx.save();
            ctx.translate(p.x, p.y);
            ctx.rotate(p.rot);
            ctx.fillStyle = p.color;
            ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
            ctx.restore();
        });
        if (Date.now() - start < 4000) {
            State.confettiAnimation = requestAnimationFrame(frame);
        } else {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }
    frame();
}

// =========================================================================
// EVENT WIRING
// =========================================================================

function wireLanding() {
    const guestBtn = $('btn-landing-guest');
    if (guestBtn) {
        guestBtn.onclick = () => {
            soundClick();
            if (State.myName) {
                showScreen('screen-home');
                refreshProfileUI();
                refreshHomeOnlineCount();
            } else {
                showScreen('screen-guest');
                setTimeout(() => { try { $('input-name').focus(); } catch (e) {} }, 50);
            }
        };
    }
    const signinBtn = $('btn-landing-signin');
    if (signinBtn) {
        signinBtn.onclick = () => {
            toast('Sign-in is coming soon. Use guest for now.');
        };
    }
    // Home-screen Players-online button (always visible, not buried in menu)
    const homeOnline = $('home-online-btn');
    if (homeOnline) {
        homeOnline.onclick = () => {
            soundClick();
            openOnlineModal();
        };
    }
}

/** Refresh the count badge on the home Players-Online button. */
async function refreshHomeOnlineCount() {
    try {
        const me = State.myUserId || '';
        const res = await fetch('/api/online?me=' + encodeURIComponent(me));
        const data = await res.json();
        const count = (data.users || []).length;
        const el = document.getElementById('home-online-count');
        if (el) el.textContent = String(count);
        const badge = document.getElementById('menu-online-badge');
        if (badge) badge.textContent = String(count);
    } catch (e) {}
}

function wireInviteModal() {
    const copyBtn = $('btn-invite-copy');
    const shareBtn = $('btn-invite-share');
    const cancelBtn = $('btn-invite-cancel');

    if (copyBtn) {
        copyBtn.onclick = async () => {
            soundClick();
            const url = getInviteUrl();
            if (!url) { toast('No code yet'); return; }
            try {
                await navigator.clipboard.writeText(url);
                toast('Link copied');
            } catch (e) {
                // Fallback: select text in the code box for manual copy
                try {
                    const range = document.createRange();
                    range.selectNodeContents($('invite-code-big'));
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    toast('Code selected — long-press to copy');
                } catch (e2) {
                    toast('Could not copy — long-press the code');
                }
            }
        };
    }
    if (shareBtn) {
        shareBtn.onclick = async () => {
            soundClick();
            const url = getInviteUrl();
            if (!url) return;
            const code = (State.serverState && State.serverState.room_code) || '';
            const hint = (State.serverState && State.serverState.mode_hint) || '';
            const game = (State.serverState && State.serverState.game_type) || 'game';
            const msg = hint === 'faceoff'
                ? `Face off with me on GameRoom (${game}). Code: ${code}`
                : `Join my GameRoom game (${game}). Code: ${code}`;
            try {
                if (navigator.share) {
                    await navigator.share({ title: 'GameRoom', text: msg, url });
                } else {
                    await navigator.clipboard.writeText(url);
                    toast('Link copied');
                }
            } catch (e) { /* user cancelled share */ }
        };
    }
    if (cancelBtn) {
        cancelBtn.onclick = () => {
            soundClick();
            // Cancel the room and go home. This kills the code permanently.
            hideInviteModal();
            leaveCurrentRoomIfAny();
            showScreen('screen-home');
            refreshProfileUI();
            toast('Game cancelled');
        };
    }
}

function wireHome() {
    // Game cards go straight to mode picker. By this point the player MUST
    // have entered their name (the landing → guest-name flow guarantees it).
    document.querySelectorAll('.game-card[data-game]').forEach(card => {
        // Inject a small "?" info pip in the top-right that opens the howto
        // pre-targeted to this game. Stopping propagation prevents the parent
        // card click handler from also firing.
        if (!card.querySelector('.game-card-info-pip')) {
            const pip = document.createElement('span');
            pip.className = 'game-card-info-pip';
            pip.textContent = '?';
            pip.setAttribute('aria-label', 'How to play');
            pip.onclick = (e) => {
                e.stopPropagation();
                soundClick();
                try {
                    const g = card.dataset.game;
                    // Map home-card 'geo' to howto's 'geography'
                    const mapped = (g === 'geo') ? 'geography' : g;
                    openHowtoModal(mapped);
                } catch (err) {}
            };
            card.appendChild(pip);
        }
        card.onclick = () => {
            if (card.classList.contains('disabled') || card.disabled) {
                toast('That game is coming soon');
                return;
            }
            soundClick();
            leaveCurrentRoomIfAny();
            const game = card.dataset.game;
            State.selectedGame = game;
            if (!State.myName) {
                showScreen('screen-guest');
                setTimeout(() => { try { $('input-name').focus(); } catch (e) {} }, 50);
                return;
            }
            showModePicker(game);
        };
    });
    document.querySelectorAll('[data-back]').forEach(b => {
        b.onclick = () => { soundClick(); showScreen(b.dataset.back); };
    });
}

// Game-specific copy and capability flags for the mode picker.
// Each entry says what each mode does for that game (or 'coming next' if unbuilt).
const GAME_MODE_CONFIG = {
    guessduel: {
        label: 'GuessDuel',
        title: 'Guess my number first',
        blurb: 'Pick a secret number. Take turns guessing. Higher / lower hints.',
        solo: { available: true, desc: 'vs Computer' },
        faceoff: { available: true, desc: '1v1, send a link' },
        group: { available: true, desc: '3-8 players, share a room' }
    },
    wordchain: {
        label: 'WordChain',
        title: 'Words get longer each round',
        blurb: 'Computer announces a letter. Words must start with it. Length grows.',
        solo: { available: true, desc: 'vs Computer' },
        faceoff: { available: true, desc: '1v1, send a link' },
        group: { available: true, desc: '3-8 players, share a room' }
    },
    oneshot: {
        label: 'OneShot',
        title: 'One number, six guesses',
        blurb: '1-100. Daily mode is the same number for everyone.',
        solo: { available: true, desc: "Today's daily puzzle" },
        faceoff: { available: false, desc: 'Coming next' },
        group: { available: false, desc: 'Coming next' }
    },
    footymind: {
        label: 'FootyMind',
        title: 'Guess the footballer',
        blurb: "From their career path. Type 'messi', 'leo', 'cr7' — we accept all.",
        solo: { available: true, desc: '10 players, beat your score' },
        faceoff: { available: false, desc: 'Coming next' },
        group: { available: false, desc: 'Coming next' }
    },
    trivia: {
        label: 'TriviaRush',
        title: '10 mixed questions',
        blurb: 'Multiple choice, "which is older", true/false. No filler.',
        solo: { available: true, desc: 'Beat your high score' },
        faceoff: { available: false, desc: 'Coming next' },
        group: { available: false, desc: 'Coming next' }
    },
    geo: {
        label: 'Geography',
        title: 'Flags, capitals, landmarks',
        blurb: 'Pick a sub-mode in the next screen — 10 questions per round.',
        solo: { available: true, desc: 'Pick a sub-mode' },
        faceoff: { available: true, desc: '1v1, fastest correct wins' },
        group: { available: true, desc: '3-8 players, race to answer' }
    },
    timeshot: {
        label: 'TimeShot',
        title: 'Stop the hidden clock',
        blurb: 'Computer announces a target time. Tap to start, tap to stop. You don\'t see the count. Closest wins.',
        solo: { available: true, desc: 'vs Computer' },
        faceoff: { available: true, desc: '1v1, send a link' },
        group: { available: true, desc: '3-8 players, share a room' }
    }
};

function showModePicker(game) {
    const cfg = GAME_MODE_CONFIG[game];
    if (!cfg) {
        toast('Unknown game');
        return;
    }
    $('mode-pick-game-label').textContent = cfg.label.toUpperCase();
    $('mode-pick-title').textContent = cfg.title;
    $('mode-pick-blurb').textContent = cfg.blurb;
    $('mode-pick-solo-desc').textContent = cfg.solo.desc;
    $('mode-pick-faceoff-desc').textContent = cfg.faceoff.desc;
    $('mode-pick-group-desc').textContent = cfg.group.desc;
    // Disable unavailable modes
    document.querySelectorAll('#screen-mode-pick .mode-card[data-pickmode]').forEach(c => {
        const m = c.dataset.pickmode;
        c.classList.remove('active');
        const isAvailable = cfg[m] && cfg[m].available;
        c.classList.toggle('disabled', !isAvailable);
    });
    // Coming-soon note
    const someUnavailable = !cfg.faceoff.available || !cfg.group.available;
    $('mode-pick-coming-note').textContent = someUnavailable
        ? 'Multiplayer for this game is coming in the next update.'
        : '';
    showScreen('screen-mode-pick');
    resetModePickerUI();
}

function wireModePicker() {
    // Clicking a mode card reveals the appropriate settings + Continue button.
    document.querySelectorAll('#screen-mode-pick .mode-card[data-pickmode]').forEach(c => {
        c.onclick = () => {
            const game = State.selectedGame;
            const cfg = GAME_MODE_CONFIG[game];
            const mode = c.dataset.pickmode;
            if (!cfg || !cfg[mode]) return;
            if (!cfg[mode].available) {
                soundLose();
                toast(`${cfg.label} ${mode === 'faceoff' ? 'Face-off' : 'Friend group'} is coming next session`);
                return;
            }
            soundClick();
            State.pickedMode = mode;

            // Highlight the chosen card
            document.querySelectorAll('#screen-mode-pick .mode-card[data-pickmode]').forEach(x => {
                x.classList.toggle('active', x === c);
            });

            // Show the settings panel + the correct sub-section
            const settingsWrap = $('mode-pick-settings');
            const soloSet = $('mode-pick-solo-settings');
            const faceoffSet = $('mode-pick-faceoff-settings');
            const continueBtn = $('btn-mode-pick-continue');
            if (settingsWrap) settingsWrap.classList.remove('hidden');
            // Solo settings only useful for GuessDuel/WordChain (bot difficulty)
            const showSolo = (mode === 'solo' && (game === 'guessduel' || game === 'wordchain'));
            // Face-off settings (best of series): GuessDuel, WordChain, TimeShot
            const showFaceoff = (mode === 'faceoff' &&
                (game === 'guessduel' || game === 'wordchain' || game === 'timeshot'));
            if (soloSet) soloSet.classList.toggle('hidden', !showSolo);
            if (faceoffSet) faceoffSet.classList.toggle('hidden', !showFaceoff);
            if (!showSolo && !showFaceoff && settingsWrap) {
                // No settings needed — hide the wrap entirely
                settingsWrap.classList.add('hidden');
            }
            if (continueBtn) {
                continueBtn.classList.remove('hidden');
                continueBtn.textContent = (mode === 'solo')
                    ? 'Start solo'
                    : (mode === 'faceoff' ? 'Create face-off' : 'Continue');
            }
        };
    });

    // Settings buttons store choices in State
    document.querySelectorAll('#screen-mode-pick [data-modepick-bot]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedBot = b.dataset.modepickBot;
            State.selectedWcBot = b.dataset.modepickBot;
            document.querySelectorAll('#screen-mode-pick [data-modepick-bot]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
    document.querySelectorAll('#screen-mode-pick [data-modepick-firstto]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedFirstTo = parseInt(b.dataset.modepickFirstto, 10) || 1;
            document.querySelectorAll('#screen-mode-pick [data-modepick-firstto]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });

    const continueBtn = $('btn-mode-pick-continue');
    if (continueBtn) {
        continueBtn.onclick = () => {
            soundClick();
            const game = State.selectedGame;
            const mode = State.pickedMode;
            if (!game || !mode) return;
            handleModePicked(game, mode);
        };
    }
}

function resetModePickerUI() {
    // Called when entering the mode-pick screen so it's a clean slate
    document.querySelectorAll('#screen-mode-pick .mode-card[data-pickmode]').forEach(x =>
        x.classList.remove('active'));
    const wrap = document.getElementById('mode-pick-settings');
    if (wrap) wrap.classList.add('hidden');
    const cont = document.getElementById('btn-mode-pick-continue');
    if (cont) cont.classList.add('hidden');
}

function handleModePicked(game, mode) {
    /* Solo: jump straight into the game (or its intro screen for difficulty/categories).
       Face-off / Group: go to the action chooser (Create new / Join with code). */
    State.pickedMode = mode;

    if (mode === 'solo') {
        // Game-specific solo launchers
        if (game === 'oneshot') { oneshotShowIntro(); return; }
        if (game === 'footymind') { footymindShowIntro(); return; }
        if (game === 'trivia') { triviaShowIntro(); return; }
        if (game === 'geo') { geoShowIntro(); return; }
        if (game === 'timeshot') { tsShowIntro('solo'); return; }
        // For GuessDuel and WordChain, solo still uses a room. Create one and
        // pre-select Solo mode so the lobby start_game uses the right options.
        if (game === 'guessduel') {
            State.selectedMode = 'solo';
            socket.emit('create_room', { game_type: 'guessduel', mode_hint: 'solo' });
            return;
        }
        if (game === 'wordchain') {
            State.selectedWcMode = 'solo';
            socket.emit('create_room', { game_type: 'wordchain', mode_hint: 'solo' });
            return;
        }
    }

    // Face-off or Group — go to "Create or join?" first
    // The client uses 'geo' as the home-card identifier but the server's
    // game_type for multiplayer is 'geography' — translate at this boundary.
    if (game === 'geo') {
        State.selectedGame = 'geography';
    }
    const cfg = GAME_MODE_CONFIG[game];
    if (mode === 'faceoff') {
        $('action-title').textContent = `${cfg.label} Face-off`;
        $('action-blurb').textContent = 'Create a match and send the link to your opponent, or join one they shared with you.';
    } else if (mode === 'group') {
        $('action-title').textContent = `${cfg.label} Friend group`;
        $('action-blurb').textContent = 'Create a room and share the link with your group, or join an existing room.';
    }
    // Pre-set the lobby mode based on what they picked so the lobby
    // shows the right card and the Start button works
    if (game === 'guessduel') State.selectedMode = mode;
    if (game === 'wordchain') State.selectedWcMode = mode === 'faceoff' ? 'faceoff' : 'group';
    if (game === 'timeshot') State.tsMode = mode;
    showScreen('screen-action');
}

function wireGuestName() {
    const advance = () => {
        const name = ($('input-name').value || '').trim();
        if (!name) { $('name-error').textContent = 'Please enter a name'; return; }
        if (name.length > 20) { $('name-error').textContent = 'Name too long (20 max)'; return; }
        State.myName = name;
        $('name-error').textContent = '';

        // Save name to localStorage so we don't ask again
        try { localStorage.setItem('gameroom_name', name); } catch (e) {}

        // Tell the server our identity for the new connection
        try { socket.emit('hello', { user_id: State.myUserId, name }); } catch (e) {}

        const presetCode = getInitialRoomCode();
        if (presetCode) {
            // /r/CODE or /m/CODE direct-link flow — join the room directly
            socket.emit('join_room', { code: presetCode, name });
        } else {
            // Normal landing flow — now show the game grid
            showScreen('screen-home');
            refreshProfileUI();
        }
    };
    $('btn-name-next').onclick = () => { soundClick(); advance(); };
    $('input-name').onkeydown = (e) => { if (e.key === 'Enter') advance(); };
}

function wireActionChooser() {
    $('btn-create-game').onclick = () => {
        soundClick();
        // Defensive: leave any stale room before creating a fresh one
        leaveCurrentRoomIfAny();
        const mode_hint = State.pickedMode === 'faceoff' ? 'faceoff' : 'group';
        debugLog('create_room game=' + State.selectedGame + ' hint=' + mode_hint);
        socket.emit('create_room', {
            game_type: State.selectedGame || 'guessduel',
            mode_hint: mode_hint
        });
    };
    $('btn-show-join').onclick = () => {
        soundClick();
        showScreen('screen-join-code');
        $('input-code').focus();
    };
}

function wireJoinCode() {
    const submit = () => {
        const code = ($('input-code').value || '').trim().toUpperCase();
        if (!code) { $('join-code-error').textContent = 'Enter the code'; return; }
        $('join-code-error').textContent = '';
        socket.emit('join_room', { code, name: State.myName });
    };
    $('btn-join-with-code').onclick = () => { soundClick(); submit(); };
    $('input-code').onkeydown = (e) => { if (e.key === 'Enter') submit(); };
    $('input-code').oninput = (e) => {
        e.target.value = e.target.value.toUpperCase();
    };
}

function wireLobby() {
    // Mode cards (scoped to lobby — other screens have their own mode-cards)
    document.querySelectorAll('#lobby-guessduel-card .mode-card').forEach(card => {
        card.onclick = () => {
            soundClick();
            State.selectedMode = card.dataset.mode;
            syncModeUI();
        };
    });
    // Variant cards
    document.querySelectorAll('#lobby-guessduel-card .variant-card').forEach(card => {
        card.onclick = () => {
            soundClick();
            State.selectedGroupVariant = card.dataset.variant;
            syncModeUI();
        };
    });
    // Bot diff
    document.querySelectorAll('#solo-options .seg-btn').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedBot = b.dataset.bot;
            syncModeUI();
        };
    });
    // First to
    document.querySelectorAll('#faceoff-options .seg-btn').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedFirstTo = parseInt(b.dataset.firstto);
            syncModeUI();
        };
    });
    // Bracket size
    document.querySelectorAll('#bracket-sub .seg-btn').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedBracketSize = parseInt(b.dataset.bracket);
            syncModeUI();
        };
    });
    // KOTH target
    document.querySelectorAll('#koth-sub .seg-btn').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedKothTarget = parseInt(b.dataset.koth);
            syncModeUI();
        };
    });

    // WordChain controls
    document.querySelectorAll('#lobby-wordchain-card .mode-card[data-wcmode]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedWcMode = b.dataset.wcmode;
            syncWordChainUI();
        };
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wcdiff]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedWcDifficulty = b.dataset.wcdiff;
            syncWordChainUI();
        };
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wctimer]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedWcTimer = parseInt(b.dataset.wctimer);
            syncWordChainUI();
        };
    });
    document.querySelectorAll('#lobby-wordchain-card .seg-btn[data-wcbot]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedWcBot = b.dataset.wcbot;
            syncWordChainUI();
        };
    });

    // Old inline copy button is gone — Copy/Share now live in the invite
    // modal (wired by wireInviteModal). Null-guard for any leftover refs.
    const oldCopyBtn = document.getElementById('btn-copy-link');
    if (oldCopyBtn) {
        oldCopyBtn.onclick = () => {
            soundClick();
            const url = getInviteUrl();
            if (!url) return;
            try {
                navigator.clipboard.writeText(url);
                toast('Link copied');
            } catch (e) {
                const tmp = document.createElement('input');
                tmp.value = url;
                document.body.appendChild(tmp);
                tmp.select();
                try { document.execCommand('copy'); toast('Link copied'); }
                catch (err) { toast('Copy failed'); }
                tmp.remove();
            }
        };
    }

    $('btn-start').onclick = () => {
        soundClick();
        const gameType = (State.serverState && State.serverState.game_type) || 'guessduel';
        if (gameType === 'wordchain') {
            if (!State.selectedWcMode) {
                toast('Choose a mode first: Solo, or With friends');
                return;
            }
            const payload = {
                mode: State.selectedWcMode,
                wc_difficulty: State.selectedWcDifficulty,
                wc_turn_timer: State.selectedWcTimer,
                bot_difficulty: State.selectedWcBot,
                first_to: State.selectedFirstTo || 1
            };
            socket.emit('start_game', payload);
            return;
        }
        if (gameType === 'geography') {
            socket.emit('start_game', {
                mode: State.pickedMode || 'faceoff',
                geo_mode: GeoMP.selectedMode,
                total_rounds: GeoMP.selectedRounds,
                geo_difficulty: 'mixed'
            });
            return;
        }
        if (!State.selectedMode) {
            toast('Choose a mode first: Solo, Face-off, or Friend group');
            return;
        }
        const payload = {
            mode: State.selectedMode,
            bot_difficulty: State.selectedBot,
            first_to: State.selectedFirstTo,
            group_variant: State.selectedGroupVariant,
            bracket_size: State.selectedBracketSize,
            koth_target: State.selectedKothTarget
        };
        socket.emit('start_game', payload);
    };
}

function syncSetupInputsForDifficulty(diff) {
    const minEl = $('input-min');
    const maxEl = $('input-max');
    if (diff === 'easy') {
        minEl.step = '1';
        maxEl.step = '1';
        minEl.min = '0';      // no negatives on easy
        if (parseFloat(minEl.value) < 0) minEl.value = '1';
    } else if (diff === 'medium') {
        minEl.step = '0.01';
        maxEl.step = '0.01';
        minEl.min = '0';      // no negatives on medium
        if (parseFloat(minEl.value) < 0) minEl.value = '1';
    } else if (diff === 'hard') {
        minEl.step = '0.01';
        maxEl.step = '0.01';
        minEl.removeAttribute('min');   // allow negatives on hard
    }
}

function wireSetup() {
    document.querySelectorAll('#setup-host-view .seg-btn[data-difficulty]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedDifficulty = b.dataset.difficulty;
            document.querySelectorAll('#setup-host-view .seg-btn[data-difficulty]').forEach(x =>
                x.classList.toggle('active', x === b));
            const desc = {
                easy:   'Easy: whole numbers, positive range only.',
                medium: 'Medium: decimals to 2 places, positive range.',
                hard:   'Hard: decimals AND negative numbers allowed.'
            };
            $('difficulty-desc').textContent = desc[b.dataset.difficulty] || '';
            syncSetupInputsForDifficulty(b.dataset.difficulty);
        };
    });
    document.querySelectorAll('#setup-host-view .seg-btn[data-timer]').forEach(b => {
        b.onclick = () => {
            soundClick();
            State.selectedTimer = parseInt(b.dataset.timer);
            document.querySelectorAll('#setup-host-view .seg-btn[data-timer]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
    $('btn-submit-settings').onclick = () => {
        soundClick();
        const min = parseFloat($('input-min').value);
        const max = parseFloat($('input-max').value);
        if (isNaN(min) || isNaN(max)) { $('setup-error').textContent = 'Enter valid numbers'; return; }
        if (min >= max) { $('setup-error').textContent = 'Min must be less than Max'; return; }
        $('setup-error').textContent = '';
        socket.emit('submit_settings', {
            difficulty: State.selectedDifficulty,
            range_min: min,
            range_max: max,
            turn_timer: State.selectedTimer
        });
    };
    // Apply initial setup
    syncSetupInputsForDifficulty(State.selectedDifficulty);
}

function wireSecrets() {
    $('btn-submit-secret').onclick = () => {
        soundClick();
        const v = $('input-secret').value;
        if (v === '') { $('secret-error').textContent = 'Enter a number'; return; }
        $('secret-error').textContent = '';
        socket.emit('submit_secret', { value: v });
    };
    $('input-secret').onkeydown = (e) => { if (e.key === 'Enter') $('btn-submit-secret').click(); };
}

function wirePickTarget() {
    $('btn-lock-target').onclick = () => {
        soundClick();
        if (!State.pendingTarget) {
            $('target-error').textContent = 'Pick someone first';
            return;
        }
        $('target-error').textContent = '';
        socket.emit('pick_target', { target_sid: State.pendingTarget });
    };
}

function wirePlaying() {
    $('btn-submit-guess').onclick = () => {
        soundClick();
        const v = $('input-guess').value;
        if (v === '') { $('guess-error').textContent = 'Enter a number'; return; }
        $('guess-error').textContent = '';
        $('btn-submit-guess').disabled = true;
        socket.emit('submit_guess', { value: v });
    };
    $('input-guess').onkeydown = (e) => {
        if (e.key === 'Enter' && !$('btn-submit-guess').disabled) $('btn-submit-guess').click();
    };
}

function wirePause() {
    $('btn-resume').onclick = () => {
        soundClick();
        socket.emit('resume');
    };
}

function wireGameOver() {
    $('btn-next-game').onclick = () => {
        soundClick();
        socket.emit('next_game');
    };
    $('btn-rematch').onclick = () => {
        soundClick();
        socket.emit('rematch');
    };
}

function wireMenu() {
    $('btn-menu').onclick = () => { soundClick(); showOverlay('menu-overlay'); };
    document.querySelectorAll('[data-close]').forEach(b => {
        b.onclick = (e) => {
            soundClick();
            hideOverlay(b.dataset.close);
            const m = document.getElementById(b.dataset.close);
            if (m && m.classList.contains('modal')) m.classList.add('hidden');
        };
    });
    $('menu-pause').onclick = () => {
        hideOverlay('menu-overlay');
        debugLog('pause click: phase=' + State.phase
                 + ' hasState=' + !!State.serverState
                 + ' alreadyPaused=' + !!(State.serverState
                                          && State.serverState.pause
                                          && State.serverState.pause.paused));
        // Defensive — pause data may be missing during a transition
        const isAlreadyPaused = !!(State.serverState
            && State.serverState.pause
            && State.serverState.pause.paused);
        if (isAlreadyPaused) {
            toast('Already paused');
            return;
        }
        if (!State.serverState) {
            toast('Pause only works during a game');
            return;
        }
        if (!['playing', 'secrets', 'pick_target'].includes(State.phase)) {
            toast('You can only pause during a live game (currently: ' + State.phase + ')');
            return;
        }
        debugLog('emitting pause');
        socket.emit('pause');
        toast('Pausing...');
    };
    $('menu-leaderboard').onclick = () => {
        hideOverlay('menu-overlay');
        const lb = $('modal-leaderboard');
        lb.innerHTML = '';
        const data = (State.serverState && State.serverState.leaderboard) || [];
        if (data.length === 0) {
            lb.innerHTML = '<p class="empty-state muted small">No games played in this room yet.</p>';
        } else {
            data.forEach(row => {
                const r = document.createElement('div');
                r.className = 'lb-row';
                r.innerHTML = `<div>${escapeHtml(row.name)}</div>
                               <div class="lb-stats">${row.wins} / ${row.games}</div>`;
                lb.appendChild(r);
            });
        }
        $('leaderboard-modal').classList.remove('hidden');
    };
    $('menu-achievements').onclick = () => {
        hideOverlay('menu-overlay');
        renderAchievementsModal();
        $('achievements-modal').classList.remove('hidden');
    };
    $('menu-profile').onclick = () => {
        hideOverlay('menu-overlay');
        renderProgressModal();
        $('progress-modal').classList.remove('hidden');
    };
    const editProfileBtn = document.getElementById('menu-edit-profile');
    if (editProfileBtn) {
        editProfileBtn.onclick = () => {
            hideOverlay('menu-overlay');
            openEditProfileModal();
        };
    }
    $('menu-invite').onclick = () => {
        hideOverlay('menu-overlay');
        if (!State.roomCode) { toast('Not in a room'); return; }
        const url = getInviteUrl();
        try {
            navigator.clipboard.writeText(url);
            toast('Invite link copied');
        } catch (e) {
            toast(url);
        }
    };
    $('menu-leave').onclick = () => {
        hideOverlay('menu-overlay');
        // Show prompt if either in a multiplayer room OR mid-game in a solo
        // game (geography, trivia, etc.). Free transitions when on home/menu.
        if (!State.roomCode && !isOnLivePlayScreen()) {
            showScreen('screen-home');
            return;
        }
        showLeaveModal();
    };
    $('btn-leave-cancel').onclick = () => { soundClick(); $('leave-modal').classList.add('hidden'); };
    $('btn-leave-confirm').onclick = () => {
        soundClick();
        $('leave-modal').classList.add('hidden');
        if (State.roomCode) {
            // Multiplayer room — server handles forfeit logic
            socket.emit('leave_game');
        } else {
            // Solo game forfeit — record as a loss in the player's profile,
            // then go home. Stat reset to 0 streak + 1 loss + 1 game played.
            if (isOnLivePlayScreen()) {
                socket.emit('solo_forfeit');
                toast('Recorded as a loss');
            }
            Geo._roundActive = false;
            setTimeout(() => { refreshProfileUI(); }, 300);
            showScreen('screen-home');
        }
    };
    $('menu-home').onclick = () => {
        hideOverlay('menu-overlay');
        if (State.roomCode || isOnLivePlayScreen()) {
            showLeaveModal();
        } else {
            refreshProfileUI();
            showScreen('screen-home');
        }
    };
    $('menu-settings').onclick = () => {
        hideOverlay('menu-overlay');
        $('settings-modal').classList.remove('hidden');
    };
    $('menu-about').onclick = () => {
        hideOverlay('menu-overlay');
        $('about-modal').classList.remove('hidden');
    };
    const onlineBtn = document.getElementById('menu-online');
    if (onlineBtn) {
        onlineBtn.onclick = () => {
            hideOverlay('menu-overlay');
            openOnlineModal();
        };
    }
    const howtoBtn = document.getElementById('menu-howto');
    if (howtoBtn) {
        howtoBtn.onclick = () => {
            hideOverlay('menu-overlay');
            openHowtoModal('guessduel');
        };
    }
}

function wireSettings() {
    document.querySelectorAll('.theme-card').forEach(c => {
        c.onclick = () => { soundClick(); applyTheme(c.dataset.theme); };
    });
    $('toggle-sound').onclick = () => {
        State.sound.enabled = !State.sound.enabled;
        syncSoundToggles();
        saveSoundPrefs();
        if (State.sound.enabled) soundClick();
    };
    $('toggle-tick').onclick = () => {
        State.sound.tick = !State.sound.tick;
        syncSoundToggles();
        saveSoundPrefs();
    };
    $('btn-reset-lb').onclick = () => {
        socket.emit('reset_leaderboard');
        $('settings-modal').classList.add('hidden');
    };
}

// =========================================================================
// BOOT
// =========================================================================

// =========================================================================
// ONESHOT (daily seeded number puzzle, single player)
// =========================================================================

const OneShot = {
    info: null,             // {date, range_min, range_max, max_guesses}
    guesses: [],            // [{value, feedback}]
    secret: null,
    state: 'idle',          // idle | playing | won | lost
    stats: null
};

const ONESHOT_STATS_KEY = 'gameroom_oneshot_stats_v1';

function oneshotLoadStats() {
    try {
        const raw = localStorage.getItem(ONESHOT_STATS_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return { played: 0, won: 0, streak: 0, best_streak: 0, last_date: null, history: {} };
}
function oneshotSaveStats(stats) {
    try { localStorage.setItem(ONESHOT_STATS_KEY, JSON.stringify(stats)); } catch (e) {}
}

async function oneshotFetchToday() {
    const res = await fetch('/api/oneshot/today');
    if (!res.ok) throw new Error('fetch failed');
    return res.json();
}

async function oneshotSubmitGuess(date, value) {
    const res = await fetch('/api/oneshot/guess', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ date, guess: value })
    });
    if (!res.ok) throw new Error('guess failed');
    return res.json();
}

async function oneshotRevealAnswer(date) {
    const res = await fetch('/api/oneshot/reveal', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ date })
    });
    if (!res.ok) throw new Error('reveal failed');
    return res.json();
}

function oneshotShowIntro() {
    OneShot.stats = oneshotLoadStats();
    const stats = OneShot.stats;
    $('oneshot-streak-current').textContent = stats.streak || 0;
    $('oneshot-streak-best').textContent = stats.best_streak || 0;
    $('oneshot-streak-played').textContent = stats.played || 0;
    // Check if today already played
    const today = new Date().toISOString().slice(0, 10);
    if (stats.history && stats.history[today]) {
        $('btn-oneshot-start').textContent = "View today's result";
    } else {
        $('btn-oneshot-start').textContent = "Play today's puzzle";
    }
    const dateStr = new Date().toLocaleDateString(undefined, {
        weekday: 'long', month: 'long', day: 'numeric'
    });
    $('oneshot-date').textContent = dateStr;
    showScreen('screen-oneshot-intro');
}

async function oneshotBeginPlay() {
    try {
        OneShot.info = await oneshotFetchToday();
    } catch (e) {
        toast('Could not load today\'s puzzle');
        return;
    }
    const today = OneShot.info.date;
    const stats = oneshotLoadStats();
    // Already finished today? jump to done screen
    if (stats.history && stats.history[today]) {
        OneShot.guesses = stats.history[today].guesses || [];
        OneShot.state = stats.history[today].won ? 'won' : 'lost';
        OneShot.secret = stats.history[today].secret;
        oneshotShowDone();
        return;
    }
    OneShot.guesses = [];
    OneShot.secret = null;
    OneShot.state = 'playing';
    oneshotRenderPlay();
    showScreen('screen-oneshot-play');
    setTimeout(() => { try { $('oneshot-input').focus(); } catch (e) {} }, 80);
}

function oneshotRenderPlay() {
    const info = OneShot.info;
    if (!info) return;
    const max = info.max_guesses || 6;
    const left = max - OneShot.guesses.length;
    $('oneshot-guesses-left').textContent = left;
    // pips
    const pipsEl = $('oneshot-pips');
    pipsEl.innerHTML = '';
    for (let i = 0; i < max; i++) {
        const pip = document.createElement('span');
        pip.className = 'oneshot-pip-big';
        if (i < OneShot.guesses.length) {
            const g = OneShot.guesses[i];
            if (g.feedback === 'correct') pip.classList.add('right');
            else pip.classList.add('wrong');
        }
        pipsEl.appendChild(pip);
    }
    // history (newest first for visibility)
    const histEl = $('oneshot-history');
    histEl.innerHTML = '';
    OneShot.guesses.slice().reverse().forEach(g => {
        const row = document.createElement('div');
        row.className = 'oneshot-guess-row ' + g.feedback;
        const fbText = g.feedback === 'higher' ? 'TRY HIGHER'
                     : g.feedback === 'lower'  ? 'TRY LOWER'
                     : 'GOT IT';
        row.innerHTML = `<span class="v">${g.value}</span><span class="f">${fbText}</span>`;
        histEl.appendChild(row);
    });
    $('oneshot-input').value = '';
    $('oneshot-input').disabled = false;
    $('oneshot-submit').disabled = false;
    $('oneshot-error').textContent = '';
}

async function oneshotSubmit() {
    const input = $('oneshot-input');
    const v = parseInt(input.value);
    const info = OneShot.info;
    if (isNaN(v) || v < info.range_min || v > info.range_max) {
        $('oneshot-error').textContent = `Number between ${info.range_min} and ${info.range_max}`;
        return;
    }
    $('oneshot-error').textContent = '';
    $('oneshot-submit').disabled = true;
    let resp;
    try {
        resp = await oneshotSubmitGuess(info.date, v);
    } catch (e) {
        $('oneshot-error').textContent = 'Network error';
        $('oneshot-submit').disabled = false;
        return;
    }
    if (resp.error) {
        $('oneshot-error').textContent = resp.error;
        $('oneshot-submit').disabled = false;
        return;
    }
    OneShot.guesses.push({ value: resp.guess, feedback: resp.feedback });
    if (resp.feedback === 'correct') {
        soundCrack();
        OneShot.secret = resp.secret;
        OneShot.state = 'won';
        oneshotFinish();
        return;
    } else {
        soundTick();
    }
    if (OneShot.guesses.length >= info.max_guesses) {
        // Out of guesses
        try {
            const r = await oneshotRevealAnswer(info.date);
            OneShot.secret = r.secret;
        } catch (e) {}
        OneShot.state = 'lost';
        soundLose();
        oneshotFinish();
        return;
    }
    oneshotRenderPlay();
    setTimeout(() => { try { $('oneshot-input').focus(); } catch (e) {} }, 50);
}

function oneshotFinish() {
    const today = OneShot.info.date;
    const stats = oneshotLoadStats();
    stats.played = (stats.played || 0) + 1;
    if (OneShot.state === 'won') {
        stats.won = (stats.won || 0) + 1;
        const yest = new Date(today);
        yest.setUTCDate(yest.getUTCDate() - 1);
        const yestStr = yest.toISOString().slice(0, 10);
        if (stats.last_date === yestStr) {
            stats.streak = (stats.streak || 0) + 1;
        } else if (stats.last_date === today) {
            // shouldn't happen, defensive
        } else {
            stats.streak = 1;
        }
        if (stats.streak > (stats.best_streak || 0)) stats.best_streak = stats.streak;
    } else {
        stats.streak = 0;
    }
    stats.last_date = today;
    stats.history = stats.history || {};
    stats.history[today] = {
        guesses: OneShot.guesses,
        won: OneShot.state === 'won',
        secret: OneShot.secret
    };
    oneshotSaveStats(stats);
    OneShot.stats = stats;
    if (OneShot.state === 'won') triggerConfetti();

    // Award XP based on how few guesses they used
    if (State.myName) {
        const event = OneShot.state === 'won'
            ? `solved_${OneShot.guesses.length}`
            : 'failed';
        awardXP({ game: 'oneshot', event }).then(r => {
            OneShot.lastAward = r;
            oneshotShowDone();
        }).catch(() => oneshotShowDone());
    } else {
        oneshotShowDone();
    }
}

function oneshotShowDone() {
    showScreen('screen-oneshot-done');
    const stamp = $('oneshot-result-stamp');
    if (OneShot.state === 'won') {
        stamp.textContent = 'SOLVED';
        stamp.classList.remove('lost');
    } else {
        stamp.textContent = 'OUT OF GUESSES';
        stamp.classList.add('lost');
    }
    $('oneshot-answer-num').textContent = OneShot.secret != null ? OneShot.secret : '?';
    // Build share grid (Wordle-style)
    const shareEl = $('oneshot-share-grid');
    shareEl.innerHTML = '';
    const max = (OneShot.info && OneShot.info.max_guesses) || 6;
    for (let i = 0; i < max; i++) {
        const row = document.createElement('div');
        row.className = 'oneshot-share-row';
        const cell = document.createElement('div');
        const g = OneShot.guesses[i];
        if (!g) cell.className = 'oneshot-share-cell empty';
        else if (g.feedback === 'correct') cell.className = 'oneshot-share-cell right';
        else cell.className = 'oneshot-share-cell ' + g.feedback;
        row.appendChild(cell);
        shareEl.appendChild(row);
    }
    const stats = OneShot.stats || oneshotLoadStats();
    $('oneshot-done-streak').textContent = stats.streak || 0;
    $('oneshot-done-played').textContent = stats.played || 0;
    const wr = stats.played ? Math.round(100 * (stats.won || 0) / stats.played) : 0;
    $('oneshot-done-winrate').textContent = wr + '%';
    oneshotStartCountdown();
    // Show the XP/levelup banner if we awarded any
    if (OneShot.lastAward) {
        setTimeout(() => showXPBanner(OneShot.lastAward), 400);
        OneShot.lastAward = null;
    }
}

let ONESHOT_COUNTDOWN_INT = null;
function oneshotStartCountdown() {
    if (ONESHOT_COUNTDOWN_INT) clearInterval(ONESHOT_COUNTDOWN_INT);
    const update = () => {
        const now = new Date();
        const tomorrow = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
        const diff = tomorrow - now;
        const h = Math.floor(diff / 3600000);
        const m = Math.floor((diff % 3600000) / 60000);
        const s = Math.floor((diff % 60000) / 1000);
        const el = $('oneshot-countdown');
        if (el) el.textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    };
    update();
    ONESHOT_COUNTDOWN_INT = setInterval(update, 1000);
}

function oneshotBuildShareText() {
    const max = (OneShot.info && OneShot.info.max_guesses) || 6;
    const used = OneShot.guesses.length;
    const head = OneShot.state === 'won'
        ? `OneShot ${OneShot.info.date} — ${used}/${max} ✅`
        : `OneShot ${OneShot.info.date} — X/${max}`;
    const grid = OneShot.guesses.map(g =>
        g.feedback === 'correct' ? '🟩'
        : g.feedback === 'higher' ? '⬆️'
        : '⬇️'
    ).join('\n');
    return `${head}\n${grid}`;
}

function wireOneShot() {
    $('btn-oneshot-start').onclick = () => { soundClick(); oneshotBeginPlay(); };
    $('oneshot-submit').onclick = () => { soundClick(); oneshotSubmit(); };
    $('oneshot-input').onkeydown = (e) => {
        if (e.key === 'Enter') oneshotSubmit();
    };
    $('oneshot-share').onclick = () => {
        soundClick();
        const text = oneshotBuildShareText();
        try { navigator.clipboard.writeText(text); toast('Result copied'); }
        catch (e) { toast('Copy failed — your browser may not allow it'); }
    };
    $('oneshot-back-home').onclick = () => {
        if (ONESHOT_COUNTDOWN_INT) clearInterval(ONESHOT_COUNTDOWN_INT);
        showScreen('screen-home');
    };
}

// =========================================================================
// FOOTYMIND (career-path footballer guessing)
// =========================================================================

const FootyMind = {
    players: [],          // list of {name, nationality, position, path: [...]}
    idx: 0,
    score: 0,
    hintLevel: 1,         // 1, 2, 3 — how many path entries are visible
    maxHint: 3,
    difficulty: 'easy',
    answers: []           // [{expected, your_guess, correct, hints_used}]
};

function footymindShowIntro() {
    showScreen('screen-footymind-intro');
    document.querySelectorAll('#screen-footymind-intro .mode-card').forEach(c => {
        c.classList.toggle('active', c.dataset.fmmode === 'solo');
    });
    document.querySelectorAll('#screen-footymind-intro .seg-btn[data-fmdiff]').forEach(b => {
        b.classList.toggle('active', b.dataset.fmdiff === 'easy');
    });
    FootyMind.difficulty = 'easy';
    updateFootyMindDifficultyDesc();
}

function updateFootyMindDifficultyDesc() {
    const m = {
        easy:   'Easy: superstars only — Messi, Ronaldo, Neymar level.',
        medium: 'Medium: well-known players. Champions League regulars.',
        hard:   'Hard: legends and era-spanners. Some retired greats.'
    };
    $('footymind-diff-desc').textContent = m[FootyMind.difficulty] || '';
}

async function footymindStart() {
    try {
        const res = await fetch(`/api/footymind/round?difficulty=${FootyMind.difficulty}&n=10`);
        const data = await res.json();
        FootyMind.players = data.players || [];
        FootyMind.idx = 0;
        FootyMind.score = 0;
        FootyMind.answers = [];
        if (FootyMind.players.length === 0) {
            toast('No players available');
            return;
        }
        showScreen('screen-footymind-play');
        footymindRender();
    } catch (e) {
        toast('Could not load players');
    }
}

function footymindRender() {
    const p = FootyMind.players[FootyMind.idx];
    if (!p) { footymindDone(); return; }
    FootyMind.hintLevel = 1;
    FootyMind.maxHint = 3;
    $('footymind-progress').textContent = `${FootyMind.idx + 1} / ${FootyMind.players.length}`;
    $('footymind-score').textContent = FootyMind.score;
    $('footymind-hint-num').textContent = FootyMind.hintLevel;
    $('footymind-hint-max').textContent = FootyMind.maxHint;
    renderFootyPath(p);
    $('footymind-input').value = '';
    $('footymind-input').disabled = false;
    $('footymind-submit').disabled = false;
    $('footymind-feedback').textContent = '';
    setTimeout(() => { try { $('footymind-input').focus(); } catch (e) {} }, 50);
}

function renderFootyPath(p) {
    const el = $('footymind-path');
    el.innerHTML = '';
    // Always show the FULL career path immediately — that's the whole hook.
    // Hints progressively reveal extra metadata:
    //   Hint 1/3: career path only
    //   Hint 2/3: + position
    //   Hint 3/3: + nationality
    p.path.forEach(step => {
        const node = document.createElement('div');
        node.className = 'fm-path-step';
        node.innerHTML = `<div class="fm-step-years">${escapeHtml(step.years)}</div>
                          <div class="fm-step-club">${escapeHtml(step.club)}</div>`;
        el.appendChild(node);
    });

    // Hide both pills by default; reveal as hints are used.
    const posEl = $('footymind-position');
    const natEl = $('footymind-nationality');
    posEl.textContent = '';
    posEl.classList.add('empty');
    natEl.textContent = '';
    natEl.classList.add('empty');

    if (FootyMind.hintLevel >= 2) {
        posEl.textContent = p.position;
        posEl.classList.remove('empty');
    }
    if (FootyMind.hintLevel >= 3) {
        natEl.textContent = p.nationality;
        natEl.classList.remove('empty');
    }
}

function footymindNextHint() {
    const p = FootyMind.players[FootyMind.idx];
    if (!p) return;
    if (FootyMind.hintLevel >= FootyMind.maxHint) {
        toast('No more hints');
        return;
    }
    FootyMind.hintLevel++;
    $('footymind-hint-num').textContent = FootyMind.hintLevel;
    renderFootyPath(p);
    setTimeout(() => { try { $('footymind-input').focus(); } catch (e) {} }, 50);
}

async function footymindSubmitGuess() {
    const p = FootyMind.players[FootyMind.idx];
    if (!p) return;
    const guess = ($('footymind-input').value || '').trim();
    if (!guess) return;
    let resp;
    try {
        const res = await fetch('/api/footymind/check', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ expected: p.name, guess })
        });
        resp = await res.json();
    } catch (e) {
        $('footymind-feedback').textContent = 'Network error';
        return;
    }
    const correct = !!resp.correct;
    const matched = resp.matched;
    if (correct) {
        // Score depends on how few hints were used
        const hintsUsed = FootyMind.hintLevel;
        const points = Math.max(1, 4 - hintsUsed);   // 1 hint = 3pts, 2 hints = 2pts, 3 hints = 1pt
        FootyMind.score += points;
        soundCrack();
        FootyMind.answers.push({
            expected: p.name, your_guess: guess, correct: true, hints_used: hintsUsed
        });
        $('footymind-feedback').textContent = '';
        setTimeout(() => {
            FootyMind.idx++;
            if (FootyMind.idx >= FootyMind.players.length) footymindDone();
            else footymindRender();
        }, 400);
    } else if (matched && matched !== p.name) {
        // Player guessed a different real player
        $('footymind-feedback').textContent = `That's ${matched}, but not the answer here.`;
    } else {
        $('footymind-feedback').textContent = "Not a recognised player. Try a different spelling.";
    }
}

function footymindSkip() {
    const p = FootyMind.players[FootyMind.idx];
    if (!p) return;
    FootyMind.answers.push({
        expected: p.name, your_guess: '(skipped)', correct: false,
        hints_used: FootyMind.hintLevel
    });
    soundLose();
    $('footymind-feedback').textContent = `Was: ${p.name}`;
    setTimeout(() => {
        FootyMind.idx++;
        if (FootyMind.idx >= FootyMind.players.length) footymindDone();
        else footymindRender();
    }, 1400);
}

async function footymindDone() {
    showScreen('screen-footymind-done');
    const score = FootyMind.score;
    const total = FootyMind.players.length;
    const correctCount = FootyMind.answers.filter(a => a.correct).length;
    const maxPossible = total * 3;
    $('footymind-final-score').textContent = `${score} pts`;
    const pct = total > 0 ? correctCount / total : 0;
    const stamp = $('footymind-result-stamp');
    if (pct >= 0.9) stamp.textContent = 'LEGENDARY';
    else if (pct >= 0.7) stamp.textContent = 'STRONG';
    else if (pct >= 0.4) stamp.textContent = 'NOT BAD';
    else stamp.textContent = 'TOUGH ROUND';
    const list = $('footymind-answers');
    list.innerHTML = '';
    FootyMind.answers.forEach(a => {
        const row = document.createElement('div');
        row.className = 'footymind-answer-row ' + (a.correct ? 'right' : 'wrong');
        const hintNote = a.correct ? `${a.hints_used} hint${a.hints_used > 1 ? 's' : ''}` : '';
        row.innerHTML = `<div><div class="label">${escapeHtml(a.expected)}</div>
                              <div class="your">You: ${escapeHtml(a.your_guess)}</div></div>
                         <div class="muted small">${hintNote}</div>`;
        list.appendChild(row);
    });
    if (pct >= 0.7) triggerConfetti();

    // Award XP: one award per correct answer, plus a round-completion bonus
    if (State.myName) {
        const diff = FootyMind.difficulty || 'easy';
        // Award per correct (fire and forget — they all contribute to one total)
        for (let i = 0; i < correctCount; i++) {
            await awardXP({ game: 'footymind', event: `correct_${diff}` });
        }
        // Round bonus
        let bonusEvent = null;
        if (pct === 1.0) bonusEvent = 'round_perfect';
        else if (pct >= 0.7) bonusEvent = 'round_70pct';
        else if (pct >= 0.5) bonusEvent = 'round_50pct';
        if (bonusEvent) {
            const r = await awardXP({ game: 'footymind', event: bonusEvent });
            showXPBanner(r);
        }
    }
}

function wireFootyMind() {
    document.querySelectorAll('#screen-footymind-intro .mode-card[data-fmmode]').forEach(c => {
        c.onclick = () => {
            soundClick();
            const mode = c.dataset.fmmode;
            document.querySelectorAll('#screen-footymind-intro .mode-card').forEach(x =>
                x.classList.toggle('active', x === c));
            if (mode !== 'solo') {
                toast(mode === 'duel' ? '1v1 mode coming next — solo works now' : 'Group mode coming next');
                // Revert to solo
                setTimeout(() => {
                    document.querySelectorAll('#screen-footymind-intro .mode-card').forEach(x =>
                        x.classList.toggle('active', x.dataset.fmmode === 'solo'));
                }, 1500);
            }
        };
    });
    document.querySelectorAll('#screen-footymind-intro .seg-btn[data-fmdiff]').forEach(b => {
        b.onclick = () => {
            soundClick();
            FootyMind.difficulty = b.dataset.fmdiff;
            document.querySelectorAll('#screen-footymind-intro .seg-btn[data-fmdiff]').forEach(x =>
                x.classList.toggle('active', x === b));
            updateFootyMindDifficultyDesc();
        };
    });
    $('btn-footymind-start').onclick = () => { soundClick(); footymindStart(); };
    $('footymind-submit').onclick = () => footymindSubmitGuess();
    $('footymind-input').onkeydown = (e) => {
        if (e.key === 'Enter') footymindSubmitGuess();
    };
    $('footymind-hint').onclick = () => { soundClick(); footymindNextHint(); };
    $('footymind-skip').onclick = () => { soundClick(); footymindSkip(); };
    $('footymind-replay').onclick = () => { soundClick(); footymindStart(); };
    $('footymind-back-home').onclick = () => { showScreen('screen-home'); };
}

// =========================================================================
// TRIVIARUSH
// =========================================================================

const Trivia = {
    questions: [],
    idx: 0,
    score: 0,
    answers: [],
    timer: null,
    timerStart: 0,
    timerDuration: 15,
    selectedCats: ['football','geography','science','movies','music','history','pop'],
    seenIds: []   // tracked in localStorage
};

const TRIVIA_SEEN_KEY = 'gameroom_trivia_seen_v1';

function triviaLoadSeen() {
    try {
        const raw = localStorage.getItem(TRIVIA_SEEN_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return [];
}
function triviaSaveSeen(seen) {
    try { localStorage.setItem(TRIVIA_SEEN_KEY, JSON.stringify(seen)); } catch (e) {}
}

function triviaShowIntro() {
    Trivia.seenIds = triviaLoadSeen();
    showScreen('screen-trivia-intro');
    document.querySelectorAll('#screen-trivia-intro .mode-card').forEach(c => {
        c.classList.toggle('active', c.dataset.trmode === 'solo');
    });
    // All cats active by default
    document.querySelectorAll('#trivia-cats .cat-chip').forEach(c => {
        c.classList.toggle('active', Trivia.selectedCats.includes(c.dataset.cat));
    });
    updateTriviaCatsNote();
}

function updateTriviaCatsNote() {
    const active = document.querySelectorAll('#trivia-cats .cat-chip.active').length;
    const total = document.querySelectorAll('#trivia-cats .cat-chip').length;
    const note = $('trivia-cats-note');
    if (active === 0) note.textContent = 'Pick at least one category.';
    else if (active === total) note.textContent = 'All categories selected.';
    else note.textContent = `${active} of ${total} categories selected.`;
}

async function triviaStart() {
    Trivia.selectedCats = Array.from(document.querySelectorAll('#trivia-cats .cat-chip.active'))
        .map(c => c.dataset.cat);
    if (Trivia.selectedCats.length === 0) {
        toast('Pick at least one category');
        return;
    }
    const catsParam = Trivia.selectedCats.join(',');
    const excludeParam = Trivia.seenIds.length > 0
        ? '&exclude=' + encodeURIComponent(Trivia.seenIds.join('|'))
        : '';
    try {
        const res = await fetch(`/api/trivia/round?n=10&categories=${catsParam}${excludeParam}`);
        const data = await res.json();
        Trivia.questions = data.questions || [];
        if (Trivia.questions.length === 0) {
            toast('No questions available — try a different category');
            return;
        }
        // If we got fewer than 10 because the pool ran out, reset seen
        if (Trivia.questions.length < 10 && Trivia.seenIds.length > 0) {
            toast('You\'ve seen most of the pool — resetting');
            Trivia.seenIds = [];
            triviaSaveSeen([]);
        }
        Trivia.idx = 0;
        Trivia.score = 0;
        Trivia.answers = [];
        showScreen('screen-trivia-play');
        triviaRender();
    } catch (e) {
        toast('Could not load questions');
    }
}

function triviaRender() {
    const q = Trivia.questions[Trivia.idx];
    if (!q) { triviaDone(); return; }
    $('trivia-progress').textContent = `${Trivia.idx + 1} / ${Trivia.questions.length}`;
    $('trivia-score').textContent = Trivia.score;
    $('trivia-cat-label').textContent = q.cat_label || '';
    $('trivia-question').textContent = q.q || '';
    $('trivia-explain').classList.add('hidden');
    $('trivia-explain').textContent = '';
    $('trivia-next').classList.add('hidden');

    // Build options based on question type
    const optsEl = $('trivia-options');
    optsEl.innerHTML = '';
    if (q.type === 'mc') {
        q.options.forEach((opt, i) => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = opt;
            btn.onclick = () => triviaPickAnswer(i, btn);
            optsEl.appendChild(btn);
        });
    } else if (q.type === 'older') {
        ['a', 'b'].forEach(side => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = q[side];
            btn.onclick = () => triviaPickAnswer(side, btn);
            optsEl.appendChild(btn);
        });
    } else if (q.type === 'tf') {
        [['TRUE', true], ['FALSE', false]].forEach(([label, val]) => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = label;
            btn.onclick = () => triviaPickAnswer(val, btn);
            optsEl.appendChild(btn);
        });
    }
    triviaStartTimer();
}

function triviaStartTimer() {
    if (Trivia.timer) clearInterval(Trivia.timer);
    Trivia.timerStart = Date.now();
    Trivia.timerDuration = 15;
    const update = () => {
        const elapsed = (Date.now() - Trivia.timerStart) / 1000;
        const remaining = Math.max(0, Trivia.timerDuration - elapsed);
        const sec = Math.ceil(remaining);
        const el = $('trivia-timer');
        if (el) {
            el.textContent = sec;
            el.classList.toggle('urgent', sec <= 5);
        }
        if (remaining <= 0) {
            clearInterval(Trivia.timer);
            triviaTimeOut();
        }
    };
    update();
    Trivia.timer = setInterval(update, 250);
}

async function triviaPickAnswer(answer, btnEl) {
    const q = Trivia.questions[Trivia.idx];
    if (!q) return;
    if (Trivia.timer) clearInterval(Trivia.timer);
    // Disable all options
    document.querySelectorAll('#trivia-options .trivia-opt').forEach(b => {
        b.disabled = true;
    });
    if (btnEl) btnEl.classList.add('picked');

    let resp;
    try {
        const res = await fetch('/api/trivia/check', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: q.id, answer })
        });
        resp = await res.json();
    } catch (e) {
        resp = { correct: false, correct_answer: null, explain: 'Network error' };
    }

    // Highlight right/wrong
    const opts = document.querySelectorAll('#trivia-options .trivia-opt');
    if (q.type === 'mc') {
        opts[resp.correct_answer]?.classList.add('right');
        if (!resp.correct && btnEl) btnEl.classList.add('wrong');
    } else if (q.type === 'older') {
        const correctIdx = resp.correct_answer === 'a' ? 0 : 1;
        opts[correctIdx]?.classList.add('right');
        if (!resp.correct && btnEl) btnEl.classList.add('wrong');
    } else if (q.type === 'tf') {
        const correctIdx = resp.correct_answer ? 0 : 1;
        opts[correctIdx]?.classList.add('right');
        if (!resp.correct && btnEl) btnEl.classList.add('wrong');
    }

    Trivia.answers.push({
        q: q.q,
        cat: q.cat_label,
        correct: resp.correct,
        explain: resp.explain
    });
    if (resp.correct) {
        Trivia.score++;
        soundCrack();
    } else {
        soundLose();
    }
    // Show explanation
    if (resp.explain) {
        $('trivia-explain').textContent = resp.explain;
        $('trivia-explain').classList.remove('hidden');
    }
    $('trivia-next').classList.remove('hidden');
    $('trivia-next').textContent = (Trivia.idx + 1 >= Trivia.questions.length)
        ? 'See result' : 'Next question';

    // Track seen
    if (!Trivia.seenIds.includes(q.id)) {
        Trivia.seenIds.push(q.id);
        triviaSaveSeen(Trivia.seenIds);
    }
}

function triviaTimeOut() {
    const q = Trivia.questions[Trivia.idx];
    if (!q) return;
    // Treat as wrong; don't disable user-side highlight, just move on
    document.querySelectorAll('#trivia-options .trivia-opt').forEach(b => {
        b.disabled = true;
    });
    Trivia.answers.push({
        q: q.q, cat: q.cat_label, correct: false, explain: 'Time ran out'
    });
    soundLose();
    $('trivia-explain').textContent = 'Time ran out.';
    $('trivia-explain').classList.remove('hidden');
    $('trivia-next').classList.remove('hidden');
    $('trivia-next').textContent = (Trivia.idx + 1 >= Trivia.questions.length)
        ? 'See result' : 'Next question';
}

function triviaNext() {
    Trivia.idx++;
    if (Trivia.idx >= Trivia.questions.length) {
        triviaDone();
    } else {
        triviaRender();
    }
}

async function triviaDone() {
    showScreen('screen-trivia-done');
    if (Trivia.timer) clearInterval(Trivia.timer);
    const score = Trivia.score;
    const total = Trivia.questions.length;
    $('trivia-final-score').textContent = `${score} / ${total}`;
    const pct = total > 0 ? score / total : 0;
    const stamp = $('trivia-result-stamp');
    if (pct === 1) stamp.textContent = 'PERFECT';
    else if (pct >= 0.7) stamp.textContent = 'STRONG';
    else if (pct >= 0.4) stamp.textContent = 'NOT BAD';
    else stamp.textContent = 'TOUGH ROUND';
    const review = $('trivia-review');
    review.innerHTML = '';
    Trivia.answers.forEach((a, i) => {
        const row = document.createElement('div');
        row.className = 'trivia-review-row ' + (a.correct ? 'right' : 'wrong');
        row.innerHTML = `<div class="rv-q">${i + 1}. ${escapeHtml(a.q)}</div>
                         <div class="rv-meta">${escapeHtml(a.cat)} &middot; ${escapeHtml(a.explain || '')}</div>`;
        review.appendChild(row);
    });
    if (pct >= 0.7) triggerConfetti();

    // Award XP
    if (State.myName) {
        for (let i = 0; i < score; i++) {
            await awardXP({ game: 'trivia', event: 'correct' });
        }
        let bonusEvent = null;
        if (pct === 1.0) bonusEvent = 'round_perfect';
        else if (pct >= 0.7) bonusEvent = 'round_70pct';
        else if (pct >= 0.5) bonusEvent = 'round_50pct';
        if (bonusEvent) {
            const r = await awardXP({ game: 'trivia', event: bonusEvent });
            showXPBanner(r);
        }
    }
}

function wireTrivia() {
    // Mode buttons (only solo works for now)
    document.querySelectorAll('#screen-trivia-intro .mode-card[data-trmode]').forEach(c => {
        c.onclick = () => {
            soundClick();
            const mode = c.dataset.trmode;
            document.querySelectorAll('#screen-trivia-intro .mode-card').forEach(x =>
                x.classList.toggle('active', x === c));
            if (mode !== 'solo') {
                toast(mode === 'duel' ? '1v1 mode coming next session' : 'Group mode coming next session');
                setTimeout(() => {
                    document.querySelectorAll('#screen-trivia-intro .mode-card').forEach(x =>
                        x.classList.toggle('active', x.dataset.trmode === 'solo'));
                }, 1500);
            }
        };
    });
    // Cat chips
    document.querySelectorAll('#trivia-cats .cat-chip').forEach(c => {
        c.onclick = () => {
            soundClick();
            c.classList.toggle('active');
            updateTriviaCatsNote();
        };
    });
    $('btn-trivia-start').onclick = () => { soundClick(); triviaStart(); };
    $('trivia-next').onclick = () => { soundClick(); triviaNext(); };
    $('trivia-replay').onclick = () => { soundClick(); triviaStart(); };
    $('trivia-back-home').onclick = () => { showScreen('screen-home'); };
}

// =========================================================================
// GEOGRAPHY
// =========================================================================

const Geo = {
    mode: 'flags',                   // flags | capitals | landmarks | continents
    difficulty: 'mixed',
    items: [],
    idx: 0,
    score: 0,
    answers: [],
    timer: null,
    timerStart: 0,
    timerDuration: 20
};

const GEO_MODE_LABELS = {
    flags: '🏳️ Flags',
    capitals: '🏛️ Capitals',
    landmarks: '🗿 Landmarks',
    continents: '🌍 Continents'
};

function geoShowIntro() {
    showScreen('screen-geo-intro');
    document.querySelectorAll('#screen-geo-intro .geo-submode-card').forEach(c => {
        c.classList.toggle('active', c.dataset.geomode === Geo.mode);
    });
    document.querySelectorAll('#screen-geo-intro .seg-btn[data-geodiff]').forEach(b => {
        b.classList.toggle('active', b.dataset.geodiff === Geo.difficulty);
    });
}

async function geoStart() {
    try {
        const url = `/api/geo/round?mode=${Geo.mode}&difficulty=${Geo.difficulty}&n=10`;
        const res = await fetch(url);
        const data = await res.json();
        Geo.items = data.items || [];
        if (Geo.items.length === 0) {
            toast('No questions available — try a different mode');
            return;
        }
        Geo.idx = 0;
        Geo.score = 0;
        Geo.answers = [];
        Geo.timerDuration = (Geo.mode === 'flags' || Geo.mode === 'landmarks') ? 20 : 15;
        showScreen('screen-geo-play');
        geoRender();
    } catch (e) {
        toast('Could not load Geography round');
    }
}

function geoRender() {
    const item = Geo.items[Geo.idx];
    if (!item) { geoDone(); return; }
    $('geo-progress').textContent = `${Geo.idx + 1} / ${Geo.items.length}`;
    $('geo-score').textContent = Geo.score;
    $('geo-mode-label').textContent = GEO_MODE_LABELS[Geo.mode] || Geo.mode;
    $('geo-explain').classList.add('hidden');
    $('geo-explain').textContent = '';
    $('geo-next').classList.add('hidden');
    $('geo-skip').classList.remove('hidden');

    const imgWrap = $('geo-image-wrap');
    const promptEl = $('geo-prompt');
    const textBlock = $('geo-text-input-block');
    const optsEl = $('geo-options');

    // Reset all three modes' UI
    imgWrap.classList.add('hidden');
    promptEl.classList.add('hidden');
    textBlock.classList.add('hidden');
    optsEl.classList.add('hidden');
    optsEl.innerHTML = '';

    if (Geo.mode === 'flags' || Geo.mode === 'landmarks') {
        imgWrap.classList.remove('hidden');
        const icon = Geo.mode === 'flags' ? '🏳️' : '🗿';
        // Always reset the wrap to a clean img element so previous errors
        // don't linger between rounds. The fallback only shows on real error.
        imgWrap.innerHTML = '<img id="geo-image" class="geo-image" alt="">';
        const img = document.getElementById('geo-image');
        let errored = false;
        img.onerror = () => {
            if (errored) return;   // guard double-fire
            errored = true;
            imgWrap.innerHTML =
                '<div class="geo-image-fallback">' +
                    '<div class="geo-image-fallback-icon">' + icon + '</div>' +
                    '<div class="geo-image-fallback-text">Image unavailable<br>(your guess still counts)</div>' +
                '</div>';
        };
        img.src = item.image;
        textBlock.classList.remove('hidden');
        const inp = $('geo-text-input');
        inp.value = '';
        inp.disabled = false;
        const submitBtn = $('geo-text-submit');
        submitBtn.disabled = false;
        if (Geo.mode === 'flags') {
            inp.placeholder = 'Country name';
        } else {
            inp.placeholder = 'Landmark name';
        }
        setTimeout(() => { try { inp.focus(); } catch (e) {} }, 50);
    } else if (Geo.mode === 'capitals') {
        promptEl.classList.remove('hidden');
        promptEl.textContent = `What is the capital of ${item.country}?`;
        optsEl.classList.remove('hidden');
        item.options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = opt;
            btn.onclick = () => geoPickChoice(opt, btn, item.answer);
            optsEl.appendChild(btn);
        });
    } else if (Geo.mode === 'continents') {
        promptEl.classList.remove('hidden');
        promptEl.textContent = `Which continent is ${item.country} in?`;
        optsEl.classList.remove('hidden');
        item.options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = opt;
            btn.onclick = () => geoPickChoice(opt, btn, item.answer);
            optsEl.appendChild(btn);
        });
    }
    geoStartTimer();
}

function geoStartTimer() {
    if (Geo.timer) clearInterval(Geo.timer);
    Geo.timerStart = Date.now();
    const update = () => {
        const elapsed = (Date.now() - Geo.timerStart) / 1000;
        const remaining = Math.max(0, Geo.timerDuration - elapsed);
        const sec = Math.ceil(remaining);
        const el = $('geo-timer');
        if (el) {
            el.textContent = sec;
            el.classList.toggle('urgent', sec <= 5);
        }
        if (remaining <= 0) {
            clearInterval(Geo.timer);
            geoTimeOut();
        }
    };
    update();
    Geo.timer = setInterval(update, 250);
}

async function geoSubmitText() {
    const item = Geo.items[Geo.idx];
    if (!item) return;
    const guess = ($('geo-text-input').value || '').trim();
    if (!guess) return;
    const expected = item.country || item.name;
    let correct = false;
    try {
        const res = await fetch('/api/geo/check', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ expected, guess })
        });
        const data = await res.json();
        correct = !!data.correct;
    } catch (e) {}
    geoAfterAnswer(correct, expected, guess);
}

function geoPickChoice(picked, btn, correctAnswer) {
    if (Geo.timer) clearInterval(Geo.timer);
    document.querySelectorAll('#geo-options .trivia-opt').forEach(b => {
        b.disabled = true;
        if (b.textContent === correctAnswer) b.classList.add('right');
    });
    if (picked !== correctAnswer && btn) btn.classList.add('wrong');
    const correct = picked === correctAnswer;
    geoAfterAnswer(correct, correctAnswer, picked);
}

function geoAfterAnswer(correct, expected, guess) {
    const item = Geo.items[Geo.idx];
    Geo.answers.push({ expected, guess, correct, mode: Geo.mode });
    if (correct) {
        Geo.score++;
        soundCrack();
    } else {
        soundLose();
    }
    let explain = '';
    if (Geo.mode === 'flags') explain = correct ? `${expected} — yes!` : `That was ${expected}.`;
    else if (Geo.mode === 'landmarks') explain = `${item.name} — ${item.country}`;
    else if (Geo.mode === 'capitals') explain = correct ? `Yes — ${expected}.` : `The capital is ${expected}.`;
    else if (Geo.mode === 'continents') explain = correct ? `Yes — ${expected}.` : `${item.country} is in ${expected}.`;
    $('geo-explain').textContent = explain;
    $('geo-explain').classList.remove('hidden');
    $('geo-next').classList.remove('hidden');
    $('geo-next').textContent = (Geo.idx + 1 >= Geo.items.length) ? 'See result' : 'Next';
    $('geo-skip').classList.add('hidden');
    if (Geo.timer) clearInterval(Geo.timer);
    $('geo-text-input').disabled = true;
    $('geo-text-submit').disabled = true;
}

function geoTimeOut() {
    const item = Geo.items[Geo.idx];
    if (!item) return;
    const expected = item.country || item.answer || item.name;
    geoAfterAnswer(false, expected, '(time out)');
}

function geoNext() {
    Geo.idx++;
    if (Geo.idx >= Geo.items.length) { geoDone(); return; }
    geoRender();
}

async function geoDone() {
    showScreen('screen-geo-done');
    if (Geo.timer) clearInterval(Geo.timer);
    const total = Geo.items.length;
    const score = Geo.score;
    const pct = total > 0 ? score / total : 0;
    $('geo-final-score').textContent = `${score} / ${total}`;
    const stamp = $('geo-result-stamp');
    if (pct === 1) stamp.textContent = 'PERFECT';
    else if (pct >= 0.7) stamp.textContent = 'STRONG';
    else if (pct >= 0.4) stamp.textContent = 'NOT BAD';
    else stamp.textContent = 'TOUGH ROUND';
    const review = $('geo-review');
    review.innerHTML = '';
    Geo.answers.forEach((a, i) => {
        const row = document.createElement('div');
        row.className = 'trivia-review-row ' + (a.correct ? 'right' : 'wrong');
        row.innerHTML = `<div class="rv-q">${i + 1}. ${escapeHtml(a.expected)}</div>
                         <div class="rv-meta">You: ${escapeHtml(a.guess)}</div>`;
        review.appendChild(row);
    });
    if (pct >= 0.7) triggerConfetti();

    // Award XP
    if (State.myName) {
        for (let i = 0; i < score; i++) {
            await awardXP({ game: 'geo', event: 'correct' });
        }
        let bonusEvent = null;
        if (pct === 1.0) bonusEvent = 'round_perfect';
        else if (pct >= 0.7) bonusEvent = 'round_70pct';
        else if (pct >= 0.5) bonusEvent = 'round_50pct';
        if (bonusEvent) {
            const r = await awardXP({ game: 'geo', event: bonusEvent });
            showXPBanner(r);
        }
    }
}

function wireGeo() {
    document.querySelectorAll('#screen-geo-intro .geo-submode-card[data-geomode]').forEach(c => {
        c.onclick = () => {
            soundClick();
            Geo.mode = c.dataset.geomode;
            document.querySelectorAll('#screen-geo-intro .geo-submode-card').forEach(x =>
                x.classList.toggle('active', x === c));
        };
    });
    document.querySelectorAll('#screen-geo-intro .seg-btn[data-geodiff]').forEach(b => {
        b.onclick = () => {
            soundClick();
            Geo.difficulty = b.dataset.geodiff;
            document.querySelectorAll('#screen-geo-intro .seg-btn[data-geodiff]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
    $('btn-geo-start').onclick = () => { soundClick(); geoStart(); };
    $('geo-text-submit').onclick = () => geoSubmitText();
    $('geo-text-input').onkeydown = (e) => {
        if (e.key === 'Enter') geoSubmitText();
    };
    $('geo-next').onclick = () => { soundClick(); geoNext(); };
    $('geo-skip').onclick = () => {
        soundClick();
        if (Geo.timer) clearInterval(Geo.timer);
        geoTimeOut();
    };
    $('geo-replay').onclick = () => { soundClick(); geoStart(); };
    $('geo-home').onclick = () => { showScreen('screen-home'); };
}

// =========================================================================


// =========================================================================
// ONLINE PLAYERS + DIRECT CHALLENGE
// =========================================================================

const STATUS_LABEL = {
    'idle': 'Free',
    'in_solo': 'Free (in solo)',
    'in_lobby': 'In lobby',
    'in_1v1': 'Busy (1v1)',
    'in_group': 'Busy (group)'
};
const FREE_STATUSES = new Set(['idle', 'in_solo']);

function openOnlineModal() {
    $('online-modal').classList.remove('hidden');
    refreshOnlineList();
}

async function refreshOnlineList() {
    const listEl = $('online-list');
    if (!listEl) return;
    listEl.innerHTML = '<p class="muted small center" style="padding:20px;">Loading...</p>';
    try {
        const me = State.myUserId || '';
        const res = await fetch('/api/online?me=' + encodeURIComponent(me));
        const data = await res.json();
        renderOnlineList(data.users || []);
    } catch (e) {
        listEl.innerHTML = '<p class="online-empty">Could not load the online list.</p>';
    }
}

function renderOnlineList(users) {
    const listEl = $('online-list');
    if (!listEl) return;
    if (!users.length) {
        listEl.innerHTML = '<p class="online-empty">Nobody else is online right now.<br>Share the URL with a friend.</p>';
        return;
    }
    listEl.innerHTML = '';
    users.forEach(u => {
        const free = FREE_STATUSES.has(u.status);
        const initial = (u.name || '?').charAt(0).toUpperCase();
        const row = document.createElement('div');
        row.className = 'online-row';
        // Build the avatar element — image overrides color overrides default
        const avColor = u.avatar_color || '#c2e835';
        let avatarHtml;
        if (u.avatar_image) {
            avatarHtml = `<div class="online-avatar" style="background: center / cover no-repeat url('${u.avatar_image}'); color: transparent;"></div>`;
        } else {
            avatarHtml = `<div class="online-avatar" style="background: ${avColor};">${escapeHtml(initial)}</div>`;
        }
        row.innerHTML = `
            ${avatarHtml}
            <div class="online-info">
                <div class="online-name">${escapeHtml(u.name)}</div>
                <div class="online-status ${free ? 'online-status-free' : 'online-status-busy'}">
                    ${STATUS_LABEL[u.status] || u.status}
                </div>
            </div>
            <button class="online-challenge-btn" data-target="${escapeHtml(u.user_id)}" ${free ? '' : 'disabled'}>
                ${free ? 'Challenge' : 'Busy'}
            </button>`;
        listEl.appendChild(row);
    });
    listEl.querySelectorAll('.online-challenge-btn[data-target]').forEach(btn => {
        btn.onclick = () => {
            const target = btn.dataset.target;
            const nameEl = btn.parentElement.querySelector('.online-name');
            const name = nameEl ? nameEl.textContent.trim() : '';
            soundClick();
            // Close the online modal so the picker is in focus
            const om = document.getElementById('online-modal');
            if (om) om.classList.add('hidden');
            sendChallenge(target, name);
        };
    });
}

function sendChallenge(targetUserId, targetName) {
    if (!State.myName) {
        toast('Set a name first');
        return;
    }
    // Open the game-picker modal — let the user choose which game
    State._challengeTarget = { user_id: targetUserId, name: targetName || 'them' };
    State._challengeGame = 'guessduel';
    const modal = document.getElementById('challenge-game-modal');
    if (!modal) {
        // Fallback to old hardcoded behavior if modal missing
        socket.emit('challenge_send', {
            target_user_id: targetUserId,
            game: State.selectedGame || 'guessduel'
        });
        toast('Challenge sent...');
        return;
    }
    const nameEl = document.getElementById('challenge-target-name');
    if (nameEl) nameEl.textContent = targetName || 'them';
    // Reset picker UI
    document.querySelectorAll('#challenge-game-modal .challenge-game-btn').forEach(b => {
        b.classList.remove('active');
    });
    document.getElementById('btn-challenge-game-send').disabled = true;
    modal.classList.remove('hidden');
}

function wireChallengeGamePicker() {
    document.querySelectorAll('#challenge-game-modal .challenge-game-btn').forEach(btn => {
        btn.onclick = () => {
            if (btn.disabled) return;
            soundClick();
            document.querySelectorAll('#challenge-game-modal .challenge-game-btn').forEach(b =>
                b.classList.toggle('active', b === btn));
            State._challengeGame = btn.dataset.cg;
            document.getElementById('btn-challenge-game-send').disabled = false;
        };
    });
    const sendBtn = document.getElementById('btn-challenge-game-send');
    if (sendBtn) {
        sendBtn.onclick = () => {
            soundClick();
            const target = State._challengeTarget;
            const game = State._challengeGame || 'guessduel';
            if (!target) return;
            debugLog('CHALLENGE_SEND target=' + target.user_id.slice(0, 12) + ' game=' + game);
            socket.emit('challenge_send', {
                target_user_id: target.user_id,
                game: game
            });
            toast(`Challenge sent to ${target.name} — waiting...`);
            document.getElementById('challenge-game-modal').classList.add('hidden');
        };
    }
}

socket.on('challenge_sent', (data) => {
    debugLog('challenge_sent id=' + (data.challenge_id || '').slice(0, 8));
});

socket.on('challenge_error', (data) => {
    toast(data.msg || 'Challenge failed');
});

socket.on('challenge_received', (data) => {
    // Show the incoming-challenge modal with a countdown
    debugLog('CHALLENGE_RECEIVED from=' + (data.from_name || '?') + ' game=' + (data.game || '?'));
    State._incomingChallenge = data;
    const modal = $('incoming-challenge-modal');
    if (!modal) {
        debugLog('  ERROR: incoming-challenge-modal element not found in DOM');
        return;
    }
    $('incoming-challenge-title').textContent =
        `${data.from_name} wants to play!`;
    $('incoming-challenge-blurb').textContent =
        `1v1 face-off in ${(data.game || 'guessduel')}.`;
    let secs = parseInt(data.ttl, 10) || 30;
    $('incoming-challenge-secs').textContent = secs;
    modal.classList.remove('hidden');
    // Play a sound so the user notices even if the page is in background
    try { soundClick(); } catch (e) {}
    if (State._challengeTimer) clearInterval(State._challengeTimer);
    State._challengeTimer = setInterval(() => {
        secs--;
        const el = $('incoming-challenge-secs');
        if (el) el.textContent = Math.max(0, secs);
        if (secs <= 0) {
            clearInterval(State._challengeTimer);
            modal.classList.add('hidden');
            State._incomingChallenge = null;
        }
    }, 1000);
});

socket.on('challenge_expired', (data) => {
    const modal = $('incoming-challenge-modal');
    if (modal) modal.classList.add('hidden');
    if (State._challengeTimer) clearInterval(State._challengeTimer);
    if (State._incomingChallenge && State._incomingChallenge.challenge_id === data.challenge_id) {
        State._incomingChallenge = null;
    }
    toast('Challenge expired');
});

socket.on('challenge_declined', (data) => {
    toast('Challenge declined');
});

socket.on('challenge_accepted', (data) => {
    // Both players got this — join the auto-created face-off room
    debugLog('challenge_accepted code=' + data.code);
    State._incomingChallenge = null;
    if (State._challengeTimer) clearInterval(State._challengeTimer);
    const mod = $('incoming-challenge-modal');
    if (mod) mod.classList.add('hidden');
    // Set per-game mode so the lobby Start button knows what to do, AND mark
    // the room for auto-start once both players are in it.
    State.selectedGame = data.game;
    State.pickedMode = 'faceoff';
    State.selectedMode = 'faceoff';
    if (data.game === 'wordchain') State.selectedWcMode = 'faceoff';
    if (data.game === 'timeshot') TS.mode = 'faceoff';
    State._challengeAutoStartCode = data.code;     // arm auto-start
    socket.emit('join_room', { code: data.code, name: State.myName });
    toast('Challenge accepted — starting...');
});

socket.on('opponent_left', (data) => {
    const msg = (data && data.msg) || 'Opponent left — you win!';
    toast(msg);
    debugLog('opponent_left: ' + msg);
});

socket.on('forfeit_recorded', (data) => {
    // Server confirmed it recorded a loss for us. Refresh visible stats
    // so the user can SEE the loss reflected immediately on home.
    debugLog('forfeit_recorded: ' + JSON.stringify(data || {}));
    toast('Loss recorded in your stats');
    setTimeout(() => { refreshProfileUI(); }, 200);
});

socket.on('presence_update', (data) => {
    // Update the badge on the menu item AND the home-screen button.
    // Refresh list if modal is open.
    refreshHomeOnlineCount();
    const onlineModal = document.getElementById('online-modal');
    if (onlineModal && !onlineModal.classList.contains('hidden')) {
        refreshOnlineList();
    }
});

function wireChallenge() {
    const accept = $('btn-challenge-accept');
    const decline = $('btn-challenge-decline');
    const refreshBtn = $('btn-online-refresh');
    if (accept) {
        accept.onclick = () => {
            soundClick();
            const ch = State._incomingChallenge;
            if (!ch) return;
            socket.emit('challenge_accept', { challenge_id: ch.challenge_id });
            if (State._challengeTimer) clearInterval(State._challengeTimer);
        };
    }
    if (decline) {
        decline.onclick = () => {
            soundClick();
            const ch = State._incomingChallenge;
            if (ch) socket.emit('challenge_decline', { challenge_id: ch.challenge_id });
            $('incoming-challenge-modal').classList.add('hidden');
            if (State._challengeTimer) clearInterval(State._challengeTimer);
            State._incomingChallenge = null;
        };
    }
    if (refreshBtn) {
        refreshBtn.onclick = () => { soundClick(); refreshOnlineList(); };
    }
}

// =========================================================================
// HOW TO PLAY
// =========================================================================

const HOWTO_CONTENT = {
    guessduel: `
        <h2>GuessDuel</h2>
        <p>Crack your opponent's secret number first.</p>
        <h3>Solo</h3>
        <p>Pick a difficulty. You and the computer each pick a secret in the chosen range. Take turns guessing; the system says higher or lower. First to crack the other's number wins.</p>
        <h3>1v1 Face-off</h3>
        <p>Create a face-off, send the link. Coin toss decides who sets the rules (range, difficulty). Same gameplay, vs a human. Single or Best-of-3/5/7.</p>
        <h3>Friend group</h3>
        <p>Four group variants: Chain (slowest eliminated), Pick-your-target, Bracket (4 or 8), King of the Hill.</p>`,
    wordchain: `
        <h2>WordChain</h2>
        <p>Each round announces a letter and length. Type a real English word starting with that letter, exactly that length. Words must be unique per round.</p>
        <h3>Difficulty</h3>
        <ul><li><b>Easy</b>: round 1 starts at 3 letters, common letters only.</li>
            <li><b>Medium</b>: round 1 starts at 4 letters.</li>
            <li><b>Hard</b>: starts at 5 letters, any letter.</li></ul>
        <h3>1v1 / Group</h3>
        <p>In 1v1, each player gets a different letter each round (coming soon). Length grows every round. Last to play correctly survives.</p>`,
    oneshot: `
        <h2>OneShot — daily puzzle</h2>
        <p>One target between 1 and 100. Same number for everyone today. Six guesses. Wordle-style hints: warmer / colder.</p>
        <p>Streak breaks if you miss a day or fail.</p>`,
    footymind: `
        <h2>FootyMind</h2>
        <p>Guess the footballer from their career path.</p>
        <h3>Hints</h3>
        <ul><li>Hint 1: career path only</li>
            <li>Hint 2: + position</li>
            <li>Hint 3: + nationality</li></ul>
        <p>Type names loosely — "messi", "leo", "cr7" all work. Skip uses a guess.</p>`,
    trivia: `
        <h2>TriviaRush</h2>
        <p>10 mixed questions per round. Three formats:</p>
        <ul><li><b>Multiple choice</b>: pick one</li>
            <li><b>Which is older</b>: two things, pick the earlier one</li>
            <li><b>True or False</b></li></ul>
        <p>Timer per question. Speed bonus on multi-choice. Categories: football, geography, science, movies, music, history, pop culture.</p>`,
    geo: `
        <h2>Geography</h2>
        <p>Four sub-modes:</p>
        <ul><li><b>Flags</b>: see a flag, type the country (217 flags incl. Legend tier)</li>
            <li><b>Capitals</b>: country → pick capital (multiple choice)</li>
            <li><b>Landmarks</b>: see an image, name what you see</li>
            <li><b>Continents</b>: country → pick continent</li></ul>
        <p><b>Legend tier</b>: historical flags, empires, microstates, unrecognised states.</p>`
};

// =========================================================================
// EDIT PROFILE — change display name + avatar color, view unique ID
// =========================================================================

const AVATAR_COLORS = ['#c2e835', '#ff6b6b', '#ffd166', '#4cc9f0',
                       '#a78bfa', '#06d6a0', '#f78ba0', '#a3a3a3'];

function getAvatarColor() {
    try {
        const c = localStorage.getItem('gameroom_avatar_color');
        if (c && AVATAR_COLORS.includes(c)) return c;
    } catch (e) {}
    return AVATAR_COLORS[0];
}
function setAvatarColor(c) {
    if (!AVATAR_COLORS.includes(c)) return;
    try { localStorage.setItem('gameroom_avatar_color', c); } catch (e) {}
}

function getAvatarImage() {
    try { return localStorage.getItem('gameroom_avatar_image') || null; } catch (e) { return null; }
}

function resizeImageToDataUrl(file, maxW, maxH, quality) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onerror = () => resolve(null);
        reader.onload = () => {
            const img = new Image();
            img.onerror = () => resolve(null);
            img.onload = () => {
                // Square-crop center, then resize to maxW x maxH
                const side = Math.min(img.width, img.height);
                const sx = (img.width - side) / 2;
                const sy = (img.height - side) / 2;
                const canvas = document.createElement('canvas');
                canvas.width = maxW; canvas.height = maxH;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, sx, sy, side, side, 0, 0, maxW, maxH);
                try {
                    resolve(canvas.toDataURL('image/jpeg', quality));
                } catch (e) { resolve(null); }
            };
            img.src = reader.result;
        };
        reader.readAsDataURL(file);
    });
}

function applyAvatarToEl(el, name, color, imageData) {
    if (!el) return;
    if (imageData) {
        el.style.background = `center / cover no-repeat url('${imageData}')`;
        el.textContent = '';
    } else {
        el.style.background = color || getAvatarColor();
        el.textContent = (name || '?').charAt(0).toUpperCase();
    }
}

function openEditProfileModal() {
    const modal = document.getElementById('edit-profile-modal');
    if (!modal) return;
    const preview = document.getElementById('edit-profile-avatar-preview');
    const nameInp = document.getElementById('edit-profile-name');
    const idEl = document.getElementById('edit-profile-id');
    const err = document.getElementById('edit-profile-error');
    const currentColor = getAvatarColor();
    const currentImage = getAvatarImage();
    State._pendingAvatarImage = undefined;   // not changed yet
    applyAvatarToEl(preview, State.myName, currentColor, currentImage);
    if (nameInp) nameInp.value = State.myName || '';
    if (idEl) idEl.textContent = State.myUserId || '(none)';
    if (err) { err.style.display = 'none'; err.textContent = ''; }
    document.querySelectorAll('#edit-profile-modal .color-swatch').forEach(b => {
        b.classList.toggle('active', b.dataset.color === currentColor);
    });
    const removeBtn = document.getElementById('btn-remove-avatar');
    if (removeBtn) removeBtn.style.display = currentImage ? '' : 'none';
    modal.classList.remove('hidden');
}

function wireEditProfile() {
    document.querySelectorAll('#edit-profile-modal .color-swatch').forEach(b => {
        b.onclick = () => {
            soundClick();
            document.querySelectorAll('#edit-profile-modal .color-swatch').forEach(x =>
                x.classList.toggle('active', x === b));
            // Picking a color clears any picture override (color wins)
            State._pendingAvatarImage = '';   // signals server to remove
            const preview = document.getElementById('edit-profile-avatar-preview');
            applyAvatarToEl(preview, document.getElementById('edit-profile-name').value, b.dataset.color, null);
            const removeBtn = document.getElementById('btn-remove-avatar');
            if (removeBtn) removeBtn.style.display = 'none';
        };
    });
    const nameInp = document.getElementById('edit-profile-name');
    if (nameInp) {
        nameInp.oninput = () => {
            const v = nameInp.value || '';
            const preview = document.getElementById('edit-profile-avatar-preview');
            const activeC = document.querySelector('#edit-profile-modal .color-swatch.active');
            const color = activeC ? activeC.dataset.color : getAvatarColor();
            const img = (State._pendingAvatarImage === undefined)
                ? getAvatarImage() : State._pendingAvatarImage;
            applyAvatarToEl(preview, v, color, img || null);
        };
    }
    const uploadBtn = document.getElementById('btn-upload-avatar');
    const fileInp = document.getElementById('edit-profile-image-input');
    if (uploadBtn && fileInp) {
        uploadBtn.onclick = () => { soundClick(); fileInp.click(); };
        fileInp.onchange = async () => {
            const f = fileInp.files && fileInp.files[0];
            if (!f) return;
            if (!f.type.startsWith('image/')) {
                toast('Please pick an image'); return;
            }
            if (f.size > 5 * 1024 * 1024) {
                toast('Image too large (5MB max)'); return;
            }
            const dataUrl = await resizeImageToDataUrl(f, 128, 128, 0.85);
            if (!dataUrl) { toast('Could not read image'); return; }
            State._pendingAvatarImage = dataUrl;
            const preview = document.getElementById('edit-profile-avatar-preview');
            applyAvatarToEl(preview, document.getElementById('edit-profile-name').value, null, dataUrl);
            const removeBtn = document.getElementById('btn-remove-avatar');
            if (removeBtn) removeBtn.style.display = '';
            fileInp.value = '';   // allow re-pick of same file
        };
    }
    const removeBtn = document.getElementById('btn-remove-avatar');
    if (removeBtn) {
        removeBtn.onclick = () => {
            soundClick();
            State._pendingAvatarImage = '';
            const preview = document.getElementById('edit-profile-avatar-preview');
            const activeC = document.querySelector('#edit-profile-modal .color-swatch.active');
            const color = activeC ? activeC.dataset.color : getAvatarColor();
            applyAvatarToEl(preview, document.getElementById('edit-profile-name').value, color, null);
            removeBtn.style.display = 'none';
        };
    }
    const copyBtn = document.getElementById('btn-copy-profile-id');
    if (copyBtn) {
        copyBtn.onclick = () => {
            soundClick();
            const uid = State.myUserId || '';
            if (!uid) return;
            try { navigator.clipboard.writeText(uid); toast('Your ID is copied'); }
            catch (e) { toast(uid); }
        };
    }
    const cancelBtn = document.getElementById('btn-edit-profile-cancel');
    if (cancelBtn) cancelBtn.onclick = () => {
        soundClick();
        delete State._pendingAvatarImage;
        document.getElementById('edit-profile-modal').classList.add('hidden');
    };
    const saveBtn = document.getElementById('btn-edit-profile-save');
    if (saveBtn) {
        saveBtn.onclick = async () => {
            soundClick();
            const nameInp2 = document.getElementById('edit-profile-name');
            const err = document.getElementById('edit-profile-error');
            const newName = (nameInp2.value || '').trim().slice(0, 20);
            const chosenSwatch = document.querySelector('#edit-profile-modal .color-swatch.active');
            const chosenColor = chosenSwatch ? chosenSwatch.dataset.color : getAvatarColor();
            if (!newName) {
                if (err) { err.textContent = 'Name cannot be empty'; err.style.display = ''; }
                return;
            }
            // Build payload (avatar_image is optional; only sent if changed)
            const payload = {
                user_id: State.myUserId,
                new_name: newName,
                avatar_color: chosenColor
            };
            if (State._pendingAvatarImage !== undefined) {
                payload.avatar_image = State._pendingAvatarImage;  // may be '' to clear
            }
            try {
                const res = await fetch('/api/profile/rename', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (!data.ok) {
                    if (err) { err.textContent = data.msg || 'Save failed'; err.style.display = ''; }
                    return;
                }
                State.myName = newName;
                try { localStorage.setItem('gameroom_name', newName); } catch (e) {}
                setAvatarColor(chosenColor);
                if (State._pendingAvatarImage !== undefined) {
                    try {
                        if (State._pendingAvatarImage)
                            localStorage.setItem('gameroom_avatar_image', State._pendingAvatarImage);
                        else
                            localStorage.removeItem('gameroom_avatar_image');
                    } catch (e) {}
                    delete State._pendingAvatarImage;
                }
                socket.emit('hello', {user_id: State.myUserId, name: newName});
                document.getElementById('edit-profile-modal').classList.add('hidden');
                refreshProfileUI();
                toast('Profile saved');
            } catch (e) {
                if (err) { err.textContent = 'Could not reach the server'; err.style.display = ''; }
            }
        };
    }
}

function openHowtoModal(initialGame) {
    const modal = $('howto-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    showHowtoTab(initialGame || 'guessduel');
}

function showHowtoTab(game) {
    document.querySelectorAll('#howto-modal .howto-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.howto === game);
    });
    const content = $('howto-content');
    if (content) content.innerHTML = HOWTO_CONTENT[game] || '<p class="muted">Coming soon.</p>';
}

function wireHowto() {
    document.querySelectorAll('#howto-modal .howto-tab').forEach(b => {
        b.onclick = () => { soundClick(); showHowtoTab(b.dataset.howto); };
    });
}

// =========================================================================

// =========================================================================
// GEOGRAPHY MULTIPLAYER (client)
// =========================================================================

const GeoMP = {
    selectedMode: 'flags',      // sub-mode: flags | capitals | landmarks | continents
    selectedRounds: 5,
    _timerInterval: null,
    _submitted: false,
};

function geoMpResetForRound() {
    GeoMP._submitted = false;
    if (GeoMP._timerInterval) {
        clearInterval(GeoMP._timerInterval);
        GeoMP._timerInterval = null;
    }
}

function renderGeoMpScoreboard(s) {
    const geo = s.geo || {};
    const scores = geo.scores || {};
    const el = document.getElementById('geo-mp-scoreboard');
    if (!el) return;
    const rows = (s.players || []).filter(p => !p.is_bot).map(p => {
        const sc = scores[p.sid] || 0;
        const isMe = p.sid === State.mySid;
        return `<div class="geo-mp-score-row${isMe ? ' self' : ''}">
            <span class="geo-mp-score-name">${escapeHtml(p.name)}${isMe ? ' (you)' : ''}</span>
            <span class="geo-mp-score-val">${sc}</span>
        </div>`;
    });
    el.innerHTML = rows.join('');
}

function renderGeoMpRound(s) {
    showScreen('screen-geo-mp-round');
    updateHeader(s);
    const geo = s.geo || {};
    const item = geo.current_item || {};
    document.getElementById('geo-mp-round-num').textContent = geo.round_number || 1;
    document.getElementById('geo-mp-round-total').textContent = geo.total_rounds || 5;
    renderGeoMpScoreboard(s);

    // Reset UI for new round (unless we're just re-rendering same round)
    if (State._geoMpCurRound !== geo.round_number) {
        State._geoMpCurRound = geo.round_number;
        geoMpResetForRound();
        // Start countdown timer
        if (geo.round_deadline) {
            const updateTimer = () => {
                const remain = Math.max(0, Math.ceil(geo.round_deadline - (Date.now() / 1000)));
                const el = document.getElementById('geo-mp-timer');
                if (el) {
                    el.textContent = remain + 's';
                    el.style.color = remain <= 5 ? '#b04040' : '';
                }
                if (remain <= 0 && GeoMP._timerInterval) {
                    clearInterval(GeoMP._timerInterval);
                    GeoMP._timerInterval = null;
                }
            };
            updateTimer();
            if (GeoMP._timerInterval) clearInterval(GeoMP._timerInterval);
            GeoMP._timerInterval = setInterval(updateTimer, 500);
        }
    }

    // Already submitted? Show waiting message instead of input
    const submittedFor = (geo.round_answers || {})[State.mySid];
    if (submittedFor) GeoMP._submitted = true;

    const imgWrap = document.getElementById('geo-mp-image-wrap');
    const prompt = document.getElementById('geo-mp-prompt');
    const optsWrap = document.getElementById('geo-mp-options-wrap');
    const textWrap = document.getElementById('geo-mp-text-wrap');
    const waiting = document.getElementById('geo-mp-waiting');

    // Image (flags + landmarks) or text prompt (capitals + continents)
    if (geo.mode === 'flags' || geo.mode === 'landmarks') {
        imgWrap.classList.remove('hidden');
        const icon = geo.mode === 'flags' ? '🏳️' : '🗿';
        imgWrap.innerHTML = '<img id="geo-mp-image" class="geo-image" alt="">';
        const img = document.getElementById('geo-mp-image');
        let errored = false;
        img.onerror = () => {
            if (errored) return; errored = true;
            imgWrap.innerHTML =
                '<div class="geo-image-fallback">' +
                    '<div class="geo-image-fallback-icon">' + icon + '</div>' +
                    '<div class="geo-image-fallback-text">Image unavailable<br>(your answer still counts)</div>' +
                '</div>';
        };
        img.src = item.image || '';
        prompt.textContent = geo.mode === 'flags' ? 'Which country?' : 'Which landmark?';
        prompt.classList.remove('hidden');
        optsWrap.classList.add('hidden');
        optsWrap.innerHTML = '';
        textWrap.classList.remove('hidden');
        const inp = document.getElementById('geo-mp-text-input');
        if (!GeoMP._submitted) {
            inp.value = ''; inp.disabled = false;
            document.getElementById('geo-mp-text-submit').disabled = false;
            setTimeout(() => { try { inp.focus(); } catch (e) {} }, 60);
        } else {
            inp.disabled = true;
            document.getElementById('geo-mp-text-submit').disabled = true;
        }
    } else {
        // Multiple choice (capitals + continents)
        imgWrap.classList.add('hidden');
        textWrap.classList.add('hidden');
        prompt.classList.remove('hidden');
        prompt.textContent = geo.mode === 'capitals'
            ? `What is the capital of ${item.country || '?'}?`
            : `Which continent is ${item.country || '?'} in?`;
        optsWrap.classList.remove('hidden');
        optsWrap.innerHTML = '';
        (item.options || []).forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'trivia-opt';
            btn.textContent = opt;
            btn.disabled = GeoMP._submitted;
            btn.onclick = () => {
                if (GeoMP._submitted) return;
                soundClick();
                geoMpSubmitAnswer(opt);
                // Lock all option buttons
                Array.from(optsWrap.children).forEach(b => b.disabled = true);
                btn.classList.add('picked');
            };
            optsWrap.appendChild(btn);
        });
    }
    waiting.style.display = GeoMP._submitted ? '' : 'none';
}

function renderGeoMpRoundEnd(s) {
    showScreen('screen-geo-mp-round-end');
    updateHeader(s);
    const geo = s.geo || {};
    const item = geo.current_item || {};
    document.getElementById('geo-mp-re-round').textContent = geo.round_number || 1;
    const correctAnswer = item.name || item.country || item.answer || '—';
    document.getElementById('geo-mp-re-answer').textContent = correctAnswer;

    // Show each player's answer + score change
    const listEl = document.getElementById('geo-mp-results-list');
    listEl.innerHTML = '';
    const answers = geo.round_answers || {};
    (s.players || []).filter(p => !p.is_bot).forEach(p => {
        const ans = answers[p.sid];
        const row = document.createElement('div');
        row.className = 'geo-mp-result-row' + (p.sid === State.mySid ? ' self' : '');
        if (ans) {
            const verdict = ans.correct
                ? `<span class="result-correct">✓ correct +${ans.score_delta}</span>`
                : `<span class="result-wrong">✗ wrong</span>`;
            row.innerHTML = `<span class="result-name">${escapeHtml(p.name)}${p.sid === State.mySid ? ' (you)' : ''}</span>
                             <span class="result-answer">${escapeHtml(ans.answer || '—')}</span>
                             ${verdict}
                             <span class="result-time">${ans.time}s</span>`;
        } else {
            row.innerHTML = `<span class="result-name">${escapeHtml(p.name)}${p.sid === State.mySid ? ' (you)' : ''}</span>
                             <span class="result-answer muted">no answer</span>
                             <span class="result-wrong">✗</span>
                             <span class="result-time">—</span>`;
        }
        listEl.appendChild(row);
    });
}

function renderGeoMpGameOver(s) {
    showScreen('screen-geo-mp-game-over');
    const geo = s.geo || {};
    const ranking = geo.final_ranking || [];
    const winners = geo.winners || [];
    geoMpResetForRound();

    const stamp = document.getElementById('geo-mp-go-stamp');
    const winnerEl = document.getElementById('geo-mp-go-winner');
    const iWon = winners.includes(State.mySid);
    if (iWon) {
        stamp.textContent = 'YOU WIN!';
        winnerEl.textContent = '🏆 +150 XP / +30 coins';
    } else if (winners.length > 1) {
        stamp.textContent = 'TIE';
        const names = winners.map(w => {
            const r = ranking.find(x => x.sid === w);
            return r ? r.name : '?';
        });
        winnerEl.textContent = names.join(' & ') + ' tied!';
    } else if (winners.length === 1) {
        const r = ranking.find(x => x.sid === winners[0]);
        stamp.textContent = 'GAME OVER';
        winnerEl.textContent = (r ? r.name : 'Someone') + ' wins!';
    } else {
        stamp.textContent = 'GAME OVER';
        winnerEl.textContent = 'No winner';
    }

    const list = document.getElementById('geo-mp-final-ranking');
    list.innerHTML = '';
    ranking.forEach((r, i) => {
        const row = document.createElement('div');
        row.className = 'geo-mp-rank-row' + (r.sid === State.mySid ? ' self' : '');
        row.innerHTML = `<span class="rank-pos">#${i + 1}</span>
                         <span class="rank-name">${escapeHtml(r.name)}${r.sid === State.mySid ? ' (you)' : ''}</span>
                         <span class="rank-score">${r.score}</span>`;
        list.appendChild(row);
    });

    // Wire replay/home buttons
    const replay = document.getElementById('geo-mp-replay');
    if (replay) replay.onclick = () => {
        soundClick();
        socket.emit('rematch');
    };
    const home = document.getElementById('geo-mp-home');
    if (home) home.onclick = () => {
        soundClick();
        leaveCurrentRoomIfAny();
        refreshProfileUI();
        showScreen('screen-home');
    };

    // Refresh profile (XP/coins/wins should reflect on home)
    setTimeout(() => { refreshProfileUI(); }, 400);
}

function geoMpSubmitAnswer(answer) {
    if (GeoMP._submitted) return;
    GeoMP._submitted = true;
    socket.emit('geo_submit_answer', { answer: answer });
    // Show waiting message
    const waiting = document.getElementById('geo-mp-waiting');
    if (waiting) waiting.style.display = '';
}

function wireGeoMp() {
    const inp = document.getElementById('geo-mp-text-input');
    const sub = document.getElementById('geo-mp-text-submit');
    if (sub) {
        sub.onclick = () => {
            if (GeoMP._submitted) return;
            const v = (inp.value || '').trim();
            if (!v) return;
            soundClick();
            geoMpSubmitAnswer(v);
            inp.disabled = true;
            sub.disabled = true;
        };
    }
    if (inp) {
        inp.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !GeoMP._submitted) {
                e.preventDefault();
                sub.click();
            }
        });
    }
    // Lobby sub-mode picker
    document.querySelectorAll('#lobby-geography-card [data-geomode]').forEach(b => {
        b.onclick = () => {
            soundClick();
            GeoMP.selectedMode = b.dataset.geomode;
            document.querySelectorAll('#lobby-geography-card [data-geomode]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
    document.querySelectorAll('#lobby-geography-card [data-georounds]').forEach(b => {
        b.onclick = () => {
            soundClick();
            GeoMP.selectedRounds = parseInt(b.dataset.georounds, 10) || 5;
            document.querySelectorAll('#lobby-geography-card [data-georounds]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
}


// =========================================================================
// TIMESHOT — guess-the-time game (client)
// =========================================================================

const TS = {
    mode: 'solo',       // solo | faceoff | group
    difficulty: 'medium',
    firstTo: 3,
    armed: false,       // tapped start, waiting for stop
    startTs: 0,         // performance.now() at start tap
    submitted: false    // already submitted this round
};

function tsShowIntro(mode) {
    TS.mode = mode || 'solo';
    showScreen('screen-ts-intro');
    // Reset intro UI controls to defaults
    document.querySelectorAll('#screen-ts-intro [data-tsdiff]').forEach(x =>
        x.classList.toggle('active', x.dataset.tsdiff === TS.difficulty));
    document.querySelectorAll('#screen-ts-intro [data-tsfirstto]').forEach(x =>
        x.classList.toggle('active', parseInt(x.dataset.tsfirstto, 10) === TS.firstTo));
}

function wireTimeShot() {
    /* Wires every TimeShot button: intro pickers, the big TAP, and the
       game-over replay/home buttons. Called once at boot so the buttons
       work whether the user arrived via mode-pick OR a challenge accept
       (which skips the intro screen entirely). */
    document.querySelectorAll('#screen-ts-intro [data-tsdiff]').forEach(b => {
        b.onclick = () => {
            soundClick();
            TS.difficulty = b.dataset.tsdiff;
            document.querySelectorAll('#screen-ts-intro [data-tsdiff]').forEach(x =>
                x.classList.toggle('active', x === b));
            const desc = $('ts-diff-desc');
            if (desc) desc.textContent =
                TS.difficulty === 'easy' ? 'Easy: 2-6 seconds, half-second targets.' :
                TS.difficulty === 'hard' ? 'Hard: 1-12 seconds, two decimals (5.73, 8.04).' :
                'Medium: 2-8 seconds, 1 decimal.';
        };
    });
    document.querySelectorAll('#screen-ts-intro [data-tsfirstto]').forEach(b => {
        b.onclick = () => {
            soundClick();
            TS.firstTo = parseInt(b.dataset.tsfirstto, 10) || 3;
            document.querySelectorAll('#screen-ts-intro [data-tsfirstto]').forEach(x =>
                x.classList.toggle('active', x === b));
        };
    });
    const startBtn = $('ts-start-game');
    if (startBtn) {
        startBtn.onclick = () => {
            soundClick();
            const hint = (TS.mode === 'solo') ? 'solo'
                       : (TS.mode === 'faceoff') ? 'faceoff' : 'group';
            State.pickedMode = TS.mode;
            socket.emit('create_room', { game_type: 'timeshot', mode_hint: hint });
            State._pendingTsStart = true;
        };
    }
    const replay = $('ts-replay');
    if (replay) replay.onclick = () => {
        soundClick();
        leaveCurrentRoomIfAny();
        tsShowIntro(TS.mode);
    };
    const home = $('ts-home');
    if (home) home.onclick = () => {
        soundClick();
        leaveCurrentRoomIfAny();
        refreshProfileUI();
        showScreen('screen-home');
    };

    // The big tap button (start hidden timer / stop it)
    const tap = $('ts-tap-btn');
    if (tap) {
        tap.onclick = () => { tsHandleTap(); };
    }
}

function tsAutoStartIfNeeded(snapshot) {
    if (snapshot.game_type !== 'timeshot') return false;
    if (snapshot.phase !== 'lobby') return false;
    if (!State._pendingTsStart) return false;
    const humans = (snapshot.players || []).filter(p => !p.is_bot);
    if (TS.mode === 'solo' || humans.length >= 2 || TS.mode === 'group') {
        State._pendingTsStart = false;
        socket.emit('start_game', {
            mode: TS.mode,
            ts_difficulty: TS.difficulty,
            first_to: TS.firstTo
        });
        return true;
    }
    return false;
}

function tsHandleTap() {
    const btn = $('ts-tap-btn');
    if (!btn) return;
    if (TS.submitted) return;
    if (!TS.armed) {
        TS.startTs = performance.now();
        TS.armed = true;
        btn.classList.add('armed');
        const lbl = $('ts-tap-label');
        if (lbl) lbl.textContent = 'TAP TO STOP';
        soundClick();
        hapticTap();
        return;
    }
    const elapsedMs = performance.now() - TS.startTs;
    TS.armed = false;
    TS.submitted = true;
    btn.classList.remove('armed');
    btn.classList.add('done');
    const lbl = $('ts-tap-label');
    if (lbl) lbl.textContent = 'STOPPED';
    soundClick();
    hapticTap();
    socket.emit('ts_stop_timer', { elapsed_ms: elapsedMs });
    const waiting = $('ts-waiting-msg');
    if (waiting) waiting.classList.remove('hidden');
}

function renderTsRound(s) {
    showScreen('screen-ts-round');
    updateHeader(s);
    const ts = s.timeshot || {};
    $('ts-round-num').textContent = ts.round_number || 1;
    $('ts-target-value').textContent = (ts.target || 0).toFixed(2) + 's';
    $('ts-first-to').textContent = ts.first_to || 3;

    // Score row: my wins vs best opponent wins
    const me = State.mySid;
    const scores = ts.round_scores || {};
    const myScore = scores[me] || 0;
    let oppBest = 0;
    Object.entries(scores).forEach(([sid, v]) => { if (sid !== me && v > oppBest) oppBest = v; });
    $('ts-score-left').textContent = myScore;
    $('ts-score-right').textContent = oppBest;

    // Reset tap button for new round
    TS.armed = false;
    TS.submitted = (ts.attempts || {})[me] !== undefined;
    const btn = $('ts-tap-btn');
    const lbl = $('ts-tap-label');
    const waiting = $('ts-waiting-msg');
    if (btn) { btn.classList.remove('armed'); btn.classList.remove('done'); }
    if (TS.submitted) {
        if (btn) btn.classList.add('done');
        if (lbl) lbl.textContent = 'STOPPED';
        if (waiting) waiting.classList.remove('hidden');
    } else {
        if (lbl) lbl.textContent = 'TAP TO START';
        if (waiting) waiting.classList.add('hidden');
    }
}

function renderTsRoundEnd(s) {
    showScreen('screen-ts-round-end');
    const ts = s.timeshot || {};
    const res = ts.last_results || {};
    $('ts-re-round').textContent = res.round_number || 1;
    $('ts-re-target').textContent = (res.target || 0).toFixed(2) + 's';
    const list = $('ts-results-list');
    if (list) {
        list.innerHTML = '';
        (res.ranked || []).forEach((r, idx) => {
            const isWinner = (idx === 0);
            const isMe = (r.sid === State.mySid);
            const row = document.createElement('div');
            row.className = 'ts-result-row' + (isWinner ? ' winner' : '');
            row.innerHTML = `
                <div class="ts-result-rank">${idx + 1}</div>
                <div class="ts-result-name">${escapeHtml(r.name)}${isMe ? ' (you)' : ''}${r.is_bot ? ' 🤖' : ''}</div>
                <div>
                    <div class="ts-result-elapsed">${(r.elapsed).toFixed(2)}s</div>
                    <div class="ts-result-error">off by ${(r.error).toFixed(2)}s</div>
                </div>`;
            list.appendChild(row);
        });
    }
}

function renderTsGameOver(s) {
    showScreen('screen-ts-game-over');
    const ts = s.timeshot || {};
    const winnerName = ts.winner_name || '—';
    const isMe = (ts.winner_sid === State.mySid);
    $('ts-go-stamp').textContent = isMe ? 'YOU WIN' : 'GAME OVER';
    $('ts-go-winner').textContent = isMe ? 'You won!' : `${winnerName} wins`;
    const list = $('ts-final-ranking');
    if (list) {
        list.innerHTML = '';
        (ts.final_ranking || []).forEach((r, idx) => {
            const isW = (idx === 0);
            const row = document.createElement('div');
            row.className = 'ts-result-row' + (isW ? ' winner' : '');
            row.innerHTML = `
                <div class="ts-result-rank">${idx + 1}</div>
                <div class="ts-result-name">${escapeHtml(r.name)}${r.is_bot ? ' 🤖' : ''}</div>
                <div class="ts-result-elapsed">${r.rounds_won} ${r.rounds_won === 1 ? 'round' : 'rounds'}</div>`;
            list.appendChild(row);
        });
    }
}

// =========================================================================

function boot() {
    loadTheme();
    loadSoundPrefs();
    debugLogInit();   // do this first so subsequent boot events get logged
    debugLog('boot start');

    // 5 quick taps on the logo toggles the debug log (for mobile diagnosis)
    let logoTaps = 0;
    let logoTapTimer = null;
    const logoEl = document.getElementById('logo-tap');
    if (logoEl) {
        logoEl.addEventListener('click', () => {
            logoTaps++;
            if (logoTapTimer) clearTimeout(logoTapTimer);
            logoTapTimer = setTimeout(() => { logoTaps = 0; }, 2000);
            if (logoTaps >= 5) {
                logoTaps = 0;
                debugLogToggle();
            }
        });
    }

    wireLanding();
    wireHome();
    wireGuestName();
    wireInviteModal();
    wireChallenge();
    wireChallengeGamePicker();
    wireHowto();
    wireTimeShot();
    wireEditProfile();
    wireGeoMp();
    wireActionChooser();
    wireJoinCode();
    wireLobby();
    wireSetup();
    wireSecrets();
    wirePickTarget();
    wirePlaying();
    wireGameOver();
    wireMenu();
    wireSettings();
    wirePause();
    wireWordChain();
    wireOneShot();
    wireFootyMind();
    wireTrivia();
    wireGeo();
    wireModePicker();   // wire LAST so handlers can't be clobbered by lobby's selectors

    // Establish a stable per-browser identity. This survives Socket.IO
    // disconnects (which generate new SIDs) and is the basis for the
    // future direct-challenge feature.
    try {
        let uid = localStorage.getItem('gameroom_uid');
        if (!uid) {
            uid = 'u_' + Math.random().toString(36).slice(2, 10)
                       + Math.random().toString(36).slice(2, 10);
            localStorage.setItem('gameroom_uid', uid);
        }
        State.myUserId = uid;
    } catch (e) {
        State.myUserId = 'u_anon_' + Math.random().toString(36).slice(2, 10);
    }

    // Restore saved name from localStorage (set in wireGuestName)
    try {
        const savedName = localStorage.getItem('gameroom_name');
        if (savedName && !State.myName) {
            State.myName = savedName;
            const input = $('input-name');
            if (input) input.value = savedName;
        }
    } catch (e) {}

    refreshProfileUI();

    // Try to restore a previous session first
    let restored = false;
    try {
        const raw = localStorage.getItem('gameroom_session_v3');
        if (raw) {
            const sess = JSON.parse(raw);
            // Stale sessions older than 30 min are ignored
            const ageMs = Date.now() - (sess.at || 0);
            if (sess.code && sess.name && ageMs < 30 * 60 * 1000) {
                State.myName = sess.name;
                // Wait for socket connect, then rejoin
                const tryRejoin = () => {
                    socket.emit('join_room', { code: sess.code, name: sess.name });
                };
                if (socket.connected) tryRejoin();
                else socket.once('connect', tryRejoin);
                restored = true;
                // Show a placeholder screen while we reconnect
                showScreen('screen-home');
                toast('Rejoining your room...');
            } else {
                localStorage.removeItem('gameroom_session_v3');
            }
        }
    } catch (e) { /* localStorage unavailable */ }

    if (restored) return;

    const presetCode = getInitialRoomCode();
    if (presetCode) {
        // Direct link visit (/r/CODE or /m/CODE) — skip landing, go to name
        // entry (or straight to join if name is already remembered)
        if (State.myName) {
            // Already have a name — join the room directly
            const tryJoin = () => socket.emit('join_room', { code: presetCode, name: State.myName });
            if (socket.connected) tryJoin();
            else socket.once('connect', tryJoin);
            showScreen('screen-home');
        } else {
            showScreen('screen-guest');
            setTimeout(() => { try { $('input-name').focus(); } catch (e) {} }, 50);
        }
    } else if (State.myName) {
        // Returning visitor with a remembered name — skip landing, go straight to games
        showScreen('screen-home');
    } else {
        // First-time visitor — show the landing page (sign in / continue as guest)
        showScreen('screen-landing');
    }
}

document.addEventListener('DOMContentLoaded', boot);
