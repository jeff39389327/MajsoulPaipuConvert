'use strict';
// main —— Electron 主程序：建立視窗、管理設定/路徑、spawn 後端、轉發事件給 renderer。

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');

const pyRunner = require('./pyRunner');
const configStore = require('./config');
const configIni = require('./configIni');
const updater = require('./updater');
const { REPO_ROOT, resolveBackend, isPackaged } = require('./pythonLocator');

let mainWindow = null;

// 由 electron-builder 的 publish url（.../releases/download/latest）推出人類可讀的
// releases 頁（.../releases），供「改用瀏覽器下載」退路使用。讀不到就回 GitHub 首頁式空字串。
function releasesPageUrl() {
  try {
    const pub = require('../package.json').build.publish;
    const url = (Array.isArray(pub) ? pub[0] : pub).url || '';
    return url.replace(/\/download\/[^/]*\/?$/, '').replace(/\/+$/, '');
  } catch (_) {
    return '';
  }
}

// ---- 單一設定檔 config.ini -----------------------------------------------
// primary：使用者選定的「執行檔同層」(dev 為 repo root)；mirror：userData 備援。
// 升級(NSIS)會清掉同層檔，故每次寫入同步鏡像、開機自動還原（見 configIni.js）。
let CONFIG = { primary: '', mirror: '' };

function resolveConfigPaths() {
  const mirror = path.join(app.getPath('userData'), 'config.ini');
  if (!isPackaged()) {
    return { primary: path.join(REPO_ROOT, 'config.ini'), mirror };
  }
  const exeDir = path.dirname(app.getPath('exe'));
  try {
    fs.mkdirSync(exeDir, { recursive: true });
    fs.accessSync(exeDir, fs.constants.W_OK);
    return { primary: path.join(exeDir, 'config.ini'), mirror };
  } catch (_) {
    // 同層不可寫（如裝在 Program Files）→ 直接以 userData 當 primary。
    return { primary: mirror, mirror };
  }
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
  return Object.assign(defaultSettings(), configStore.readSettings(CONFIG.primary, CONFIG.mirror));
}

function saveSettings(s) {
  configStore.writeSettings(CONFIG.primary, CONFIG.mirror, s);
}

