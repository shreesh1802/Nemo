// Connection to the agent service: sends requests, runs client tools, shows replies.
const WS_URL = "ws://127.0.0.1:8000/ws";
const reply = document.getElementById("reply");
const thinking = document.getElementById("thinking");
const confirmBox = document.getElementById("confirm");
const confirmText = document.getElementById("confirm-text");
let socket = null;
let thinkingSince = 0;

function connect() {
  socket = new WebSocket(WS_URL);
  socket.onmessage = (msg) => handle(JSON.parse(msg.data));
  socket.onclose = () => setTimeout(connect, 2000);
  socket.onerror = () => socket.close();
}

function send(event) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(event));
}

function showThinking() {
  reply.classList.add("hidden");
  thinking.classList.remove("hidden");
  thinkingSince = Date.now();
  place();
}

// Reveal the reply word by word so it feels composed rather than dumped.
function showReply(text) {
  thinking.classList.add("hidden");
  reply.replaceChildren();
  reply.classList.remove("hidden");
  text.split(/(\s+)/).forEach((part, i) => {
    if (!part.trim()) return reply.append(part);
    const span = document.createElement("span");
    span.className = "w";
    span.textContent = part;
    span.style.animationDelay = `${i * 18}ms`;
    reply.append(span);
  });
  place();
}

async function handle(event) {
  switch (event.type) {
    case "state":
      if (event.state === "thinking") showThinking();
      if (event.state !== "idle") setState(event.state);
      break;
    case "tool_request": {
      const run = window.nemo.tools[event.name];
      try {
        if (!run) throw new Error(`no client tool named ${event.name}`);
        send({ type: "tool_result", id: event.id, ok: true, result: await run(event.args) });
      } catch (err) {
        send({ type: "tool_result", id: event.id, ok: false, result: String(err.message || err) });
      }
      break;
    }
    case "confirm_request":
      confirmText.textContent = `Allow ${event.name}? (${event.risk})`;
      confirmBox.classList.remove("hidden");
      place();
      document.getElementById("allow").onclick = () => answer(event.id, true);
      document.getElementById("deny").onclick = () => answer(event.id, false);
      break;
    case "final":
    case "error": {
      // Make sure the "thinking" beat is visible even for instant replies.
      const wait = Math.max(0, 900 - (Date.now() - thinkingSince));
      setTimeout(() => {
        showReply(event.type === "final" ? event.text : event.message);
        setState("idle"); // the border glow fades out as the answer appears
        scheduleSleep(20000);
      }, wait);
      break;
    }
  }
}

function answer(id, approved) {
  confirmBox.classList.add("hidden");
  place();
  send({ type: "confirm", id, approved });
}

input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !input.value.trim()) return;
  send({ type: "user_message", text: input.value.trim() });
  input.value = "";
  showThinking();
  setState("thinking");
});

connect();
