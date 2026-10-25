// Tool host: the only code that touches the user's files and shell on behalf of the
// agent. It runs in the Electron main process and enforces access itself, so a
// confused or misled model cannot get past it. The agent service never sees a path
// it hasn't been allowed to use.
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const WIN = process.platform === "win32";
const SKIP_DIRS = new Set([".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next", "target"]);
const MAX_READ_BYTES = 1_000_000;
const MAX_OUTPUT_CHARS = 20_000;

// Folders the user has approved this session. Real (symlink-resolved) paths.
const grants = new Set();

class NeedsGrant extends Error {
  constructor(root) {
    super(`Nemo does not have access to ${root} yet.`);
    this.needsGrant = root;
  }
}

const norm = (p) => (WIN ? p.toLowerCase() : p);

function inside(child, root) {
  const rel = path.relative(norm(root), norm(child));
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

// Resolve symlinks on the deepest part of the path that exists, so a link inside a
// granted folder can't be used to reach outside it.
function realish(p) {
  let abs = path.resolve(p);
  const tail = [];
  while (!fs.existsSync(abs)) {
    const parent = path.dirname(abs);
    if (parent === abs) break;
    tail.unshift(path.basename(abs));
    abs = parent;
  }
  let real = abs;
  try {
    real = fs.realpathSync.native(abs);
  } catch {}
  return path.join(real, ...tail);
}

function nearestExistingDir(p) {
  let cur = p;
  while (!fs.existsSync(cur) || !fs.statSync(cur).isDirectory()) {
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return cur;
}

function isProtected(p) {
  const base = path.basename(p).toLowerCase();
  return /^\.env(\..*)?$/.test(base) || /\.(pem|key|p12|pfx)$/.test(base) || /^id_(rsa|dsa|ecdsa|ed25519)/.test(base);
}

function tooBroadToGrant(real) {
  if (norm(real) === norm(path.parse(real).root)) return true; // a whole drive
  if (inside(realish(os.homedir()), real)) return true; // home folder or any parent of it
  const system = [process.env.SystemRoot, process.env.ProgramFiles, process.env["ProgramFiles(x86)"]].filter(Boolean);
  return system.some((s) => inside(real, realish(s)));
}

function grantFolder(p) {
  const real = realish(p);
  if (!fs.existsSync(real) || !fs.statSync(real).isDirectory()) throw new Error(`Not a folder: ${p}`);
  if (tooBroadToGrant(real)) throw new Error(`${real} is too broad to share. Pick a project folder instead.`);
  grants.add(real);
  return real;
}

function access(p, { write = false } = {}) {
  if (typeof p !== "string" || !p.trim()) throw new Error("path is required");
  const real = realish(p);
  if (isProtected(real)) {
    throw new Error(`${path.basename(real)} holds secrets and is off limits to Nemo.`);
  }
  if (write && real.split(path.sep).some((s) => s.toLowerCase() === ".git")) {
    throw new Error("Nemo does not modify files inside .git.");
  }
  for (const g of grants) if (inside(real, g)) return real;
  throw new NeedsGrant(nearestExistingDir(fs.existsSync(real) && fs.statSync(real).isFile() ? path.dirname(real) : real));
}

const looksBinary = (buf) => buf.subarray(0, 4096).includes(0);

// ---- tools -----------------------------------------------------------------

function listDir({ path: p }) {
  const real = access(p);
  const entries = fs.readdirSync(real, { withFileTypes: true }).sort((a, b) => b.isDirectory() - a.isDirectory() || a.name.localeCompare(b.name));
  const shown = entries.slice(0, 200).map((e) => (e.isDirectory() ? `${e.name}/` : e.name));
  return shown.join("\n") + (entries.length > 200 ? `\n... and ${entries.length - 200} more` : "") || "(empty folder)";
}

function readFile({ path: p, offset = 1, limit = 400 }) {
  const real = access(p);
  const stat = fs.statSync(real);
  if (!stat.isFile()) throw new Error("not a file");
  if (stat.size > MAX_READ_BYTES) throw new Error("file is larger than 1 MB; search it or read part of it with run_command");
  const buf = fs.readFileSync(real);
  if (looksBinary(buf)) throw new Error("binary file");
  const lines = buf.toString("utf8").split(/\r?\n/);
  const start = Math.max(1, offset);
  const slice = lines.slice(start - 1, start - 1 + limit);
  const body = slice.map((l, i) => `${start + i}\t${l}`).join("\n");
  const more = start - 1 + limit < lines.length ? `\n... ${lines.length - (start - 1 + limit)} more lines (use offset)` : "";
  return body + more;
}

function globToRegExp(glob) {
  const esc = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${esc}$`, "i");
}

function searchFiles({ path: p, pattern, glob }) {
  const root = access(p);
  let re;
  try {
    re = new RegExp(pattern, "i");
  } catch (e) {
    throw new Error(`invalid regular expression: ${e.message}`);
  }
  const nameRe = glob ? globToRegExp(glob) : null;
  const hits = [];
  let visited = 0;
  const visit = (file) => {
    if (hits.length >= 60 || visited > 5000) return;
    if (isProtected(file) || (nameRe && !nameRe.test(path.basename(file)))) return;
    let stat;
    try {
      stat = fs.statSync(file);
    } catch {
      return;
    }
    if (stat.size > MAX_READ_BYTES) return;
    visited++;
    const buf = fs.readFileSync(file);
    if (looksBinary(buf)) return;
    buf.toString("utf8").split(/\r?\n/).forEach((line, i) => {
      if (hits.length < 60 && re.test(line)) hits.push(`${path.relative(root, file) || path.basename(file)}:${i + 1}: ${line.trim().slice(0, 200)}`);
    });
  };
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name)) walk(path.join(dir, e.name));
      } else if (e.isFile()) visit(path.join(dir, e.name));
    }
  };
  fs.statSync(root).isDirectory() ? walk(root) : visit(root);
  return hits.length ? hits.join("\n") : "no matches";
}

function writeFile({ path: p, content }) {
  const real = access(p, { write: true });
  if (typeof content !== "string") throw new Error("content must be text");
  const existed = fs.existsSync(real);
  fs.mkdirSync(path.dirname(real), { recursive: true });
  fs.writeFileSync(real, content, "utf8");
  return `${existed ? "overwrote" : "created"} ${real} (${Buffer.byteLength(content)} bytes)`;
}

function editFile({ path: p, old_text: oldText, new_text: newText }) {
  const real = access(p, { write: true });
  if (!oldText) throw new Error("old_text must not be empty");
  if (typeof newText !== "string") throw new Error("new_text must be text");
  let content = fs.readFileSync(real, "utf8");
  // Files saved with Windows line endings: make the model's \n match them.
  const crlf = content.includes("\r\n");
  const fix = (s) => (crlf ? s.replace(/\r?\n/g, "\r\n") : s);
  const needle = fix(oldText);
  const first = content.indexOf(needle);
  if (first === -1) throw new Error("old_text was not found; read the file again and copy the exact text");
  if (content.indexOf(needle, first + 1) !== -1) throw new Error("old_text appears more than once; include more surrounding lines so it is unique");
  content = content.slice(0, first) + fix(newText) + content.slice(first + needle.length);
  fs.writeFileSync(real, content, "utf8");
  return `edited ${real}`;
}

const SECRET_ENV = /(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)/i;

function runCommand({ command, cwd, timeout_seconds: timeout = 60 }) {
  if (typeof command !== "string" || !command.trim()) throw new Error("command is required");
  const dir = access(cwd);
  if (!fs.statSync(dir).isDirectory()) throw new Error("cwd must be a folder");
  const seconds = Math.min(Math.max(Number(timeout) || 60, 1), 300);
  // Commands never inherit the user's secrets from the environment.
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !SECRET_ENV.test(k)));
  const [shell, args] = WIN
    ? ["powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command]]
    : ["sh", ["-c", command]];

  return new Promise((resolve) => {
    let out = "";
    let timedOut = false;
    const child = spawn(shell, args, { cwd: dir, env, windowsHide: true });
    const add = (d) => {
      if (out.length < MAX_OUTPUT_CHARS * 2) out += d.toString();
    };
    child.stdout.on("data", add);
    child.stderr.on("data", add);
    const timer = setTimeout(() => {
      timedOut = true;
      if (WIN) spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
      else child.kill("SIGKILL");
    }, seconds * 1000);
    const finish = (code, err) => {
      clearTimeout(timer);
      let text = out.length > MAX_OUTPUT_CHARS ? `${out.slice(0, MAX_OUTPUT_CHARS / 2)}\n... output trimmed ...\n${out.slice(-MAX_OUTPUT_CHARS / 2)}` : out;
      if (err) text += `\n${err}`;
      resolve(`${timedOut ? `timed out after ${seconds}s` : `exit code ${code}`}\n${text}`.trim());
    };
    child.on("error", (e) => finish(-1, `failed to start: ${e.message}`));
    child.on("close", (code) => finish(code));
  });
}

// Used by the agent service before it reads a local path itself (for example the repo
// scan): the same folder approval and protected-file rules apply as for any other tool.
function checkAccess({ path: p }) {
  return access(p);
}

const HANDLERS = {
  check_access: checkAccess,
  list_dir: listDir,
  read_file: readFile,
  search_files: searchFiles,
  write_file: writeFile,
  edit_file: editFile,
  run_command: runCommand,
};

async function runTool(name, args) {
  const handler = HANDLERS[name];
  if (!handler) return { ok: false, error: `no such tool: ${name}` };
  try {
    return { ok: true, result: await handler(args || {}) };
  } catch (e) {
    if (e instanceof NeedsGrant) return { ok: false, needsGrant: e.needsGrant, error: e.message };
    return { ok: false, error: e.message };
  }
}

module.exports = { runTool, grantFolder, _grants: grants };