// 首次啟動（尚無 config.ini，也無鏡像可還原）→ 把舊的 gui-settings.json / config.env /
// crawler_config.json 一次性遷入 config.ini，既有使用者不丟設定。
function migrateLegacyIfNeeded() {
  if (fs.existsSync(CONFIG.primary)) return;

  const guiSettings = configStore.readJsonSafe(path.join(app.getPath('userData'), 'gui-settings.json'));
  const legacyWorkDir = (guiSettings && guiSettings.workDir) || defaultWorkDir();
  const envText = configStore.readTextSafe(path.join(legacyWorkDir, 'config.env'))
    || configStore.readTextSafe(path.join(REPO_ROOT, 'config.env'));
  const env = envText ? configStore.parseEnvFile(envText) : {};
  const innerDir = isPackaged() ? legacyWorkDir : path.join(REPO_ROOT, 'paipu_project', 'paipu_project');
  const crawler = configStore.readJsonSafe(path.join(innerDir, 'crawler_config.json')) || {};

  // 先寫骨架（即使無任何舊檔，也確保 config.ini 成形）。
  configStore.writeSettings(CONFIG.primary, CONFIG.mirror, {});

  const ENV_KEYS = ['ms_username', 'ms_password', 'MS_RES_VERSION', 'COLLECT_TIMING', 'SAVE_DEBUG', 'SAVE_RAW_JSON'];
  const pickEnv = {};
  for (const k of ENV_KEYS) if (env[k] != null) pickEnv[k] = env[k];
  if (Object.keys(pickEnv).length) configStore.writeEnv(CONFIG.primary, CONFIG.mirror, pickEnv);

  if (crawler && Object.keys(crawler).length) {
    configStore.writeCrawler(CONFIG.primary, CONFIG.mirror, crawler);
  }
  if (guiSettings) {
    configStore.writeSettings(CONFIG.primary, CONFIG.mirror, {
      workDir: guiSettings.workDir || '',
      pythonPath: guiSettings.pythonPath || '',
      locale: guiSettings.locale || '',
      autoDownloadAfterCrawl: guiSettings.autoDownloadAfterCrawl !== false,
      downloadConcurrency: guiSettings.downloadConcurrency != null ? guiSettings.downloadConcurrency : 3,
      convertConcurrency: guiSettings.convertConcurrency != null ? guiSettings.convertConcurrency : 0,
      sequentialDownload: !!guiSettings.sequentialDownload,
    });
  }
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

// 「自動」工作目錄：dev = repo root；凍結版 = 「文件\MajsoulPaipuGUI」。
// 注意：**不可**用安裝執行檔同層（exeDir）——electron-updater(NSIS) 更新會清空安裝目錄，
// 連同 mahjong_logs / tonpuulist.txt / download_checkpoint.json 等下載產出一併刪除。
// 改用文件夾（持久、更新不影響、仍好找）；不可寫才退到 userData。
function defaultWorkDir() {
  if (!isPackaged()) return REPO_ROOT;
  return pickWritableDir([
    path.join(app.getPath('documents'), 'MajsoulPaipuGUI'),
    path.join(app.getPath('userData'), 'work'),
  ]);
}

// 舊版（≤ 此修復前）的自動工作目錄＝執行檔同層；用來把殘留資料搬到新位置。
function legacyInstallWorkDir() {
  if (!isPackaged()) return '';
  try {
    return path.dirname(app.getPath('exe'));
  } catch (_) {
    return '';
  }
}

// 一次性把舊位置（執行檔同層）殘留的下載產出搬到新的工作目錄，避免使用者升級後「看不到」舊資料、
// 或被下次更新清掉。僅在「使用預設工作目錄、舊位置確有資料、新位置尚無同名項」時搬移；rename 失敗
// （如跨磁碟）則略過不致命（新預設已能保護未來資料）。
function migrateLegacyWorkDirData() {
  if (!isPackaged()) return;
  if (settings && settings.workDir) return; // 使用者自訂過位置 → 不動
  const from = legacyInstallWorkDir();
  const to = resolveWorkDir();
  if (!from || !to || path.resolve(from) === path.resolve(to)) return;

  const ITEMS = ['mahjong_logs', 'tonpuulist.txt', 'date_room_list.txt',
    'download_checkpoint.json', 'crawler_progress.json'];
  for (const name of ITEMS) {
    const src = path.join(from, name);
    const dst = path.join(to, name);
    try {
      if (!fs.existsSync(src) || fs.existsSync(dst)) continue;
      fs.mkdirSync(to, { recursive: true });
      fs.renameSync(src, dst); // 同磁碟瞬間完成；跨磁碟會丟錯 → 由 catch 略過
    } catch (_) {
      /* 搬移失敗不致命：新位置已生效，使用者可手動搬舊檔 */
    }
  }
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
      configPath: CONFIG.primary, // 單一設定檔位置（設定頁顯示 + 可開啟）
      packaged: isPackaged(),
      appVersion: app.getVersion(),
      systemLocale: app.getLocale(),
      backendAvailable: !!resolveBackend({ pythonPath: settings.pythonPath }),
      releasesUrl: releasesPageUrl(), // 更新橫幅的「改用瀏覽器下載」退路
    };
  });

  // GUI 自動更新：手動「檢查更新」與「立即重啟安裝」。
  ipcMain.handle('update:check', () => updater.checkForUpdates());
  ipcMain.handle('update:quitAndInstall', () => updater.quitAndInstall());

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

  // 用預設瀏覽器開啟外部網址（更新橫幅的「改用瀏覽器下載」退路）。
  ipcMain.handle('shell:openExternal', (_e, url) => {
    if (!url || !/^https?:\/\//i.test(url)) return false;
    shell.openExternal(url);
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

  ipcMain.handle('config:read', () => ({
    env: configStore.readEnv(CONFIG.primary, CONFIG.mirror),
    crawler: configStore.readCrawler(CONFIG.primary, CONFIG.mirror),
  }));

  ipcMain.handle('config:writeEnv', (_e, values) =>
    configStore.writeEnv(CONFIG.primary, CONFIG.mirror, values || {}));

  ipcMain.handle('config:writeCrawler', (_e, cfg) =>
    configStore.writeCrawler(CONFIG.primary, CONFIG.mirror, cfg || {}));

  // 用系統檔案管理員開啟並標示 config.ini（設定頁的「開啟設定檔位置」按鈕）。
  ipcMain.handle('config:reveal', () => {
    if (CONFIG.primary && fs.existsSync(CONFIG.primary)) {
      shell.showItemInFolder(CONFIG.primary);
      return true;
    }
    return false;
  });

  ipcMain.handle('job:start', (_e, { kind, params }) => {
    const { repoRoot, workDir, innerDir } = derivePaths();
    const merged = Object.assign(
      {
        repo_root: repoRoot,
        work_dir: workDir,
        inner_dir: innerDir,
        config_ini_path: CONFIG.primary,   // 後端讀帳密/旗標、寫回 MS_RES_VERSION
        config_ini_mirror: CONFIG.mirror,  // 升級備援：同步寫一份到 userData
      },
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
  CONFIG = resolveConfigPaths();
  configIni.restoreFromMirror(CONFIG.primary, CONFIG.mirror); // 同層檔被升級洗掉 → 由鏡像還原
  migrateLegacyIfNeeded();                                    // 首次啟動：遷入舊設定檔
  settings = loadSettings();
  migrateLegacyWorkDirData();                                 // 把舊「執行檔同層」殘留產出搬到文件夾
  registerIpc();
  createWindow();
  // 打包版啟動後檢查更新；事件透過 send('app:update', …) 轉發給 renderer。dev 模式為 no-op。
  updater.init(app, send);
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
