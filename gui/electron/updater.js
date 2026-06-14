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
// (objects.githubusercontent.com / release-assets.githubusercontent.com) 偶爾在串流中途或
// **下載尾段**卡數十秒（連線仍在、只是沒推位元組），症狀是橫幅停在某個百分比、無進度、無錯誤。
// 故改為手動控制下載（autoDownload=false + downloadUpdate(CancellationToken)），以 watchdog
// 偵測「一段時間內無任何進度」即取消重試；連續 MAX_ATTEMPTS 次失敗才送 state:'stalled'。
//
// 重要：本下載器走整檔下載（disableDifferentialDownload=true），**無 HTTP range/續傳**——watchdog
// 取消一次＝整包（可達 122MB）從 0 重來。故 watchdog 門檻分兩段：串流途中用 STALL_MS；一旦
// 接近完成（>=NEAR_DONE_PERCENT）改用 NEAR_DONE_GRACE_MS 長寬限，避免「差最後幾 KB 卻被取消、
// 重來又卡在同一處」的惡性循環（實測：台灣本機從 GitHub 抓 122MB，尾段差 ~1.2KB 被 30s watchdog
// 取消三次，最後誤報「連不上 GitHub」）。
//
// 安全：僅在「已打包」時啟用；dev 模式呼叫 autoUpdater 會丟 "update config not found"，故直接 no-op。
// 任何更新錯誤（無網路、尚無 release、簽章等）都只回報事件、不影響主流程。

const { autoUpdater, CancellationToken } = require('electron-updater');
const fs = require('fs');
const path = require('path');

let wired = false;

// 串流途中「一段時間完全無進度」才視為停滯。30s 對 GitHub 資產 CDN 的偶發卡頓太短，放寬到 60s。
const STALL_MS = 60_000;
// 已接近完成時的寬限：無續傳，取消＝整包重來，故尾段給足等待，別為了最後幾 KB 而前功盡棄。
const NEAR_DONE_GRACE_MS = 180_000;
const NEAR_DONE_PERCENT = 90;     // 達此百分比後改用長寬限
const MAX_ATTEMPTS = 3;           // 自動重試上限（含第一次）
const RETRY_DELAY_MS = 3_000;     // 重試間隔

let sendRef = () => {};
let cancelToken = null;   // 進行中下載的取消權杖（null = 無下載進行中）
let watchdog = null;
let retryTimer = null;
let attempts = 0;
let offeredVersion = '';
let lastPercent = 0;      // 最近一次回報的下載百分比（watchdog 寬限與診斷用）
let logFile = '';         // userData/logs/updater.log；取不到路徑就只進 console

// 輕量檔案日誌：封裝後 stderr 無處可看，故把更新流程寫進固定檔案，方便事後查停滯主因。
function ulog(level, msg) {
  let stamp = '';
  try { stamp = new Date().toISOString(); } catch (_) { /* 理論上不會 */ }
  const line = `${stamp} [update] ${level} ${msg}`;
  try { if (logFile) fs.appendFileSync(logFile, line + '\n'); } catch (_) { /* 寫不進就算了 */ }
  try { (console[level] || console.log)(line); } catch (_) { /* 無 console 也算了 */ }
}

function clearTimers() {
  if (watchdog) { clearTimeout(watchdog); watchdog = null; }
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
}

// grace 未指定時依進度決定：接近完成給長寬限（重來代價=整包），其餘用 STALL_MS。
function armWatchdog(graceMs) {
  if (watchdog) clearTimeout(watchdog);
  const grace = graceMs != null
    ? graceMs
    : (lastPercent >= NEAR_DONE_PERCENT ? NEAR_DONE_GRACE_MS : STALL_MS);
  watchdog = setTimeout(onDownloadStalled, grace);
}

function startDownload() {
  attempts += 1;
  lastPercent = 0;
  cancelToken = new CancellationToken();
  ulog('info', `download attempt ${attempts}/${MAX_ATTEMPTS} for ${offeredVersion}`);
  armWatchdog(STALL_MS); // 連線/首位元組階段用基本門檻（尚無進度，lastPercent=0）
  // rejection（取消/網路錯誤）由 stall watchdog 與 'error' 事件接手，這裡僅防 unhandled。
  autoUpdater.downloadUpdate(cancelToken).catch(() => {});
}

