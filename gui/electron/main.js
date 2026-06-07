'use strict';
// main —— Electron 主程序：建立視窗、管理設定/路徑、spawn 後端、轉發事件給 renderer。

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
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
    workDir: REPO_ROOT, // dev 預設等於 repo root；凍結版由使用者選
    pythonPath: '',
    locale: '',
    downloadConcurrency: 3,
    convertConcurrency: 0, // 0 = 後端自動 (CPU 核心)
    sequentialDownload: false,
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

// 由設定推導出關鍵路徑。
// 凍結版的 repoRoot 位於唯讀的 process.resourcesPath 底下，crawler_config.json 與爬取
// 輸出須改放使用者選定、可寫的 workDir；spider/extractor 已 bundle，不依賴 inner package 目錄。
function derivePaths() {
  const repoRoot = settings.repoRoot || REPO_ROOT;
  const workDir = settings.workDir || repoRoot;
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

  ipcMain.handle('job:start', (_e, { kind, params, dryRun }) => {
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
    return pyRunner.startJob(kind, { params: merged, dryRun, pythonPath: settings.pythonPath }, send);
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
