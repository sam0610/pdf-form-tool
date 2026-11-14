#!/usr/bin/env python3
"""回歸測試:逐個 PDF 行「開啟 → 偵測 → 填寫 → 儲存 → 重開 → 列印」,輸出 JSON 結果。
用法: python3 tests/regress.py <corpus目錄> <輸出.json> [--mobile]
       python3 tests/regress.py --compare <基準.json> <新.json>
corpus 目錄放測試用 PDF(唔好放入 repo;公司表格唔應該公開)。"""
import asyncio, json, sys, os, time, subprocess, socket

JS_HELPERS = r"""
window.__t = {
  sig(cv, w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, w, h);
    if (cv && cv.width > 1) { g.imageSmoothingQuality = 'high'; g.drawImage(cv, 0, 0, w, h); }
    const d = g.getImageData(0, 0, w, h).data, o = []; for (let i = 0; i < d.length; i += 4) o.push(Math.round((d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000)); return o; },
  async ensure(i) { const S = window.__app, pg = S.pages[i]; if (S.api.ensureFull) { await S.api.ensureFull(i); return; }
    document.querySelector('#pages').children[i].scrollIntoView({ block: 'start' }); await new Promise((r) => setTimeout(r, 50)); },
  async idle() { const S = window.__app; for (let k = 0; k < 3000 && S.busy; k++) await new Promise((r) => setTimeout(r, 100)); },
  toB64(b) { let s = ''; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode.apply(null, b.subarray(i, i + 8192)); return btoa(s); }
};
"""

JS_LOAD = r"""async () => { const S = window.__app, t = window.__t; await t.idle();
  return { pages: S.pages.length, dims: S.pages.map((p) => [p.W, p.H, (p.wf || []).length, (p.text || []).length]),
           toast: (document.querySelector('#toast') || {}).textContent || '' }; }"""

JS_PAGES = r"""async () => { const S = window.__app, t = window.__t, n = S.pages.length, idx = [...new Set([0, Math.floor(n / 2), n - 1])], out = {};
  for (const i of idx) { await t.ensure(i); const pg = S.pages[i]; const cells = S.api.pageCells(pg, true);
    const kinds = {}; let h = 0; for (const c of cells) { kinds[c.kind] = (kinds[c.kind] || 0) + 1; h = (h * 31 + Math.round(c.x0) + 7 * Math.round(c.y0) + 13 * Math.round(c.x1) + 17 * Math.round(c.y1)) % 1000000007; }
    out[i] = { canvas: t.sig(pg.canvas, 24, 32), cells: cells.length, kinds, cellHash: h, thumb: pg.th ? t.sig(pg.th.querySelector('canvas'), 8, 10) : null }; }
  let blank = 0; S.pages.forEach((pg) => { if (!pg.th) return; const s = t.sig(pg.th.querySelector('canvas'), 6, 8); if (Math.min(...s) > 250) blank++; });
  out.blankThumbs = blank; return out; }"""

JS_DETECT = r"""async () => { const S = window.__app, t = window.__t; document.querySelector('#redetect').click(); await new Promise((r) => setTimeout(r, 300)); await t.idle();
  return S.pages.map((p) => p.fields.length); }"""

JS_FILL = r"""async () => { const S = window.__app, t = window.__t, set = [];
  const pick = (pi) => { const w = (S.pages[pi].wf || []).find((w) => w.kind === 'text' && !w.ro && w.el && !w.comb); if (w) { w.el.value = 'T' + pi; w.el.dispatchEvent(new Event('input', { bubbles: true })); set.push([w.name, 'T' + pi]); } };
  const withWf = S.pages.map((p, i) => (p.wf || []).some((w) => w.kind === 'text' && !w.ro && !w.comb) ? i : -1).filter((i) => i >= 0);
  if (withWf.length) { pick(withWf[0]); if (withWf.length > 1) pick(withWf[withWf.length - 1]); }
  const b = await S.api.buildPdf(); const d = await PDFLib.PDFDocument.load(b.slice()); const form = d.getForm();
  const vals = set.map(([n]) => { try { return form.getTextField(n).getText(); } catch (e) { return 'ERR ' + e.message; } });
  const pd = await pdfjsLib.getDocument({ data: b.slice() }).promise, sigs = [];
  for (const n of [...new Set([1, pd.numPages])]) { const p = await pd.getPage(n), vp = p.getViewport({ scale: 0.4 }), c = document.createElement('canvas'); c.width = vp.width; c.height = vp.height;
    const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); await p.render({ canvasContext: x, viewport: vp }).promise; sigs.push(t.sig(c, 24, 32)); }
  return { set, vals, outPages: d.getPageCount(), outFields: form.getFields().length, encrypted: d.isEncrypted, sigs, bytes: b.length }; }"""

