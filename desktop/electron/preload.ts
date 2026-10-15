import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("cola", {
  desktop: {
    setAlwaysOnTop: (enabled: boolean): Promise<void> => ipcRenderer.invoke("window:set-always-on-top", enabled),
    quit: (): Promise<void> => ipcRenderer.invoke("app:quit"),
  },
});
