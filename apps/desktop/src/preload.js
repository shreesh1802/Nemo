const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("nemo", {
  setInteractive: (v) => ipcRenderer.send("set-interactive", v),
  onWake: (cb) => ipcRenderer.on("wake", cb),
  // File and shell tools; access rules are enforced in the main process.
  runTool: (name, args) => ipcRenderer.invoke("tool:run", name, args),
  grantFolder: (folder) => ipcRenderer.invoke("tool:grant", folder),
  // Client-side tools the agent service can ask this app to run.
  tools: {
    clipboard_read: () => ipcRenderer.invoke("clipboard:read"),
    clipboard_write: ({ text }) => ipcRenderer.invoke("clipboard:write", text),
  },
});
