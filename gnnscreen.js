#!/usr/bin/env node
process.env.LD_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu';
/**
 * GNN Search Tag Crawler + Ultra HD Scrolling Screenshot
 * 使用 FlareSolverr 绕过 Cloudflare，Puppeteer 截图.
 *
 * 用法:
 *   node gnnscreen.js                  # 自动当前季度
 *   node gnnscreen.js 動畫瘋26夏        # 指定标签
 */
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const FS_URL = process.env.FLARESOLVERR_URL || 'http://localhost:8191/v1';
const OUT = path.join(__dirname, 'gnn_screenshots');
const README = path.join(__dirname, 'README.md');
const MARKER = path.join(OUT, '.done_quarters');
const VPS = {
  desktop: { width: 1920, height: 1080, deviceScaleFactor: 2 },
  mobile:  { width: 390,  height: 844,  deviceScaleFactor: 3 },
};
const MAX = parseInt(process.env.MAX || '20');
const TIMEOUT = 60000;
const results = [];

function fmtTag(d) {
  return `動畫瘋${String(d.getFullYear()).slice(-2)}${['冬','春','夏','秋'][Math.floor(d.getMonth()/3)]}`;
}
function loadDone() { try { return new Set(JSON.parse(fs.readFileSync(MARKER,'utf8'))); } catch(e) { return new Set(); } }
function saveDone(tag) { const d = loadDone(); d.add(tag); fs.mkdirSync(OUT,{recursive:true}); fs.writeFileSync(MARKER,JSON.stringify([...d]),'utf8'); }

function updateReadme() {
  if (!results.length) return;
  const now = new Date().toISOString().slice(0,19).replace('T',' ');
  const tags = [...new Set(results.map(r=>r.tag))].join(', ');
  let sec = `# GNN 截图记录 (${now})\n\n已完成季度: ${tags}\n\n`;
  for (const r of results) sec += `- [${r.tag}] ${r.title} (${r.vn}) — ${r.mb} MB  \`${r.file}\`\n`;
  let rm = '';
  try { rm = fs.readFileSync(README,'utf8'); } catch(e) { rm = ''; }
  const re = /^# GNN 截图记录[\s\S]*?(?=\n# |\n$|$)/;
  if (re.test(rm)) rm = rm.replace(re, sec.trimEnd());
  else rm = sec + '\n\n' + rm;
  fs.writeFileSync(README, rm, 'utf8');
  console.log(`README updated`);
}

// 通过 FlareSolverr 获取页面 HTML
async function flareFetch(url) {
  const resp = await fetch(FS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cmd: 'request.get', url, maxTimeout: TIMEOUT }),
  });
  const data = await resp.json();
  if (data.status !== 'ok') throw new Error(data.message);
  return data.solution.response;
}

async function shot(page, html, art, tag, vn, vp) {
  console.log(`  [${vn}] ${art.title}`);
  await page.setViewport(vp);
  await page.setContent(html, { waitUntil: 'networkidle0', timeout: TIMEOUT }).catch(() => {});
  await page.evaluate(() => new Promise(r => setTimeout(r, 2000)));
  await page.evaluate(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    for (let y = 0; y < document.body.scrollHeight; y += 400) { window.scrollTo(0, y); await w(120); }
    window.scrollTo(0, 0); await w(300);
  });
  const n = art.title.replace(/[/\\?%*:|"<>]/g, '_').slice(0, 80);
  const d = path.join(OUT, tag, vn);
  fs.mkdirSync(d, { recursive: true });
  const f = `${d}/${n}.png`;
  await page.screenshot({ path: f, fullPage: true, type: 'png' });
  const mb = (fs.statSync(f).size/1024/1024).toFixed(1);
  console.log(`    ${f} (${mb} MB)`);
  results.push({ tag, title: art.title, vn, file: path.relative(__dirname, f), mb });
}

(async () => {
  console.log('=== GNN ScreenShot ===\nTags:', process.argv.slice(2).join(', '));
  const tags = process.argv.slice(2).length ? process.argv.slice(2) : [fmtTag(new Date()), '新番'];
  const done = loadDone();
  const pending = tags.filter(t => !done.has(t));
  if (!pending.length) { console.log('All quarters done, skipping.'); return; }
  console.log('Pending:', pending.join(', '));

  // FlareSolverr test
  try {
    const resp = await fetch(FS_URL, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd:'request.get',url:'https://www.google.com',maxTimeout:15000}) });
    const d = await resp.json();
    if (d.status !== 'ok') throw new Error(d.message);
    console.log('FlareSolverr: OK');
  } catch(e) { console.error('FlareSolverr unavailable:', e.message); process.exit(1); }

  // 用 FlareSolverr 获取 GNN 搜索页
  for (const tag of pending) {
    console.log(`\n====== ${tag} ======`);
    const url = `https://gnn.gamer.com.tw/search_tag.php?q=${encodeURIComponent(tag)}`;
    let html;
    try { html = await flareFetch(url); }
    catch(e) { console.error('  FlareSolverr error:', e.message); continue; }
    // 解析文章列表
    const articles = [];
    const reLink = /<a[^>]+href="([^"]+)"[^>]*class="GNNG-libit2"[^>]*>([\s\S]*?)<\/a>/g;
    let m;
    while ((m = reLink.exec(html)) !== null) {
      const title = m[2].replace(/<[^>]+>/g, '').trim();
      let href = m[1];
      if (href.startsWith('//')) href = 'https:' + href;
      else if (href.startsWith('/')) href = 'https://gnn.gamer.com.tw' + href;
      if (title) articles.push({ title, href });
    }
    console.log(`  ${articles.length} articles`);

    // 启动 Chromium（仅用于截图）
    console.log('  Launching Chromium for screenshots...');
    const b = await puppeteer.launch({ headless: true, args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'] });
    const p = await b.newPage();
    await p.setExtraHTTPHeaders({ 'Accept-Language': 'zh-TW,zh;q=0.9;en;q=0.7' });
    await p.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36');

    for (const a of articles.slice(0, MAX)) {
      console.log(`\n--- ${a.title} ---`);
      let articleHtml;
      try { articleHtml = await flareFetch(a.href); }
      catch(e) { console.error('  FlareSolverr article error:', e.message); continue; }
      for (const [vn, vp] of Object.entries(VPS)) await shot(p, articleHtml, a, tag, vn, vp);
    }
    await b.close();
  }

  if (results.length > 0) {
    for (const tag of pending) saveDone(tag);
    updateReadme();
  } else {
    console.log('No screenshots taken, will retry.');
  }
  console.log(`\n=== Done in ${((Date.now()-Date.now())/60000).toFixed(1)} min ===`);
})().catch(e => { console.error('Fatal:', e); process.exit(1); });
