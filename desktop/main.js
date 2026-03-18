/**
 * CryptoMind — Electron main process.
 *
 * Dev mode:   npm run desktop   → starts backend + Vite dev server, loads localhost:3000
 * Prod mode:  open CryptoMind.app → starts backend, loads built frontend from file://
 */

const { app, BrowserWindow, shell, dialog } = require("electron");
const { spawn, execSync } = require("child_process");
const path = require("path");
const http = require("http");
const fs = require("fs");

// Suppress EPIPE errors (happen when writing to closed pipe on process exit)
process.stdout.on("error", () => {});
process.stderr.on("error", () => {});

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const APP_NAME = "CryptoMind";
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3700;
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`;
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`;

const BACKEND_TIMEOUT_MS = 60000;
const FRONTEND_TIMEOUT_MS = 30000;
const POLL_INTERVAL_MS = 800;
const STALE_PORTS = [3700]; // only our port — don't kill other projects

const IS_DEV = !app.isPackaged;

// ---------------------------------------------------------------------------
// Paths — different in dev vs production
//
// Dev:
//   PROJECT_ROOT = btc-paper-trader/
//   run_api.py   = btc-paper-trader/run_api.py
//   frontend     = btc-paper-trader/frontend/ (Vite dev server)
//
// Prod (inside .app bundle):
//   RESOURCES    = CryptoMind.app/Contents/Resources/
//   run_api.py   = RESOURCES/run_api.py
//   app/*.py     = RESOURCES/app/
//   frontend     = RESOURCES/frontend/index.html (static build)
//   data/        = RESOURCES/data/
// ---------------------------------------------------------------------------

const RESOURCES = IS_DEV
  ? path.resolve(__dirname, "..")
  : process.resourcesPath;

const BACKEND_SCRIPT = path.join(RESOURCES, "run_api.py");
const BACKEND_CWD = RESOURCES;

const FRONTEND_DIR = path.join(RESOURCES, "frontend");
const FRONTEND_INDEX = path.join(FRONTEND_DIR, "index.html");

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

function log(msg) {
  const ts = new Date().toLocaleTimeString();
  console.log(`[CryptoMind ${ts}] ${msg}`);
}

function logErr(msg) {
  const ts = new Date().toLocaleTimeString();
  console.error(`[CryptoMind ${ts}] ERROR: ${msg}`);
}

// ---------------------------------------------------------------------------
// Process management
// ---------------------------------------------------------------------------

let backendProcess = null;
let frontendProcess = null;
let mainWindow = null;

function clearPort(port) {
  try {
    const pids = execSync(`lsof -ti:${port}`, { encoding: "utf-8" }).trim();
    if (pids) {
      log(`Clearing port ${port} (PIDs: ${pids.replace(/\n/g, ", ")})`);
      execSync(`lsof -ti:${port} | xargs kill -9`, { stdio: "ignore" });
      execSync("sleep 1", { stdio: "ignore" });
    }
  } catch {
    // port is free
  }
}

function findPython() {
  for (const cmd of ["python3", "/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"]) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { encoding: "utf-8" }).trim();
      log(`Found Python: ${cmd} → ${ver}`);
      return cmd;
    } catch { /* next */ }
  }
  logErr("No python3 found!");
  return "python3";
}