JS_PRINT = r"""async () => { window.__printed = 0; window.print = () => { window.__printed++; }; const t0 = Date.now();
  document.querySelector('#print').click();
  for (let k = 0; k < 1500; k++) { await new Promise((r) => setTimeout(r, 200)); const tt = (document.querySelector('#toast') || {}).textContent || ''; if (window.__printed || /失敗/.test(tt)) return { printed: window.__printed, toast: /失敗/.test(tt) ? tt : '', pages: document.querySelectorAll('#printroot canvas, #printroot img, .printpg').length }; }
  return { printed: 0, toast: 'timeout' }; }"""

JS_MEM = r"""() => { let px = 0, full = 0; document.querySelectorAll('#pages canvas').forEach((c) => { px += c.width * c.height; if (c.width > 400) full++; });
  const S = window.__app; let gray = 0; S.pages.forEach((p) => { const g = Object.getOwnPropertyDescriptor(p, 'gray'); const v = g && 'value' in g ? g.value : p._gray; if (v) gray += v.length; });
  return { bitmapMB: Math.round(px * 4 / 1e6), grayMB: Math.round(gray / 1e6), fullCanvases: full }; }"""

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

async def run(corpus, out, mobile):
    from playwright.async_api import async_playwright
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    port = free_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(1); res = {}
    try:
        async with async_playwright() as p:
            for f in sorted(os.listdir(corpus)):
                if not f.lower().endswith('.pdf'): continue
                b = await p.chromium.launch(executable_path=os.environ.get('CHROME', '/usr/bin/google-chrome'), args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
                ctx = await b.new_context(viewport={'width': 390, 'height': 800}, has_touch=True, is_mobile=True) if mobile else await b.new_context(viewport={'width': 1400, 'height': 1000})
                pg = await ctx.new_page(); errs = []
                pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
                async def dlg(d): await d.accept('upw')
                pg.on('dialog', dlg)
                r = {}; t0 = time.time()
                try:
                    await pg.goto(f'http://127.0.0.1:{port}/index.html'); await pg.evaluate(JS_HELPERS)
                    await pg.set_input_files('input[type=file]', os.path.join(corpus, f))
                    for _ in range(600):
                        await pg.wait_for_timeout(500)
                        if await pg.evaluate('window.__app.lastLoadOk && !window.__app.busy'): break
                    r['load'] = await pg.evaluate(JS_LOAD); r['loadSecs'] = round(time.time() - t0, 1)
                    r['memAfterLoad'] = await pg.evaluate(JS_MEM)
                    r['samples'] = await pg.evaluate(JS_PAGES)
                    r['fill'] = await pg.evaluate(JS_FILL)
                    r['print'] = await pg.evaluate(JS_PRINT)
                    r['detect'] = await pg.evaluate(JS_DETECT)
                    r['memEnd'] = await pg.evaluate(JS_MEM)
                except Exception as e:
                    r['error'] = str(e)[:300]
                r['pageErrors'] = errs; r['secs'] = round(time.time() - t0, 1); res[f] = r
                print(f, 'pages', (r.get('load') or {}).get('pages'), 'secs', r['secs'], 'err', r.get('error', '')[:80], flush=True)
                await b.close()
                json.dump(res, open(out, 'w'), ensure_ascii=False)   # 逐個檔案寫入,中途停咗都有結果
    finally:
        srv.terminate()
    json.dump(res, open(out, 'w'), ensure_ascii=False)

def near(a, b, tol):
    return a is not None and b is not None and len(a) == len(b) and sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a)) <= tol

