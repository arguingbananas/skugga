// Skugga phone page: join, lobby, rounds, answers and scores.
// The server decides everything (docs/game-spec.md); this page shows the
// state it gets from GET /state every 250 ms, fetches each dot's track once
// the server says it's revealed, and sends joins, starts and guesses.

const POLL_MS = 250;
const TOTAL_DOTS = 15;
const TOKEN_KEY = "skugga-token";

const $ = (id) => document.getElementById(id);
const el = {
  roundLabel: $("round-label"),
  screens: { join: $("screen-join"), lobby: $("screen-lobby"), play: $("screen-play"), final: $("screen-final") },
  joinForm: $("join-form"), joinName: $("join-name"), joinError: $("join-error"),
  lobbyNote: $("lobby-note"), startBtn: $("start-btn"),
  canvas: $("canvas"), countdown: $("countdown"),
  answer: $("answer"), answerCategory: $("answer-category"), answerResult: $("answer-result"),
  dotsLine: $("dots-line"), guessForm: $("guess-form"), guess: $("guess"), guessStatus: $("guess-status"),
  answerGuesses: $("answer-guesses"), answerCredit: $("answer-credit"),
  finalTitle: $("final-title"), againBtn: $("again-btn"), finalNote: $("final-note"),
  scores: $("scores"), connection: $("connection"),
};
const ctx = el.canvas.getContext("2d");

// --- storage (may be unavailable, e.g. private browsing)

function loadToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function saveToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* the game still works until the page is reloaded */ }
}

// --- state

let token = loadToken();
let state = null;            // last /state response
let polledAt = 0;            // performance.now() when it arrived
let tracks = new Map();      // marker index -> Int32Array (x0, y0, x1, y1, ...)
let tracksRound = null;      // round id the tracks belong to
const inFlight = new Set();
const lastTry = new Map();   // "round/n" -> performance.now() of the last request
let lastRoundId = null;
let guessSent = false;
let failures = 0;

/** Server time now, from the last poll plus local time elapsed since. */
function serverNow() {
  return state ? state.serverNow + (performance.now() - polledAt) : 0;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? { cache: "no-store" } : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  return { ok: res.ok, status: res.status, data };
}

// --- joining

const JOIN_ERRORS = {
  name_taken: "Someone already has that name.",
  full: "The game is full (8 players).",
  bad_name: "Use 1 to 16 letters or numbers.",
};

async function join(name) {
  // Rejoining sends only the token: if the server doesn't know it, it refuses
  // (no name), and we show the join screen instead of making a new player.
  const res = await api("/join", name === undefined ? { token } : { name });
  if (res.ok) {
    token = res.data.token;
    saveToken(token);
    el.joinError.textContent = "";
    return true;
  }
  if (token) {            // stored token unknown here (server restarted): start over
    token = null;
    saveToken(null);
    return false;
  }
  el.joinError.textContent = JOIN_ERRORS[res.data?.error] || "Couldn't join. Try again.";
  return false;
}

el.joinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = el.joinName.value.trim();
  if (!name) return;
  el.joinForm.querySelector("button").disabled = true;
  await join(name);
  el.joinForm.querySelector("button").disabled = false;
  poll(true);
});

el.startBtn.addEventListener("click", async () => {
  el.startBtn.disabled = true;
  await api("/start", { token });
  poll(true);
});

el.againBtn.addEventListener("click", async () => {
  el.againBtn.disabled = true;
  await api("/again", { token });
  poll(true);
});

// --- guessing

el.guessForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = el.guess.value.trim();
  const round = state?.round;
  if (!text || !round || guessSent) return;
  guessSent = true;
  el.guess.disabled = true;
  el.guessForm.querySelector("button").disabled = true;
  const res = await api("/guess", { token, roundId: round.id, guess: text });
  if (res.ok && res.data.correct) {
    showGuessStatus("Correct!", "good");
  } else if (res.ok) {
    showGuessStatus(`“${text}” isn't it. You're out for this clip.`, "bad");
  } else {
    showGuessStatus("Too late for that one.", "bad");
  }
  poll(true);
});

function showGuessStatus(text, kind) {
  el.guessStatus.textContent = text;
  el.guessStatus.className = "guess-status " + (kind || "");
}

// --- polling

