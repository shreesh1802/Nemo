// Robot behaviour: wandering, dragging, hover/hotkey wake, bubble placement,
// click-through, and the Siri-style border glow.
const robot = document.getElementById("robot");
const bubble = document.getElementById("bubble");
const input = document.getElementById("input");
const glow = document.getElementById("glow");

const ROBOT_W = 64;
const ROBOT_H = 86;
const SPEED = 60; // px per second
const MIN_CURSOR_DIST = 450; // roam at least this far from the user's cursor when possible

const pos = { x: 200, y: 0 }; // set properly in init() once the window has a size
const cursor = { x: -9999, y: -9999 };
let state = "idle";
let awake = false; // true while the user is interacting; wandering pauses
let drag = null;
let wanderTimer = null;
let sleepTimer = null;
let actionTimer = null;

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const floorY = () => window.innerHeight - ROBOT_H - 8;

function place() {
  robot.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
  const bx = clamp(pos.x + ROBOT_W / 2 - 170, 8, window.innerWidth - 348);
  const above = pos.y > bubble.offsetHeight + 24;
  bubble.style.left = `${bx}px`;
  bubble.style.top = above ? `${pos.y - bubble.offsetHeight - 10}px` : `${pos.y + ROBOT_H + 10}px`;
  bubble.style.transformOrigin = above ? "bottom center" : "top center";
}

// The border glow follows the state: lit while listening, pulsing while working,
// fading out once Nemo answers.
function setState(next) {
  state = next;
  robot.classList.remove("idle", "listening", "thinking", "acting");
  robot.classList.add(next);
  const working = next === "thinking" || next === "acting";
  glow.classList.toggle("on", next === "listening" || working);
  glow.classList.toggle("pulse", working);
}

function freeze() {
  // Capture the current on-screen position (mid-walk included) and stop moving.
  const rect = robot.getBoundingClientRect();
  pos.x = rect.left;
  pos.y = rect.top;
  robot.style.transitionDuration = "0s";
  robot.classList.remove("walking");
  place();
}

function walkTo(x, y) {
  const dist = Math.hypot(x - pos.x, y - pos.y);
  const secs = Math.max(dist / SPEED, 0.1);
  robot.classList.toggle("facing-left", x < pos.x);
  robot.style.transitionDuration = `${secs}s`;
  robot.classList.add("walking");
  pos.x = x;
  pos.y = y;
  place();
  return new Promise((resolve) =>
    setTimeout(() => {
      robot.classList.remove("walking");
      resolve();
    }, secs * 1000)
  );
}

// Pick a spot away from where the user is working (their cursor).
function pickSpot() {
  const candidates = [];
  for (let i = 0; i < 14; i++) {
    const x = 20 + Math.random() * (window.innerWidth - ROBOT_W - 40);
    const y = Math.random() < 0.7 ? floorY() : floorY() - Math.random() * window.innerHeight * 0.5;
    const d = Math.hypot(x + ROBOT_W / 2 - cursor.x, y + ROBOT_H / 2 - cursor.y);
    candidates.push({ x, y, d });
  }
  const far = candidates.filter((c) => c.d >= MIN_CURSOR_DIST);
  if (far.length) return far[Math.floor(Math.random() * far.length)];
  return candidates.reduce((a, b) => (b.d > a.d ? b : a)); // small screen: take the farthest
}

function doAction(name, ms) {
  robot.classList.add(name);
  clearTimeout(actionTimer);
  actionTimer = setTimeout(() => robot.classList.remove(name), ms);
}
const ACTIONS = [["wave", 1500], ["hop", 1000], ["look", 1600]];
function randomAction() {
  const [name, ms] = ACTIONS[Math.floor(Math.random() * ACTIONS.length)];
  doAction(name, ms);
  return ms;
}

async function wander() {
  if (awake || drag) return;
  const spot = pickSpot();
  await walkTo(spot.x, spot.y);
  if (awake || drag) return;
  const actionMs = Math.random() < 0.6 ? randomAction() : 0;
  wanderTimer = setTimeout(wander, actionMs + 3000 + Math.random() * 5000);
}

