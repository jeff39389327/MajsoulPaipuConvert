'use strict';
// main —— Electron 主程序：建立視窗、管理設定/路徑、spawn 後端、轉發事件給 renderer。

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');

const pyRunner = require('./pyRunner');
const configStore = require('./config');
const { REPO_ROOT, resolveBackend, isPackaged } = require('./pythonLocator');

let mainWindow = null;

// ---- 應用設定 (userData/gui-settings.json) -------------------------------
function settingsFile() {
  return path.join(app.getPath('userData'), 'gui-settings.json');
}

function defaultSettings() {
  return {
    repoRoot: REPO_ROOT,
    workDir: '', // 留空＝自動：dev 用 repo root，凍結版用執行檔同層的可寫資料夾 (見 defaultWorkDir)
    pythonPath: '',
    locale: '',
    downloadConcurrency: 3,
    convertConcurrency: 0, // 0 = 後端自動 (CPU 核心)
    sequentialDownload: false,
    autoDownloadAfterCrawl: true, // 收集完 ID 後自動接續 Stage 2（下載＋轉換）
  };
}

function loadSettings() {
  try {
    const raw = JSON.parse(fs.readFileSync(settingsFile(), 'utf-8'));
    return Object.assign(defaultSettings(), raw);
  } catch (_) {
    return defaultSettings();
  }
}

function saveSettings(s) {
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2), 'utf-8');
}

let settings = null;

// 挑第一個能建立且可寫的資料夾；全部失敗則回傳最後一個候選（讓後端去報實際寫入錯誤）。
function pickWritableDir(candidates) {
  for (const dir of candidates) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.accessSync(dir, fs.constants.W_OK);
      return dir;
    } catch (_) {
      /* 試下一個候選 */
    }
  }
  return candidates[candidates.length - 1];
}

// 「自動」工作目錄：dev = repo root；凍結版 = 安裝執行檔同層（使用者要求輸出與執行檔同層、
// 好找）。同層不可寫（如裝到 Program Files）才退到 文件夾 / userData。
function defaultWorkDir() {
  if (!isPackaged()) return REPO_ROOT;
  const exeDir = path.dirname(app.getPath('exe'));
  return pickWritableDir([
    exeDir,
    path.join(app.getPath('documents'), 'MajsoulPaipuGUI'),
    path.join(app.getPath('userData'), 'work'),
  ]);
}

// 解析實際工作目錄。未自訂（空字串）或仍是舊版自動預設（REPO_ROOT；凍結版即 resources 夾，
// 埋在 app 內部不好找）一律改用 defaultWorkDir()，達成「與執行檔同層」並自動遷移舊設定。
function resolveWorkDir() {
  const w = settings && settings.workDir;
  if (!w || path.resolve(w) === path.resolve(REPO_ROOT)) return defaultWorkDir();
  return w;
}

// 由設定推導出關鍵路徑。
// 凍結版的 repoRoot 位於唯讀的 process.resourcesPath 底下，crawler_config.json 與爬取
// 輸出須改放可寫的 workDir；spider/extractor 已 bundle，不依賴 inner package 目錄。
function derivePaths() {
  const repoRoot = settings.repoRoot || REPO_ROOT;
  const workDir = resolveWorkDir();
  const innerDir = isPackaged()
    ? workDir
    : path.join(repoRoot, 'paipu_project', 'paipu_project');
  return { repoRoot, workDir, innerDir };
}

// ---- 視窗 ----------------------------------------------------------------
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1040,
    height: 760,
    minWidth: 820,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

// ---- IPC -----------------------------------------------------------------
function registerIpc() {
  ipcMain.handle('app:getState', () => {
    return {
      settings,
      paths: derivePaths(),
      packaged: isPackaged(),
      systemLocale: app.getLocale(),
      backendAvailable: !!resolveBackend({ pythonPath: settings.pythonPath }),
    };
  });

  ipcMain.handle('app:setSettings', (_e, patch) => {
    settings = Object.assign({}, settings, patch || {});
    saveSettings(settings);
    return { settings, paths: derivePaths() };
  });

  ipcMain.handle('dialog:pickDir', async () => {
    const res = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
    if (res.canceled || !res.filePaths.length) return null;
    return res.filePaths[0];
  });

  ipcMain.handle('dialog:pickFile', async () => {
    const res = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'] });
    if (res.canceled || !res.filePaths.length) return null;
    return res.filePaths[0];
  });

  // 用系統檔案管理員開啟資料夾 / 於資料夾中標示某檔，方便使用者找到輸出。
  ipcMain.handle('shell:openPath', async (_e, p) => {
    if (!p) return false;
    const err = await shell.openPath(p); // 成功回空字串
    return !err;
  });

  ipcMain.handle('shell:showItem', (_e, p) => {
    if (!p) return false;
    shell.showItemInFolder(p);
    return true;
  });

  ipcMain.handle('i18n:list', () => {
    const dir = path.join(__dirname, '..', 'renderer', 'i18n');
    const locales = {};
    for (const code of ['zh-TW', 'en', 'ja']) {
      try {
        locales[code] = JSON.parse(fs.readFileSync(path.join(dir, `${code}.json`), 'utf-8'));
      } catch (_) {
        locales[code] = {};
      }
    }
    return locales;
  });

  ipcMain.handle('config:read', () => {
    const { workDir, innerDir } = derivePaths();
    return {
      env: configStore.readEnv(workDir),
      crawler: configStore.readCrawlerConfig(innerDir),
    };
  });

  ipcMain.handle('config:writeEnv', (_e, values) => {
    const { workDir, repoRoot } = derivePaths();
    return configStore.writeEnv(workDir, repoRoot, values || {});
  });

  ipcMain.handle('config:writeCrawler', (_e, cfg) => {
    const { innerDir } = derivePaths();
    return configStore.writeCrawlerConfig(innerDir, cfg || {});
  });

  ipcMain.handle('job:start', (_e, { kind, params }) => {
    const { repoRoot, workDir, innerDir } = derivePaths();
    const merged = Object.assign(
      { repo_root: repoRoot, work_dir: workDir, inner_dir: innerDir },
      params || {}
    );
    // 為下載 job 注入並發設定
    if (kind === 'download') {
      if (settings.downloadConcurrency) merged.download_concurrency = settings.downloadConcurrency;
      if (settings.convertConcurrency) merged.convert_concurrency = settings.convertConcurrency;
      merged.sequential_download = !!settings.sequentialDownload;
    }
    return pyRunner.startJob(kind, { params: merged, pythonPath: settings.pythonPath }, send);
  });

  ipcMain.handle('job:cancel', () => pyRunner.cancelJob());
}

app.whenReady().then(() => {
  settings = loadSettings();
  registerIpc();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