let pollTimer = null;
async function poll(now = false) {
  clearTimeout(pollTimer);
  if (now !== true && document.hidden) {    // don't poll from a hidden tab
    pollTimer = setTimeout(poll, 1000);
    return;
  }
  try {
    const res = await api(`/state?token=${encodeURIComponent(token || "")}`);
    if (!res.ok) throw new Error(String(res.status));
    state = res.data;
    polledAt = performance.now();
    failures = 0;
    el.connection.hidden = true;
    if (token && !state.you) {        // our token isn't known (server restarted)
      token = null;
      saveToken(null);
    }
    render();
    fetchTracks();
  } catch {
    failures += 1;
    el.connection.hidden = failures < 3;
  }
  pollTimer = setTimeout(poll, POLL_MS);
}

/** Dots showing now: the server's count, advanced locally between polls. */
function dotsNow() {
  const r = state?.round;
  if (!r) return 0;
  if (state.status === "answer") return TOTAL_DOTS;
  const now = serverNow();
  const local = now < r.t0 ? 0 : Math.min(TOTAL_DOTS, 1 + Math.floor((now - r.t0) / r.dotIntervalMs));
  return Math.max(r.dotsShown, local);
}

/** Fetch the track of every revealed dot we lack. Uses the local count, so a
 * new dot appears with the counter; if the server says it's a moment early
 * (403), the next call retries. */
function fetchTracks() {
  const r = state?.round;
  if (!r || !token || !["reveal", "answer"].includes(state.status)) return;
  if (tracksRound !== r.id) {
    tracks = new Map();
    tracksRound = r.id;
    lastTry.clear();
  }
  for (let n = 0; n < dotsNow(); n++) {
    const key = `${r.id}/${n}`;
    if (tracks.has(n) || inFlight.has(key)) continue;
    if (performance.now() - (lastTry.get(key) || 0) < 150) continue;   // retry gently
    lastTry.set(key, performance.now());
    inFlight.add(key);
    api(`/round/${r.id}/marker/${n}?token=${encodeURIComponent(token)}`)
      .then((res) => {
        if (res.ok && tracksRound === r.id) tracks.set(n, Int32Array.from(res.data.track));
      })
      .catch(() => {})
      .finally(() => inFlight.delete(key));
  }
}

// --- rendering

function show(name) {
  for (const [key, node] of Object.entries(el.screens)) node.hidden = key !== name;
}

function render() {
  const s = state;
  const me = s.you;
  el.scores.hidden = !me;
  renderScores();

  if (!me) {
    el.roundLabel.textContent = "";
    show("join");
    return;
  }
  if (s.status === "lobby") {
    el.roundLabel.textContent = "Lobby";
    show("lobby");
    const present = s.players.filter((p) => !p.away).length;
    const leader = s.players.find((p) => p.leader);
    el.startBtn.hidden = !me.leader;
    el.startBtn.disabled = present < s.minPlayers;
    el.lobbyNote.textContent = me.leader
      ? (present < s.minPlayers ? "Waiting for at least one more player…" : "Start when everyone's in.")
      : `Waiting for ${leader ? leader.name : "the leader"} to start…`;
    return;
  }
  if (s.status === "final") {
    el.roundLabel.textContent = "Game over";
    show("final");
    const playing = s.players.filter((p) => !p.waiting);
    const best = Math.max(...playing.map((p) => p.score));
    const winners = playing.filter((p) => p.score === best).map((p) => p.name);
    el.finalTitle.textContent =
      !playing.length || best === 0 ? "Final scores" :
      winners.length === 1 ? `${winners[0]} wins!` : `Tie: ${winners.join(" and ")}`;
    el.againBtn.hidden = !me.leader;
    el.againBtn.disabled = false;
    const leader = s.players.find((p) => p.leader);
    el.finalNote.textContent = me.leader ? "" : `Waiting for ${leader ? leader.name : "the leader"} to start another game…`;
    return;
  }

  // countdown, reveal, answer
  show("play");
  const r = s.round;
  el.roundLabel.textContent = `Round ${r.number} of ${s.totalRounds}`;
  if (r.id !== lastRoundId) {           // new round: reset the guess box
    lastRoundId = r.id;
    guessSent = false;
    el.guess.value = "";
    showGuessStatus("");
  }
  const canGuess = s.status === "reveal" && !me.guessed && !me.waiting && !guessSent;
  el.guess.disabled = !canGuess;
  el.guessForm.querySelector("button").disabled = !canGuess;
  el.guessForm.hidden = s.status === "answer";
  if (me.waiting) showGuessStatus("Game in progress: you'll play from the next game.", "");

  el.countdown.hidden = s.status !== "countdown";
  el.answer.hidden = s.status !== "answer";
  el.answerGuesses.hidden = s.status !== "answer";
  el.answerCredit.hidden = s.status !== "answer";
  if (s.status === "answer") renderAnswer(s.answer);
}

