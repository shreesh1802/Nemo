const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { runTool, grantFolder, _grants } = require("../src/tools");

function sandbox() {
  _grants.clear();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "nemo-tools-"));
  grantFolder(dir);
  return dir;
}

test("paths outside a granted folder ask for a grant instead of running", async () => {
  const dir = sandbox();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "nemo-outside-"));
  fs.writeFileSync(path.join(outside, "a.txt"), "x");
  const r = await runTool("read_file", { path: path.join(outside, "a.txt") });
  assert.strictEqual(r.ok, false);
  assert.ok(r.needsGrant, "should report which folder needs a grant");
  assert.ok(fs.realpathSync(outside).toLowerCase().startsWith(r.needsGrant.toLowerCase()));
  assert.ok(dir);
});

test("a sibling folder with a similar name is not treated as inside the grant", async () => {
  const dir = sandbox();
  const sibling = dir + "-evil";
  fs.mkdirSync(sibling);
  fs.writeFileSync(path.join(sibling, "x.txt"), "x");
  const r = await runTool("read_file", { path: path.join(sibling, "x.txt") });
  assert.strictEqual(r.ok, false);
  assert.ok(r.needsGrant);
});

test("dot-dot traversal cannot escape the grant", async () => {
  const dir = sandbox();
  const r = await runTool("read_file", { path: path.join(dir, "..", "..", "windows", "win.ini") });
  assert.strictEqual(r.ok, false);
});

test("symlinks cannot be used to reach outside the grant", async (t) => {
  const dir = sandbox();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "nemo-secret-"));
  fs.writeFileSync(path.join(outside, "s.txt"), "secret");
  try {
    fs.symlinkSync(outside, path.join(dir, "link"), "junction");
  } catch {
    return t.skip("cannot create links here");
  }
  const r = await runTool("read_file", { path: path.join(dir, "link", "s.txt") });
  assert.strictEqual(r.ok, false);
  assert.ok(r.needsGrant);
});

test("secret files are off limits even inside a granted folder", async () => {
  const dir = sandbox();
  fs.writeFileSync(path.join(dir, ".env"), "KEY=abc");
  assert.strictEqual((await runTool("read_file", { path: path.join(dir, ".env") })).ok, false);
  assert.strictEqual((await runTool("write_file", { path: path.join(dir, ".env"), content: "x" })).ok, false);
  const found = await runTool("search_files", { path: dir, pattern: "abc" });
  assert.strictEqual(found.result, "no matches");
});

test("nothing inside .git can be modified", async () => {
  const dir = sandbox();
  fs.mkdirSync(path.join(dir, ".git"));
  const r = await runTool("write_file", { path: path.join(dir, ".git", "hooks.sh"), content: "x" });
  assert.strictEqual(r.ok, false);
});

test("write, read, edit round trip", async () => {
  const dir = sandbox();
  const f = path.join(dir, "sub", "a.txt");
  assert.ok((await runTool("write_file", { path: f, content: "one\ntwo\nthree\n" })).ok);
  const read = await runTool("read_file", { path: f });
  assert.match(read.result, /2\ttwo/);
  assert.ok((await runTool("edit_file", { path: f, old_text: "two", new_text: "2" })).ok);
  assert.strictEqual(fs.readFileSync(f, "utf8"), "one\n2\nthree\n");
});

test("edit refuses ambiguous or missing text", async () => {
  const dir = sandbox();
  const f = path.join(dir, "a.txt");
  fs.writeFileSync(f, "dup\ndup\n");
  assert.strictEqual((await runTool("edit_file", { path: f, old_text: "dup", new_text: "x" })).ok, false);
  assert.strictEqual((await runTool("edit_file", { path: f, old_text: "nope", new_text: "x" })).ok, false);
  assert.strictEqual(fs.readFileSync(f, "utf8"), "dup\ndup\n", "failed edits change nothing");
});

test("edit works on files with Windows line endings and keeps them", async () => {
  const dir = sandbox();
  const f = path.join(dir, "w.txt");
  fs.writeFileSync(f, "a\r\nb\r\nc\r\n");
  assert.ok((await runTool("edit_file", { path: f, old_text: "a\nb", new_text: "A\nB" })).ok);
  assert.strictEqual(fs.readFileSync(f, "utf8"), "A\r\nB\r\nc\r\n");
});

test("replacement text containing $ patterns is inserted literally", async () => {
  const dir = sandbox();
  const f = path.join(dir, "d.txt");
  fs.writeFileSync(f, "price: X\n");
  await runTool("edit_file", { path: f, old_text: "X", new_text: "$& $1 $$" });
  assert.strictEqual(fs.readFileSync(f, "utf8"), "price: $& $1 $$\n");
});

test("search finds matches and skips node_modules", async () => {
  const dir = sandbox();
  fs.writeFileSync(path.join(dir, "a.js"), "const needle = 1;\n");
  fs.mkdirSync(path.join(dir, "node_modules"));
  fs.writeFileSync(path.join(dir, "node_modules", "b.js"), "needle\n");
  const r = await runTool("search_files", { path: dir, pattern: "needle" });
  assert.match(r.result, /a\.js:1/);
  assert.doesNotMatch(r.result, /node_modules/);
});

test("run_command runs in the granted folder and reports the exit code", async () => {
  const dir = sandbox();
  const r = await runTool("run_command", { command: "echo hello-nemo", cwd: dir });
  assert.ok(r.ok);
  assert.match(r.result, /exit code 0/);
  assert.match(r.result, /hello-nemo/);
  const bad = await runTool("run_command", { command: "exit 3", cwd: dir });
  assert.match(bad.result, /exit code 3/);
});

test("run_command refuses a folder that was not granted", async () => {
  sandbox();
  const other = fs.mkdtempSync(path.join(os.tmpdir(), "nemo-other-"));
  const r = await runTool("run_command", { command: "echo hi", cwd: other });
  assert.strictEqual(r.ok, false);
  assert.ok(r.needsGrant);
});

test("run_command does not leak secret-looking environment variables", async () => {
  const dir = sandbox();
  process.env.NEMO_TEST_API_KEY = "should-not-appear";
  const cmd = process.platform === "win32" ? "echo [$env:NEMO_TEST_API_KEY]" : "echo [$NEMO_TEST_API_KEY]";
  const r = await runTool("run_command", { command: cmd, cwd: dir });
  assert.doesNotMatch(r.result, /should-not-appear/);
});

test("run_command times out", async () => {
  const dir = sandbox();
  const cmd = process.platform === "win32" ? "Start-Sleep -Seconds 20" : "sleep 20";
  const r = await runTool("run_command", { command: cmd, cwd: dir, timeout_seconds: 1 });
  assert.match(r.result, /timed out/);
});

test("drives, the home folder and system folders cannot be granted", () => {
  assert.throws(() => grantFolder(path.parse(os.tmpdir()).root));
  assert.throws(() => grantFolder(os.homedir()));
  assert.throws(() => grantFolder(path.dirname(os.homedir())));
  if (process.env.SystemRoot) assert.throws(() => grantFolder(process.env.SystemRoot));
});
