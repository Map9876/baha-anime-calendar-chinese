#!/usr/bin/env node
process.env.LD_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu';
/**
 * GNN Search Tag Crawler + Ultra HD Scrolling Screenshot
 * 截图结果写入 README.md 顶部 # 标签
 *
 * 用法:
 *   node gnnscreen.js                  # 自动当前季度
 *   node gnnscreen.js 動畫瘋26夏        # 指定标签
 *   node gnnscreen.js 動畫瘋26夏 新番   # ��标签
 */
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'gnn_screenshots');
const README = path.join(__dirname, 'README.md');
const VPS = {
  desktop: { width: 1920, height: 1080, deviceScaleFactor: 2 },
  mobile:  { width: 390,  height: 844,  deviceScaleFactor: 3 },
};
const MAX = parseInt(process.env.MAX || '20');
const TIMEOUT = parseInt(process.env.TIMEOUT || '45000');

const results = []; // { tag, title, file, vn }

function fmtTag(d) {
  return `動畫瘋${String(d.getFullYear()).slice(-2)}${['冬','春','夏','秋'][Math.floor(d.getMonth()/3)]}`;
}

let tags = process.argv.slice(2);
if (!tags.length) tags = [fmtTag(new Date()), '新番'];

async function shot(page, art, tag, vn, vp) {
  console.log(`  [${vn}] ${art.title}`);
  await page.setViewport(vp);
  try { await page.goto(art.href, { waitUntil: 'networkidle0', timeout: TIMEOUT }); }
  catch (e) { console.error('    nav error:', e.message); return; }
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
  const mb = (fs.statSync(f).size / 1024 / 1024).toFixed(1);
  console.log(`    ${f} (${mb} MB)`);
  results.push({ tag, title: art.title, vn, file: path.relative(__dirname, f), mb });
}

function updateReadme() {
  if (!results.length) return;
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
  let section = `# GNN 截图记录 (${now})\n\n`;
  for (const r of results) {
    section += `- [${r.tag}] ${r.title} (${r.vn}) — ${r.mb} MB  \`${r.file}\`\n`;
  }
  let readme = '';
  try { readme = fs.readFileSync(README, 'utf8'); } catch (e) { readme = ''; }
  // 替换已有的 # GNN 截图记录 区块，或插入到顶部
  const re = /^# GNN 截图记录[\s\S]*?(?=\n# |\n$|$)/;
  if (re.test(readme)) {
    readme = readme.replace(re, section.trimEnd());
  } else {
    readme = section + '\n' + readme;
  }
  fs.writeFileSync(README, readme, 'utf8');
  console.log(`\nREADME updated: ${README}`);
}

(async () => {
  console.log('=== GNN ScreenShot ===\nTags:', tags.join(', '));
  const b = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'],
  });
  const p = await b.newPage();
  await p.setExtraHTTPHeaders({ 'Accept-Language': 'zh-TW,zh;q=0.9;en;q=0.7' });
  await p.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36');
  await p.evaluateOnNewDocument(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
  const t0 = Date.now();
  for (const tag of tags) {
    console.log(`\n====== ${tag} ======`);
    const url = `https://gnn.gamer.com.tw/search_tag.php?q=${encodeURIComponent(tag)}`;
    try { await p.goto(url, { waitUntil: 'networkidle0', timeout: TIMEOUT }); }
    catch (e) { console.error('  nav error:', e.message); continue; }
    let articles = [];
    try { articles = await p.evaluate(() => Array.from(document.querySelectorAll('a.GNNG-libit2'), a => ({ title: a.textContent.trim(), href: a.href }))); }
    catch (e) { console.error('  parse error:', e.message); continue; }
    console.log(`  ${articles.length} articles`);
    for (const a of articles.slice(0, MAX)) {
      console.log(`\n--- ${a.title} ---`);
      for (const [vn, vp] of Object.entries(VPS)) await shot(p, a, tag, vn, vp);
    }
  }
  await b.close();
  updateReadme();
  console.log(`\n=== Done in ${((Date.now()-t0)/60000).toFixed(1)} min ===`);
})().catch(e => { console.error(e); process.exit(1); });