def compare(a, b):
    A, B = json.load(open(a)), json.load(open(b)); bad = 0
    def chk(ok, f, what, x='', y=''):
        nonlocal bad
        if not ok: bad += 1; print(f'  ✗ {f}: {what}  基準={str(x)[:90]}  新={str(y)[:90]}')
    for f in sorted(A):
        x, y = A[f], B.get(f)
        if y is None: chk(False, f, '新結果冇呢個檔案'); continue
        chk(x.get('error') == y.get('error'), f, 'error', x.get('error'), y.get('error'))
        chk(not y.get('pageErrors') or y.get('pageErrors') == x.get('pageErrors'), f, 'pageErrors', x.get('pageErrors'), y.get('pageErrors'))
        if 'load' in x and 'load' in y:
            n = min(x['load']['pages'], y['load']['pages'])
            chk(x['load']['dims'][:n] == y['load']['dims'][:n], f, '頁面尺寸/欄位數/文字數')
            if x['load']['pages'] != y['load']['pages']: print(f'  ℹ {f}: 頁數 {x["load"]["pages"]} → {y["load"]["pages"]}')
        for k in (x.get('samples') or {}):
            if k == 'blankThumbs': chk(y['samples'].get(k) == 0, f, '空白縮圖', x['samples'][k], y['samples'].get(k)); continue
            s, t = x['samples'][k], (y.get('samples') or {}).get(k)
            if t is None: continue
            chk(near(s['canvas'], t['canvas'], 1.0), f, f'第{int(k)+1}頁畫面')
            chk((s['cells'], s['kinds'], s['cellHash']) == (t['cells'], t['kinds'], t['cellHash']), f, f'第{int(k)+1}頁偵測格', (s['cells'], s['kinds']), (t['cells'], t['kinds']))
            chk(near(s['thumb'], t['thumb'], 12), f, f'第{int(k)+1}頁縮圖')
        if 'fill' in x and 'fill' in y:
            for key in ('set', 'vals', 'outPages', 'outFields', 'encrypted'): chk(x['fill'][key] == y['fill'][key], f, 'fill.' + key, x['fill'][key], y['fill'][key])
            chk(all(near(p, q, 1.0) for p, q in zip(x['fill']['sigs'], y['fill']['sigs'])), f, '輸出 PDF 畫面')
        if 'print' in x and 'print' in y: chk((x['print']['printed'] > 0, x['print']['toast']) == (y['print']['printed'] > 0, y['print']['toast']), f, '列印', x['print'], y['print'])
        if 'detect' in x and 'detect' in y:
            n = min(len(x['detect']), len(y['detect'])); chk(x['detect'][:n] == y['detect'][:n], f, '自動偵測欄位數', x['detect'][:n], y['detect'][:n])
        print(f'{f}: 載入 {x.get("loadSecs")}s → {y.get("loadSecs")}s;載入後位圖 {x.get("memAfterLoad", {}).get("bitmapMB")}MB → {y.get("memAfterLoad", {}).get("bitmapMB")}MB;完結時 {x.get("memEnd", {}).get("bitmapMB")}+{x.get("memEnd", {}).get("grayMB")}MB → {y.get("memEnd", {}).get("bitmapMB")}+{y.get("memEnd", {}).get("grayMB")}MB')
    print('結果:', '全部一致 ✓' if not bad else f'{bad} 項唔一致 ✗'); return bad

if __name__ == '__main__':
    if sys.argv[1] == '--compare': sys.exit(1 if compare(sys.argv[2], sys.argv[3]) else 0)
    asyncio.run(run(sys.argv[1], sys.argv[2], '--mobile' in sys.argv))
