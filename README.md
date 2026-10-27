# PDF 填表轉換(PWA)

PDF 填表、加文字/圖案/簽名/圖章、掃描檔轉可填表單、分割/壓縮/批量填寫。全部喺瀏覽器本機運行,PDF 唔會上載。

目前版本 v3.16.0

## 部署(GitHub Pages)
1. Repo → Settings → Pages → Source 揀 `Deploy from a branch`,Branch 揀 `main` / `(root)`,Save。
2. 約一至兩分鐘後,網址係 `https://<帳戶>.github.io/pdf-form-tool/`。

## 安裝成程式
- Chrome / Edge:網址列右邊「安裝」圖示;安裝後離線都開到。
- 安裝後可喺 PDF 檔案「開啟方式」揀「PDF填表」(Chrome / Edge)。
- 「儲存」(Ctrl+S)可直接覆蓋原檔(Chrome / Edge);其他瀏覽器改為下載。

## 檔案
- `index.html`:整個程式(單檔)
- `lib/`:pdf.js、pdf-lib、JSZip、SheetJS(本機版,供離線使用)
- `sw.js`:Service Worker(離線快取;改版時請同步更新 `CACHE` 版本字串)
- `manifest.webmanifest`、`icons/`:PWA 設定

## 更新版本
改完 `index.html` 後,將 `sw.js` 內 `CACHE` 版本字串改新,推上 `main`。已安裝嘅用戶重開一至兩次就會見到新版。