function startBackend() {
  const python = findPython();

  log(`Starting backend: ${python} ${BACKEND_SCRIPT}`);
  log(`  CWD: ${BACKEND_CWD}`);

  // Verify the script exists
  if (!fs.existsSync(BACKEND_SCRIPT)) {
    logErr(`Backend script not found: ${BACKEND_SCRIPT}`);
    throw new Error(`run_api.py not found at ${BACKEND_SCRIPT}`);
  }

  updateStatus("Starting backend...");

  backendProcess = spawn(python, [BACKEND_SCRIPT], {
    cwd: BACKEND_CWD,
    env: {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.on("data", (d) => console.log(`  [backend] ${d.toString().trim()}`));
  backendProcess.stderr.on("data", (d) => console.log(`  [backend] ${d.toString().trim()}`));
  backendProcess.on("error", (e) => logErr(`Backend spawn failed: ${e.message}`));
  backendProcess.on("close", (code) => { log(`Backend exited: ${code}`); backendProcess = null; });
}

function startFrontendDev() {
  const frontendSrc = IS_DEV ? path.join(RESOURCES, "frontend") : null;
  if (!frontendSrc) return;

  log(`Starting Vite dev server in ${frontendSrc}`);
  updateStatus("Starting frontend...");

  frontendProcess = spawn("npm", ["run", "dev"], {
    cwd: frontendSrc,
    env: { ...process.env },
    stdio: ["ignore", "pipe", "pipe"],
    shell: true,
  });

  frontendProcess.stdout.on("data", (d) => console.log(`  [frontend] ${d.toString().trim()}`));
  frontendProcess.stderr.on("data", (d) => console.log(`  [frontend] ${d.toString().trim()}`));
  frontendProcess.on("error", (e) => logErr(`Frontend spawn failed: ${e.message}`));
  frontendProcess.on("close", (code) => { log(`Frontend exited: ${code}`); frontendProcess = null; });
}

// ---------------------------------------------------------------------------
// Loading screen communication
// ---------------------------------------------------------------------------

function updateStatus(text) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const s = text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  mainWindow.webContents.executeJavaScript(`
    try {
      document.getElementById("status").innerHTML = "${s}<span class='dots'></span>";
      document.getElementById("spinner").style.display = "block";
      document.getElementById("retry-btn").style.display = "none";
      document.getElementById("error-detail").style.display = "none";
    } catch(e) {}
  `).catch(() => {});
}

function showError(text) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const s = text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  mainWindow.webContents.executeJavaScript(`
    try {
      document.getElementById("status").textContent = "Startup failed";
      document.getElementById("spinner").style.display = "none";
      document.getElementById("error-detail").style.display = "block";
      document.getElementById("error-detail").textContent = "${s}";
      document.getElementById("retry-btn").style.display = "inline-block";
      document.getElementById("hint").style.display = "block";
    } catch(e) {}
  `).catch(() => {});
}

// ---------------------------------------------------------------------------
// Health polling
// ---------------------------------------------------------------------------

function waitForService(url, label, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    let attempts = 0;

    function check() {
      const elapsed = Date.now() - start;
      attempts++;

      if (elapsed > timeoutMs) {
        logErr(`${label} timeout after ${attempts} attempts (${(elapsed / 1000).toFixed(1)}s)`);
        return reject(new Error(`${label} did not start within ${Math.round(timeoutMs / 1000)}s`));
      }

      if (attempts % 5 === 1) {
        log(`Waiting for ${label}... (attempt ${attempts}, ${(elapsed / 1000).toFixed(1)}s)`);
        updateStatus(`Waiting for ${label.toLowerCase()}...`);
      }

      const req = http.get(url, { timeout: 3000 }, (res) => {
        res.resume();
        if (res.statusCode >= 200 && res.statusCode < 400) {
          log(`${label} ready (${attempts} attempts, ${(elapsed / 1000).toFixed(1)}s) [HTTP ${res.statusCode}]`);
          resolve();
        } else {
          setTimeout(check, POLL_INTERVAL_MS);
        }
      });
      req.on("error", () => setTimeout(check, POLL_INTERVAL_MS));
      req.on("timeout", () => { req.destroy(); setTimeout(check, POLL_INTERVAL_MS); });
    }

    check();
  });
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    title: APP_NAME,
    backgroundColor: "#0f1117",
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, "loading.html"));
  mainWindow.show();

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => { mainWindow = null; });
}