// 停滯或下載錯誤：取消本次下載，未達上限就排程重試，否則送 'stalled' 讓使用者走瀏覽器退路。
function onDownloadStalled() {
  clearTimers();
  ulog('warn', `download stalled at ${lastPercent}% (attempt ${attempts}/${MAX_ATTEMPTS})`);
  try { if (cancelToken) cancelToken.cancel(); } catch (_) { /* 已結束的權杖：忽略 */ }
  cancelToken = null;
  if (attempts < MAX_ATTEMPTS) {
    retryTimer = setTimeout(startDownload, RETRY_DELAY_MS);
  } else {
    ulog('error', `giving up after ${MAX_ATTEMPTS} attempts; offering browser download`);
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

  // 更新日誌檔（封裝後無 stderr 可看）：userData/logs/updater.log。
  try {
    const dir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(dir, { recursive: true });
    logFile = path.join(dir, 'updater.log');
  } catch (_) { logFile = ''; }

  autoUpdater.autoDownload = false;         // 改為手動 downloadUpdate（才能掛 watchdog/重試）
  autoUpdater.autoInstallOnAppQuit = true;  // 使用者沒按「立即重啟」也會在下次離開時安裝
  autoUpdater.allowPrerelease = true;       // 通道為預發佈（rolling latest）
  // 關閉差分下載（blockmap）：electron-updater 預設會先抓 .blockmap 做區塊 diff＋ranged 請求，
  // 這段不回報 download-progress，且在 Windows/NSIS + GitHub CDN 上常卡死或極慢（症狀：橫幅
  // 停在「正在背景下載…」卻無百分比）。關掉後直接整檔下載，行為與瀏覽器一致、穩定且會持續回報進度。
  autoUpdater.disableDifferentialDownload = true;
  // electron-updater 內部日誌（解析到的下載 URL、各階段、sha512 驗證、錯誤）導進同一檔案。
  autoUpdater.logger = {
    info: (m) => ulog('info', String(m)),
    warn: (m) => ulog('warn', String(m)),
    error: (m) => ulog('error', String(m)),
    debug: () => {}, // 太吵，略過
  };

  autoUpdater.on('checking-for-update', () => send('app:update', { state: 'checking' }));
  autoUpdater.on('update-available', (info) => {
    offeredVersion = (info && info.version) || '';
    attempts = 0;
    clearTimers();
    ulog('info', `update-available: ${offeredVersion}`);
    send('app:update', { state: 'available', version: offeredVersion });
    startDownload();
  });
  autoUpdater.on('update-not-available', () => send('app:update', { state: 'none' }));
  autoUpdater.on('download-progress', (p) => {
    lastPercent = Math.round((p && p.percent) || 0);
    armWatchdog(); // 有進度＝連線活著，餵狗（接近完成時自動改用長寬限）
    send('app:update', {
      state: 'progress',
      percent: lastPercent,
      bytesPerSecond: (p && p.bytesPerSecond) || 0,
      transferred: (p && p.transferred) || 0,
      total: (p && p.total) || 0,
    });
  });
  autoUpdater.on('update-downloaded', (info) => {
    clearTimers();
    cancelToken = null;
    const v = (info && info.version) || offeredVersion;
    ulog('info', `update-downloaded: ${v}`);
    send('app:update', { state: 'downloaded', version: v });
  });
  autoUpdater.on('error', (err) => {
    const msg = err == null ? 'unknown' : String(err.message || err);
    if (/cancel/i.test(msg)) return; // watchdog 主動取消產生的錯誤：內部行為，不外漏
    ulog('error', `error event: ${msg}`);
    if (cancelToken) {
      onDownloadStalled(); // 下載階段的真錯誤（含 sha512 不符）：與停滯同路徑（重試→stalled）
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
