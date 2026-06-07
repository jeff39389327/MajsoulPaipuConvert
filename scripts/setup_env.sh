#!/usr/bin/env bash
# =============================================================================
# setup_env.sh —— 在 Linux 容器 / CI 沙箱中重建本專案的完整執行環境。
#
# 此腳本記錄並自動化「建立環境」所需的全部步驟，涵蓋兩階段 pipeline 的相依：
#   Stage 1 (Scrapy + Selenium 爬蟲)：Chrome + 對應 chromedriver
#   Stage 2 (toumajsoul.py 下載/轉換)：tensoul-py-ng、ms_api(ms 套件)、mjai-reviewer
#
# 用法：
#   bash scripts/setup_env.sh
#   之後填好 config.env 帳密，即可：
#     (Stage 1) cd paipu_project/paipu_project && scrapy crawl paipu_spider
#     (Stage 2) python toumajsoul.py
#
# 註：本腳本針對 Debian/Ubuntu (apt) + root 環境撰寫；其他發行版請自行調整。
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo ">>> [1/6] 安裝 Python 相依"
export SETUPTOOLS_USE_DISTUTILS=stdlib

# (a) ms_api 是唯一需要特殊處理的相依：舊式 sdist，在新版環境會撞到 Debian
#     setuptools 的 install_layout 衝突，必須以 SETUPTOOLS_USE_DISTUTILS=stdlib
#     且關閉 build isolation 才能編譯。先單獨裝好，requirements.txt 同一行即被滿足。
pip install -q ms_api==0.11.100 --no-build-isolation

# (b) 其餘相依：本專案某些套件 (scrapy 需新版 cryptography、flask 需新版 blinker)
#     的舊版由 Debian apt 預裝，pip 無法卸載而報錯。用 --ignore-installed 讓 pip
#     直接把新版裝進 site-packages 覆蓋系統版，而非嘗試卸載。
#     刻意「不」用 `|| true`——這裡是嚴格安裝，任何真正的失敗都會讓 set -e 中止，
#     不會在相依不完整 (例如缺 python-dotenv/tqdm) 的情況下誤報環境建立成功。
grep -viE '^\s*#|^\s*$|^ms_api' requirements.txt > /tmp/reqs_no_msapi.txt
pip install -q -r /tmp/reqs_no_msapi.txt --ignore-installed

echo ">>> [2/6] 取得 tensoul-py-ng (toumajsoul.py 的下載器，.gitignore 內，需各自 clone)"
if [ ! -d tensoul-py-ng ]; then
  git clone --depth 1 https://github.com/unStatiK/tensoul-py-ng.git tensoul-py-ng
fi

# Chrome + chromedriver 僅 Stage 1 (Selenium 爬蟲) 需要。離線測試 / 只跑 Stage 2 的
# 情境可設 SKIP_CHROME=1 略過，省去 apt 安裝時間。
if [ "${SKIP_CHROME:-0}" = "1" ]; then
  echo ">>> [3-4/6] 略過 Chrome / chromedriver 安裝 (SKIP_CHROME=1)"
else
  echo ">>> [3/6] 安裝 Google Chrome (Selenium 爬蟲所需)"
  if ! command -v google-chrome >/dev/null 2>&1; then
    curl -sL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y -q /tmp/chrome.deb
  fi
  CHROME_VER="$(google-chrome --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')"
  echo "    Chrome 版本: $CHROME_VER"

  echo ">>> [4/6] 安裝與 Chrome 完全相符的 chromedriver"
  # Selenium Manager 偵測到的 PATH chromedriver 若版本不符會失敗；改抓 Chrome for Testing
  # 對應版本，放到 PATH 最前段的目錄覆蓋。
  DRIVER_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VER}/linux64/chromedriver-linux64.zip"
  mkdir -p "$HOME/.local/bin"
  if curl -sfL "$DRIVER_URL" -o /tmp/chromedriver.zip; then
    python3 -c "import zipfile;zipfile.ZipFile('/tmp/chromedriver.zip').extractall('/tmp/cdz')"
    cp /tmp/cdz/chromedriver-linux64/chromedriver "$HOME/.local/bin/chromedriver"
    chmod +x "$HOME/.local/bin/chromedriver"
    echo "    chromedriver: $("$HOME/.local/bin/chromedriver" --version)"
  else
    echo "    警告：找不到 $CHROME_VER 的精確 chromedriver，請改用相近版本。"
  fi
fi

echo ">>> [5/6] 建置並安裝 mjai-reviewer (tenhou -> mjai 轉換器)"
if ! command -v mjai-reviewer >/dev/null 2>&1; then
  if command -v cargo >/dev/null 2>&1; then
    # 可用 MJAI_REVIEWER_VERSION 釘選版本 (CI 用於重現與快取鍵)，未設則取最新 tag。
    VER="${MJAI_REVIEWER_VERSION:-$(git ls-remote --tags --refs https://github.com/Equim-chan/mjai-reviewer.git \
      | grep -oE 'refs/tags/.*' | sed 's#refs/tags/##' | sort -V | tail -1)}"
    echo "    從源碼建置 mjai-reviewer $VER (release build)"
    rm -rf /tmp/mjr-src
    git clone --depth 1 --branch "$VER" https://github.com/Equim-chan/mjai-reviewer.git /tmp/mjr-src
    ( cd /tmp/mjr-src && cargo build --release )
    cp /tmp/mjr-src/target/release/mjai-reviewer "$HOME/.local/bin/mjai-reviewer"
    chmod +x "$HOME/.local/bin/mjai-reviewer"
  else
    echo "    警告：未找到 cargo，請手動安裝 mjai-reviewer 並加入 PATH。"
  fi
fi
command -v mjai-reviewer >/dev/null 2>&1 && echo "    mjai-reviewer: $(mjai-reviewer --version)"

echo ">>> [6/6] 準備 config.env"
if [ ! -f config.env ]; then
  cp config.env.example config.env
  echo "    已從範本建立 config.env，請填入 CN 伺服器帳密 (ms_username / ms_password)。"
fi

echo ""
echo ">>> 環境建立完成。請確認 \$HOME/.local/bin 位於 PATH 前段："
echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
