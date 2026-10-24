const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("nemo", {
  setInteractive: (v) => ipcRenderer.send("set-interactive", v),
  onWake: (cb) => ipcRenderer.on("wake", cb),
  // Client-side tools the agent service can ask this app to run.
  tools: {
    clipboard_read: () => ipcRenderer.invoke("clipboard:read"),
    clipboard_write: ({ text }) => ipcRenderer.invoke("clipboard:write", text),
  },
});
