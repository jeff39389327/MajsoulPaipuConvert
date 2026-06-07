'use strict';
// preload —— 透過 contextBridge 暴露受限、安全的 API 給 renderer。

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  // 狀態與設定
  getState: () => ipcRenderer.invoke('app:getState'),
  setSettings: (patch) => ipcRenderer.invoke('app:setSettings', patch),
  pickDir: () => ipcRenderer.invoke('dialog:pickDir'),
  pickFile: () => ipcRenderer.invoke('dialog:pickFile'),

  // i18n 語系資料
  loadLocales: () => ipcRenderer.invoke('i18n:list'),

  // 設定檔讀寫 (config.env / crawler_config.json)
  readConfig: () => ipcRenderer.invoke('config:read'),
  writeEnv: (values) => ipcRenderer.invoke('config:writeEnv', values),
  writeCrawler: (cfg) => ipcRenderer.invoke('config:writeCrawler', cfg),

  // job 控制
  startJob: (kind, params, dryRun) => ipcRenderer.invoke('job:start', { kind, params, dryRun }),
  cancelJob: () => ipcRenderer.invoke('job:cancel'),

  // 事件訂閱 (回傳取消訂閱函式)
  onEvent: (cb) => {
    const fn = (_e, payload) => cb(payload);
    ipcRenderer.on('py:event', fn);
    return () => ipcRenderer.removeListener('py:event', fn);
  },
  onStderr: (cb) => {
    const fn = (_e, payload) => cb(payload);
    ipcRenderer.on('py:stderr', fn);
    return () => ipcRenderer.removeListener('py:stderr', fn);
  },
  onRaw: (cb) => {
    const fn = (_e, payload) => cb(payload);
    ipcRenderer.on('py:raw', fn);
    return () => ipcRenderer.removeListener('py:raw', fn);
  },
  onExit: (cb) => {
    const fn = (_e, payload) => cb(payload);
    ipcRenderer.on('py:exit', fn);
    return () => ipcRenderer.removeListener('py:exit', fn);
  },
});
