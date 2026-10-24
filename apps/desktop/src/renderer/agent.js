// Connection to the agent service: sends requests, runs client tools, shows replies.
const WS_URL = "ws://127.0.0.1:8000/ws";
const reply = document.getElementById("reply");
const confirmBox = document.getElementById("confirm");
const confirmText = document.getElementById("confirm-text");
let socket = null;

function connect() {
  socket = new WebSocket(WS_URL);
  socket.onmessage = (msg) => handle(JSON.parse(msg.data));
  socket.onclose = () => setTimeout(connect, 2000);
  socket.onerror = () => socket.close();
}

function send(event) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(event));
}

function speak(text) {
  if (!text || !window.speechSynthesis) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.onstart = () => setState("speaking");
  utter.onend = () => setState("listening");
  speechSynthesis.speak(utter);
}

async function handle(event) {
  switch (event.type) {
    case "state":
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
      reply.textContent = event.text;
      setState("listening");
      place();
      speak(event.text);
      scheduleSleep(15000);
      break;
    case "error":
      reply.textContent = event.message;
      setState("listening");
      place();
      break;
  }
}

function answer(id, approved) {
  confirmBox.classList.add("hidden");
  place();
  send({ type: "confirm", id, approved });
}

input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !input.value.trim()) return;
  reply.textContent = "";
  send({ type: "user_message", text: input.value.trim() });
  input.value = "";
});

connect();
