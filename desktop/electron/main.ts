import { app, BrowserWindow, ipcMain } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";

const currentDirectory = __dirname;
let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcess | null = null;

function backendAlreadyRunning(): Promise<boolean> {
  return new Promise((resolve) => {
    const client = net.createConnection({ host: "127.0.0.1", port: 8000 });
    client.once("connect", () => { client.destroy(); resolve(true); });
    client.once("error", () => resolve(false));
  });
}

async function startLocalBackend(): Promise<void> {
  if (await backendAlreadyRunning()) return;
  const projectRoot = path.resolve(currentDirectory, "../..");
  const python = path.join(projectRoot, ".venv", "Scripts", "python.exe");
  if (!existsSync(python)) {
    console.warn("Cola AI backend not started: Python environment missing.");
    return;
  }
  backendProcess = spawn(python, ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: projectRoot,
    windowsHide: true,
    stdio: "ignore",
  });
  backendProcess.once("exit", (code) => console.warn("Cola AI backend exited", code));
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 520,
    minWidth: 620,
    minHeight: 400,
    resizable: true,
    alwaysOnTop: false,
    autoHideMenuBar: true,
    title: "Cola AI",
    backgroundColor: "#1d1d1d",
    webPreferences: {
      preload: path.join(currentDirectory, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const developmentUrl = process.env.VITE_DEV_SERVER_URL ?? "http://127.0.0.1:5173";
  if (process.env.NODE_ENV === "development") {
    void mainWindow.loadURL(developmentUrl);
  } else {
    void mainWindow.loadFile(path.join(currentDirectory, "../dist/index.html"));
  }

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedUrl) => {
    console.error("Renderer failed to load", { errorCode, errorDescription, validatedUrl });
  });
  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    console.log("Renderer console", { level, message, line, sourceId });
  });
}

app.whenReady().then(() => {
  ipcMain.handle("window:set-always-on-top", (_event, enabled: boolean) => {
    mainWindow?.setAlwaysOnTop(Boolean(enabled));
  });
  ipcMain.handle("app:quit", () => app.quit());
  void startLocalBackend();
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on("before-quit", () => { backendProcess?.kill(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
