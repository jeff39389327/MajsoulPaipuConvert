'use strict';
// updater —— GUI 全自動更新（electron-updater）。
//
// 通道設計：沿用既有 CI 的 rolling「latest」預發佈版（.github/workflows/release.yml）。
// 為避開 electron-updater 的 GitHub provider 以「tag 名稱當版本」解析（我們的 tag 固定叫
// "latest"，非 semver，會解析失敗），改用 **generic provider** 指向固定的 release 下載 URL：
//   https://github.com/<owner>/<repo>/releases/download/latest
// electron-builder 打包時把此 URL 寫進 latest.yml；electron-updater 只需抓 {url}/latest.yml，
// 以其中的 version 欄位（CI 每次建置遞增）與本機版本比對，較新就下載 {url}/<安裝檔>。
// 版本比較看 latest.yml 的 version（非 tag），故 rolling「latest」tag 完全相容。
//
// 下載卡死防護：electron-updater 對「連線悶死」沒有逾時——GitHub 資產域名
// (objects.githubusercontent.com) 在部分網路環境對非瀏覽器流量極慢或直接黑洞，症狀是
// 橫幅永遠停在「正在背景下載…」且無進度、無錯誤。故改為手動控制下載
// （autoDownload=false + downloadUpdate(CancellationToken)），以 watchdog 偵測
// 「STALL_MS 內無任何進度」即取消重試；連續 MAX_ATTEMPTS 次失敗改送 state:'stalled'，
// 由 renderer 顯著提示改用瀏覽器下載（關差分下載仍保留，見下）。
//
// 安全：僅在「已打包」時啟用；dev 模式呼叫 autoUpdater 會丟 "update config not found"，故直接 no-op。
// 任何更新錯誤（無網路、尚無 release、簽章等）都只回報事件、不影響主流程。

const { autoUpdater, CancellationToken } = require('electron-updater');

let wired = false;

const STALL_MS = 30_000;      // 無任何下載進度視為停滯的門檻
const MAX_ATTEMPTS = 3;       // 自動重試上限（含第一次）
const RETRY_DELAY_MS = 3_000; // 重試間隔

let sendRef = () => {};
let cancelToken = null;   // 進行中下載的取消權杖（null = 無下載進行中）
let watchdog = null;
let retryTimer = null;
let attempts = 0;
let offeredVersion = '';

function clearTimers() {
  if (watchdog) { clearTimeout(watchdog); watchdog = null; }
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
}

function armWatchdog() {
  if (watchdog) clearTimeout(watchdog);
  watchdog = setTimeout(onDownloadStalled, STALL_MS);
}

function startDownload() {
  attempts += 1;
  cancelToken = new CancellationToken();
  armWatchdog();
  // rejection（取消/網路錯誤）由 stall watchdog 與 'error' 事件接手，這裡僅防 unhandled。
  autoUpdater.downloadUpdate(cancelToken).catch(() => {});
}

// 停滯或下載錯誤：取消本次下載，未達上限就排程重試，否則送 'stalled' 讓使用者走瀏覽器退路。
function onDownloadStalled() {
  clearTimers();
  try { if (cancelToken) cancelToken.cancel(); } catch (_) { /* 已結束的權杖：忽略 */ }
  cancelToken = null;
  if (attempts < MAX_ATTEMPTS) {
    retryTimer = setTimeout(startDownload, RETRY_DELAY_MS);
  } else {
    sendRef('app:update', { state: 'stalled', version: offeredVersion });
  }
}

// 把更新狀態統一成一個事件送往 renderer：{ state, ... }
//   checking | available | none | progress | downloaded | stalled | error
function init(app, send) {
  if (!app.isPackaged) return; // dev：無更新設定，避免拋錯
  if (wired) return;
  wired = true;
  sendRef = send;

  autoUpdater.autoDownload = false;         // 改為手動 downloadUpdate（才能掛 watchdog/重試）
  autoUpdater.autoInstallOnAppQuit = true;  // 使用者沒按「立即重啟」也會在下次離開時安裝
  autoUpdater.allowPrerelease = true;       // 通道為預發佈（rolling latest）
  // 關閉差分下載（blockmap）：electron-updater 預設會先抓 .blockmap 做區塊 diff＋ranged 請求，
  // 這段不回報 download-progress，且在 Windows/NSIS + GitHub CDN 上常卡死或極慢（症狀：橫幅
  // 停在「正在背景下載…」卻無百分比）。關掉後直接整檔下載，行為與瀏覽器一致、穩定且會持續回報進度。
  autoUpdater.disableDifferentialDownload = true;
  // electron-updater 內建 logger 介面相容 console；保留預設即可（log 進 stderr）。

  autoUpdater.on('checking-for-update', () => send('app:update', { state: 'checking' }));
  autoUpdater.on('update-available', (info) => {
    offeredVersion = (info && info.version) || '';
    attempts = 0;
    clearTimers();
    send('app:update', { state: 'available', version: offeredVersion });
    startDownload();
  });
  autoUpdater.on('update-not-available', () => send('app:update', { state: 'none' }));
  autoUpdater.on('download-progress', (p) => {
    armWatchdog(); // 有進度＝連線活著，餵狗
    send('app:update', {
      state: 'progress',
      percent: Math.round((p && p.percent) || 0),
      bytesPerSecond: (p && p.bytesPerSecond) || 0,
      transferred: (p && p.transferred) || 0,
      total: (p && p.total) || 0,
    });
  });
  autoUpdater.on('update-downloaded', (info) => {
    clearTimers();
    cancelToken = null;
    send('app:update', { state: 'downloaded', version: (info && info.version) || offeredVersion });
  });
  autoUpdater.on('error', (err) => {
    const msg = err == null ? 'unknown' : String(err.message || err);
    if (/cancel/i.test(msg)) return; // watchdog 主動取消產生的錯誤：內部行為，不外漏
    if (cancelToken) {
      onDownloadStalled(); // 下載階段的真錯誤：與停滯同路徑（重試→stalled）
      return;
    }
    send('app:update', { state: 'error', message: msg }); // 檢查階段錯誤（無網路/尚無 release）：靜默記錄
  });

  // 啟動後檢查一次（失敗已由 error 事件處理，這裡再吞一次避免 unhandled rejection）。
  checkForUpdates();
}

function checkForUpdates() {
  try {
    autoUpdater.checkForUpdates().catch((err) => {
      // checkForUpdates 的 rejection 與上面的 'error' 事件可能重複；此處僅防止 unhandled。
      void err;
    });
  } catch (_) {
    /* dev 或設定缺失：忽略 */
  }
}

// 由 renderer 的「立即重啟並更新」觸發。isSilent=false 顯示安裝程式進度、isForceRunAfter=true 安裝後自動開啟。
function quitAndInstall() {
  try {
    autoUpdater.quitAndInstall(false, true);
  } catch (_) {
    /* 尚未下載完成等情況：忽略 */
  }
}

module.exports = { init, checkForUpdates, quitAndInstall };