// Stay put for a while (after being dropped or after a chat), act, then move on.
function linger(ms) {
  clearTimeout(wanderTimer);
  const end = Date.now() + ms;
  const tick = () => {
    if (awake || drag) return;
    if (Date.now() >= end) return wander();
    const actionMs = randomAction();
    wanderTimer = setTimeout(tick, actionMs + 1500 + Math.random() * 2000);
  };
  wanderTimer = setTimeout(tick, 1200);
}

function wake() {
  awake = true;
  clearTimeout(wanderTimer);
  clearTimeout(sleepTimer);
  robot.classList.remove("wave", "hop", "look");
  freeze();
  setState("listening");
  bubble.classList.remove("hidden");
  place();
  window.nemo.setInteractive(true);
  input.focus();
}

function sleep() {
  awake = false;
  bubble.classList.add("hidden");
  document.getElementById("reply").classList.add("hidden");
  document.getElementById("thinking").classList.add("hidden");
  setState("idle");
  window.nemo.setInteractive(false);
  linger(6000);
}

function scheduleSleep(ms = 8000) {
  clearTimeout(sleepTimer);
  sleepTimer = setTimeout(() => {
    if (awake && !input.value.trim() && (state === "idle" || state === "listening")) sleep();
  }, ms);
}

// ---- Dragging: pick Nemo up and drop it anywhere ---------------------------
robot.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  robot.setPointerCapture(e.pointerId);
  clearTimeout(hoverTimer);
  hoverTimer = null;
  const rect = robot.getBoundingClientRect();
  drag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top, sx: e.clientX, sy: e.clientY, moved: false };
});
robot.addEventListener("pointermove", (e) => {
  if (!drag) return;
  if (!drag.moved) {
    if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 5) return;
    drag.moved = true;
    clearTimeout(wanderTimer);
    freeze();
    robot.classList.remove("wave", "hop", "look");
    robot.classList.add("dragging");
  }
  pos.x = clamp(e.clientX - drag.dx, 0, window.innerWidth - ROBOT_W);
  pos.y = clamp(e.clientY - drag.dy, 0, window.innerHeight - ROBOT_H);
  place();
});
robot.addEventListener("pointerup", (e) => {
  const d = drag;
  drag = null;
  robot.releasePointerCapture(e.pointerId);
  robot.classList.remove("dragging");
  if (d && d.moved) {
    if (!awake) linger(8000 + Math.random() * 4000); // stay where it was dropped for a bit
  } else {
    awake ? sleep() : wake();
  }
});

// ---- Click-through and hover-to-wake ---------------------------------------
let hoverTimer = null;
document.addEventListener("mousemove", (e) => {
  cursor.x = e.clientX;
  cursor.y = e.clientY;
  if (drag) return;
  if (!awake) window.nemo.setInteractive(!!e.target.closest(".hit"));
  if (e.target.closest("#robot") && !awake && !hoverTimer) {
    hoverTimer = setTimeout(() => {
      hoverTimer = null;
      wake();
    }, 400); // short dwell so brushing past the robot doesn't wake it
  } else if (!e.target.closest("#robot") && hoverTimer) {
    clearTimeout(hoverTimer);
    hoverTimer = null;
  }
});
window.nemo.onWake(() => (awake ? input.focus() : wake()));
input.addEventListener("input", () => clearTimeout(sleepTimer));
input.addEventListener("focus", () => {
  if (awake && state === "idle") setState("listening"); // lights up again when it listens
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && awake) sleep();
});

function init() {
  pos.x = clamp(200, 0, Math.max(0, window.innerWidth - ROBOT_W));
  pos.y = Math.max(0, floorY());
  robot.style.transitionDuration = "0s";
  place();
  bubble.classList.add("hidden");
  clearTimeout(wanderTimer);
  wanderTimer = setTimeout(wander, 1000);
}

// Keep Nemo on screen if the display size changes.
window.addEventListener("resize", () => {
  pos.x = clamp(pos.x, 0, Math.max(0, window.innerWidth - ROBOT_W));
  pos.y = clamp(pos.y, 0, Math.max(0, window.innerHeight - ROBOT_H));
  robot.style.transitionDuration = "0s";
  place();
});

if (document.readyState === "complete") init();
else window.addEventListener("load", init);