function renderAnswer(a) {
  el.answerCategory.textContent = a.category;
  el.answerResult.textContent =
    a.endReason === "answered" ? `${a.winner} got it: +${a.points}` :
    a.endReason === "all_out" ? "Everyone guessed wrong." : "Nobody got it.";
  el.answerGuesses.replaceChildren(...a.guesses.map((g) => {
    const li = document.createElement("li");
    const who = document.createElement("span");
    who.textContent = g.name;
    const what = document.createElement("span");
    what.textContent = `${g.guess} ${g.correct ? "✓" : "✗"}`;
    what.className = g.correct ? "good" : "bad";
    li.append(who, what);
    return li;
  }));
  el.answerCredit.textContent = `CMU ${a.clipId}: ${a.description}`;
}

function renderScores() {
  const s = state;
  const rows = [...s.players].sort((a, b) => b.score - a.score || a.id - b.id);
  el.scores.replaceChildren(...rows.map((p) => {
    const li = document.createElement("li");
    li.classList.toggle("me", s.you?.id === p.id);
    li.classList.toggle("out", p.out && ["reveal", "answer"].includes(s.status));
    li.classList.toggle("away", p.away);
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = p.name;
    const tags = [p.leader && "leader", p.waiting && "next game", p.away && "away", s.you?.id === p.id && "you"].filter(Boolean);
    if (tags.length) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = tags.join(" · ");
      name.append(tag);
    }
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = p.score;
    li.append(name, score);
    return li;
  }));
}

// --- drawing (every animation frame)

function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(el.canvas.clientWidth * dpr);
  const h = Math.round(el.canvas.clientHeight * dpr);
  if (el.canvas.width !== w || el.canvas.height !== h) {
    el.canvas.width = w;
    el.canvas.height = h;
  }
  return dpr;
}

function draw() {
  requestAnimationFrame(draw);
  if (el.screens.play.hidden) return;
  const dpr = resizeCanvas();
  const W = el.canvas.width, H = el.canvas.height;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);

  const s = state;
  const r = s?.round;
  if (!r) return;
  const now = serverNow();

  if (s.status === "countdown") {
    el.countdown.textContent = String(Math.max(1, Math.ceil((r.t0 - now) / 1000)));
    el.dotsLine.textContent = "Get ready…";
    return;
  }

  const dots = dotsNow();
  renderDotsLine(dots, s.status === "reveal");
  if (dots > tracks.size && tracksRound === r.id) fetchTracks();   // a new dot is due

  // Fit the clip's bounds into the canvas, feet near the bottom. While the
  // answer shows, leave room for it at the top.
  const b = r.bounds;
  const margin = 0.08 * H, top = s.status === "answer" ? 0.24 * H : margin;
  const spanX = Math.max(b.maxX - b.minX, 400), spanY = Math.max(b.maxY, 1000);
  const scale = Math.min((W * 0.84) / spanX, (H - top - margin) / spanY);
  const cx = W / 2 - ((b.minX + b.maxX) / 2) * scale;
  const floor = top + (H - top - margin) / 2 + (spanY / 2) * scale;

  const frame = Math.floor((Math.max(0, now - r.t0) / 1000) * r.fps) % r.frameCount;
  const radius = Math.max(3 * dpr, Math.min(W, H) * 0.014);
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  for (let n = 0; n < dots; n++) {
    const t = tracks.get(n);
    if (!t || tracksRound !== r.id) continue;
    const x = cx + t[frame * 2] * scale;
    const y = floor - t[frame * 2 + 1] * scale;
    ctx.moveTo(x + radius, y);
    ctx.arc(x, y, radius, 0, Math.PI * 2);
  }
  ctx.fill();
}

function renderDotsLine(dots, live) {
  const left = document.createElement("span");
  left.textContent = `${dots} / ${TOTAL_DOTS} dots`;
  const right = document.createElement("span");
  if (live) {
    right.append("Right now: ");
    const pts = document.createElement("strong");
    pts.textContent = `${TOTAL_DOTS + 1 - dots} pts`;
    right.append(pts);
  }
  el.dotsLine.replaceChildren(left, right);
}

// --- keep the screen on during a game, where the browser allows it

let wakeLock = null;
async function keepAwake() {
  try {
    if ("wakeLock" in navigator && !wakeLock && document.visibilityState === "visible") {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => { wakeLock = null; });
    }
  } catch { /* not allowed here; fine */ }
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) { keepAwake(); poll(true); }
});

// --- start

(async () => {
  if (token) await join();        // rejoin with the stored token
  await poll(true);
  keepAwake();
  requestAnimationFrame(draw);
})();
