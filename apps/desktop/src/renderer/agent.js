// Connection to the agent service: sends requests, runs client tools, asks the user
// for approval, and shows replies.
const WS_URL = "ws://127.0.0.1:8000/ws";
const reply = document.getElementById("reply");
const thinking = document.getElementById("thinking");
const confirmBox = document.getElementById("confirm");
const confirmTitle = document.getElementById("confirm-title");
const confirmDetail = document.getElementById("confirm-detail");
const allowBtn = document.getElementById("allow");
const allowSessionBtn = document.getElementById("allow-session");
const denyBtn = document.getElementById("deny");
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

// ---- Asking the user -------------------------------------------------------
// Everything shown here is built with textContent, never innerHTML: the text comes
// from a model and must not be able to inject markup into the approval card.
const clip = (s, n) => (String(s).length > n ? `${String(s).slice(0, n)}...` : String(s));
const baseName = (p) => String(p || "").split(/[\\/]/).pop();

function linesOf(text, kind, max = 12) {
  const all = String(text ?? "").split(/\r?\n/);
  const mark = kind === "add" ? "+ " : kind === "del" ? "- " : "";
  const out = all.slice(0, max).map((l) => ({ kind, text: mark + clip(l, 200) }));
  if (all.length > max) out.push({ kind: "dim", text: `... ${all.length - max} more lines` });
  return out;
}

// What the user sees before a tool runs: the exact change or command, not a summary.
function describe(name, args, risk) {
  switch (name) {
    case "run_command":
      return {
        title: "Run this command?",
        lines: [{ kind: "dim", text: `in ${args.cwd}` }, { kind: "ctx", text: `$ ${clip(args.command, 800)}` }],
      };
    case "edit_file":
      return {
        title: `Edit ${baseName(args.path)}?`,
        lines: [{ kind: "dim", text: args.path }, ...linesOf(args.old_text, "del"), ...linesOf(args.new_text, "add")],
        canRemember: risk === "write",
      };
    case "write_file":
      return {
        title: `Write ${baseName(args.path)}?`,
        lines: [{ kind: "dim", text: `${args.path} (${String(args.content ?? "").length} characters)` }, ...linesOf(args.content, "add")],
        canRemember: risk === "write",
      };
    case "clipboard_write":
      return { title: "Replace your clipboard?", lines: linesOf(args.text, "add"), canRemember: risk === "write" };
    default:
      return { title: `Allow ${name}?`, lines: linesOf(JSON.stringify(args, null, 2), "ctx"), canRemember: risk === "write" };
  }
}

function askUser({ title, lines, canRemember = false }) {
  return new Promise((resolve) => {
    confirmTitle.textContent = title;
    confirmDetail.replaceChildren(
      ...lines.map((l) => {
        const span = document.createElement("span");
        span.className = l.kind === "ctx" ? "" : l.kind;
        span.textContent = l.text + "\n";
        return span;
      })
    );
    allowSessionBtn.classList.toggle("hidden", !canRemember);
    confirmBox.classList.remove("hidden");
    place();
    const done = (approved, remember = false) => {
      confirmBox.classList.add("hidden");
      place();
      resolve({ approved, remember });
    };
    allowBtn.onclick = () => done(true);
    allowSessionBtn.onclick = () => done(true, true);
    denyBtn.onclick = () => done(false);
  });
}

// ---- Client tools ----------------------------------------------------------
// File and shell tools are enforced in the main process. When a path is outside the
// folders the user has shared, the user is asked before anything runs.
async function runClientTool(name, args) {
  let result = await window.nemo.runTool(name, args);
  if (!result.ok && result.needsGrant) {
    const answer = await askUser({
      title: "Let Nemo work in this folder?",
      lines: [
        { kind: "ctx", text: result.needsGrant },
        { kind: "dim", text: "Nemo can read, search and (with your approval each time) change files here until you quit." },
      ],
    });
    if (!answer.approved) throw new Error("the user did not allow access to that folder");
    const granted = await window.nemo.grantFolder(result.needsGrant);
    if (!granted.ok) throw new Error(granted.error);
    result = await window.nemo.runTool(name, args);
  }
  if (!result.ok) throw new Error(result.error);
  return result.result;
}

async function handle(event) {
  switch (event.type) {
    case "state":
      if (event.state === "thinking") showThinking();
      if (event.state !== "idle") setState(event.state);
      break;
    case "tool_request": {
      try {
        const local = window.nemo.tools[event.name]; // clipboard
        const result = local ? await local(event.args) : await runClientTool(event.name, event.args);
        send({ type: "tool_result", id: event.id, ok: true, result });
      } catch (err) {
        send({ type: "tool_result", id: event.id, ok: false, result: String(err.message || err) });
      }
      break;
    }
    case "confirm_request": {
      const answer = await askUser(describe(event.name, event.args, event.risk));
      send({ type: "confirm", id: event.id, approved: answer.approved, remember: answer.remember });
      break;
    }
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

input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !input.value.trim()) return;
  send({ type: "user_message", text: input.value.trim() });
  input.value = "";
  showThinking();
  setState("thinking");
});

connect();
