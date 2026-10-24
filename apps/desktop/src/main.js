const { app, BrowserWindow, screen, ipcMain, globalShortcut, clipboard } = require("electron");
const path = require("path");

let win;

function createWindow() {
  const { x, y, width, height } = screen.getPrimaryDisplay().workArea;
  win = new BrowserWindow({
    x,
    y,
    width,
    height,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  // Click-through everywhere except on the robot; the renderer toggles this.
  win.setIgnoreMouseEvents(true, { forward: true });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

ipcMain.on("set-interactive", (_e, interactive) => {
  if (!win) return;
  win.setIgnoreMouseEvents(!interactive, { forward: true });
  if (interactive) win.focus();
});
ipcMain.handle("clipboard:read", () => clipboard.readText());
ipcMain.handle("clipboard:write", (_e, text) => {
  clipboard.writeText(String(text));
  return "ok";
});

app.whenReady().then(() => {
  createWindow();
  // Summon the robot from anywhere.
  globalShortcut.register("CommandOrControl+Shift+Space", () => {
    if (win) win.webContents.send("wake");
  });
});
app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => app.quit());
