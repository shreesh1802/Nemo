// Robot behaviour: wandering, hover/hotkey wake, bubble placement, click-through.
const robot = document.getElementById("robot");
const bubble = document.getElementById("bubble");
const input = document.getElementById("input");

const ROBOT_W = 64;
const ROBOT_H = 86;
const SPEED = 60; // px per second

const pos = { x: 200, y: window.innerHeight - ROBOT_H - 8 };
let state = "idle";
let awake = false; // true while the user is interacting; wandering pauses
let wanderTimer = null;
let sleepTimer = null;

function place() {
  robot.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
  const bx = Math.min(Math.max(pos.x + ROBOT_W / 2 - 140, 8), window.innerWidth - 288);
  const above = pos.y > bubble.offsetHeight + 24;
  bubble.style.left = `${bx}px`;
  bubble.style.top = above ? `${pos.y - bubble.offsetHeight - 10}px` : `${pos.y + ROBOT_H + 10}px`;
}

function setState(next) {
  state = next;
  robot.classList.remove("idle", "listening", "thinking", "acting", "speaking");
  robot.classList.add(next);
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

async function wander() {
  if (awake) return;
  // Mostly stroll along the bottom; occasionally climb somewhere higher.
  const x = 20 + Math.random() * (window.innerWidth - ROBOT_W - 40);
  const roaming = Math.random() < 0.25;
  const floor = window.innerHeight - ROBOT_H - 8;
  const y = roaming ? floor - Math.random() * (window.innerHeight * 0.5) : floor;
  await walkTo(x, y);
  wanderTimer = setTimeout(wander, 1500 + Math.random() * 4000);
}

function wake() {
  awake = true;
  clearTimeout(wanderTimer);
  clearTimeout(sleepTimer);
  // Freeze in place where the robot currently is.
  const rect = robot.getBoundingClientRect();
  pos.x = rect.left;
  pos.y = rect.top;
  robot.style.transitionDuration = "0s";
  robot.classList.remove("walking");
  place();
  setState("listening");
  bubble.classList.remove("hidden");
  place();
  window.nemo.setInteractive(true);
  input.focus();
}

function sleep() {
  if (state !== "listening" && state !== "idle") return;
  awake = false;
  bubble.classList.add("hidden");
  document.getElementById("reply").textContent = "";
  setState("idle");
  window.nemo.setInteractive(false);
  wanderTimer = setTimeout(wander, 800);
}

function scheduleSleep(ms = 8000) {
  clearTimeout(sleepTimer);
  sleepTimer = setTimeout(() => {
    if (!input.value.trim()) sleep();
  }, ms);
}

// Click-through: the window ignores the mouse except while over the robot/bubble.
let hoverTimer = null;
document.addEventListener("mousemove", (e) => {
  const overHit = !!e.target.closest(".hit");
  if (!awake) window.nemo.setInteractive(overHit);
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
robot.addEventListener("click", () => (awake ? scheduleSleep(0) : wake()));
window.nemo.onWake(() => (awake ? input.focus() : wake()));
input.addEventListener("input", () => clearTimeout(sleepTimer));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && awake) {
    setState("idle");
    sleep();
  }
});

place();
bubble.classList.add("hidden");
wanderTimer = setTimeout(wander, 1000);