async function loadApp() {
  log("=== CryptoMind startup ===");
  log(`Mode: ${IS_DEV ? "DEVELOPMENT" : "PRODUCTION"}`);
  log(`Resources: ${RESOURCES}`);
  log(`Backend script: ${BACKEND_SCRIPT} (exists: ${fs.existsSync(BACKEND_SCRIPT)})`);
  log(`Frontend dir: ${FRONTEND_DIR} (exists: ${fs.existsSync(FRONTEND_DIR)})`);
  if (!IS_DEV) log(`Frontend index: ${FRONTEND_INDEX} (exists: ${fs.existsSync(FRONTEND_INDEX)})`);

  try {
    // Step 0: Clear ports
    log("Step 0: Clearing ports...");
    updateStatus("Preparing...");
    clearPort(BACKEND_PORT);
    for (const port of STALE_PORTS) clearPort(port);

    // Step 1: Start backend
    log("Step 1: Starting backend...");
    startBackend();

    // Step 2: Start frontend dev server (dev only)
    if (IS_DEV) {
      log("Step 2: Starting frontend dev server...");
      startFrontendDev();
    }

    // Step 3: Wait for backend
    log("Step 3: Waiting for backend health...");
    updateStatus("Waiting for backend...");
    await waitForService(HEALTH_URL, "Backend", BACKEND_TIMEOUT_MS);

    // Step 4: Wait for frontend (dev only)
    if (IS_DEV) {
      log("Step 4: Waiting for frontend dev server...");
      updateStatus("Waiting for frontend...");
      await waitForService(FRONTEND_URL, "Frontend", FRONTEND_TIMEOUT_MS);
    }

    // Step 5: Load the dashboard
    //
    // Dev mode:  load from Vite dev server (localhost:3000)
    // Prod mode: load from backend (localhost:8000) which serves the built
    //            frontend via FastAPI static file mount — no file:// needed,
    //            no CORS issues, API calls work naturally.
    log("Step 5: Loading dashboard...");
    if (!mainWindow || mainWindow.isDestroyed()) return;

    const dashboardURL = IS_DEV ? FRONTEND_URL : `http://localhost:${BACKEND_PORT}`;
    log(`Loading from: ${dashboardURL}`);
    await mainWindow.loadURL(dashboardURL);

    // Auto-login for desktop app — no manual login needed
    if (!IS_DEV) {
      log("Auto-login as admin...");
      await mainWindow.webContents.executeJavaScript(`
        (async () => {
          try {
            // Check if already logged in
            if (localStorage.getItem("token")) return "already_logged_in";

            const res = await fetch("http://localhost:${BACKEND_PORT}/login", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ username: "admin", password: "changeme" })
            });
            if (res.ok) {
              const data = await res.json();
              localStorage.setItem("token", data.access_token);
              location.reload();
              return "logged_in";
            }
            return "login_failed";
          } catch(e) { return "error:" + e.message; }
        })()
      `).then(r => log(`Auto-login result: ${r}`)).catch(e => log(`Auto-login error: ${e}`));
    }

    log("Dashboard loaded successfully!");

  } catch (err) {
    logErr(`Startup failed: ${err.message}`);
    showError(err.message);
  }
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.setName(APP_NAME);

app.whenReady().then(() => {
  createWindow();
  loadApp();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) { createWindow(); loadApp(); }
  });
});

app.on("window-all-closed", () => {
  cleanup();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", cleanup);

function cleanup() {
  log("Cleaning up...");
  if (backendProcess && !backendProcess.killed) {
    try { backendProcess.kill("SIGTERM"); } catch { /* */ }
    backendProcess = null;
  }
  if (frontendProcess && !frontendProcess.killed) {
    try { frontendProcess.kill("SIGTERM"); } catch { /* */ }
    frontendProcess = null;
  }
  try { execSync(`lsof -ti:${BACKEND_PORT} | xargs kill -9 2>/dev/null`, { stdio: "ignore" }); } catch { /* */ }
  for (const port of STALE_PORTS) {
    try { execSync(`lsof -ti:${port} | xargs kill -9 2>/dev/null`, { stdio: "ignore" }); } catch { /* */ }
  }
  log("Cleanup done");
}
