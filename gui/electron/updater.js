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
// 安全：僅在「已打包」時啟用；dev 模式呼叫 autoUpdater 會丟 "update config not found"，故直接 no-op。
// 任何更新錯誤（無網路、尚無 release、簽章等）都只回報事件、不影響主流程。

const { autoUpdater } = require('electron-updater');

let wired = false;

// 把更新狀態統一成一個事件送往 renderer：{ state, ... }
//   checking | available | none | progress | downloaded | error
function init(app, send) {
  if (!app.isPackaged) return; // dev：無更新設定，避免拋錯
  if (wired) return;
  wired = true;

  autoUpdater.autoDownload = true;          // 偵測到新版即自動下載
  autoUpdater.autoInstallOnAppQuit = true;  // 使用者沒按「立即重啟」也會在下次離開時安裝
  autoUpdater.allowPrerelease = true;       // 通道為預發佈（rolling latest）
  // electron-updater 內建 logger 介面相容 console；保留預設即可（log 進 stderr）。

  autoUpdater.on('checking-for-update', () => send('app:update', { state: 'checking' }));
  autoUpdater.on('update-available', (info) =>
    send('app:update', { state: 'available', version: info && info.version }));
  autoUpdater.on('update-not-available', () => send('app:update', { state: 'none' }));
  autoUpdater.on('download-progress', (p) =>
    send('app:update', { state: 'progress', percent: Math.round((p && p.percent) || 0) }));
  autoUpdater.on('update-downloaded', (info) =>
    send('app:update', { state: 'downloaded', version: info && info.version }));
  autoUpdater.on('error', (err) =>
    send('app:update', { state: 'error', message: err == null ? 'unknown' : String(err.message || err) }));

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
