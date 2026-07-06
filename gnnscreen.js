#!/usr/bin/env node
// 设置共享库路径（Puppeteer bundled Chromium 需要）
process.env.LD_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu';
try { process.env.PUPPETEER_CHROMIUM_REVISION = '150.0.7871.24'; } catch(e) {}
/**
 * GNN Search Tag Crawler + Ultra HD Scrolling Screenshot
 *
 * 爬取巴哈姆特 GNN 新闻的搜索标签页面，全网页滚动截图。
 *
 * 用法:
 *   node gnnscreen.js                  # 自动按当前季度爬取
 *   node gnnscreen.js 動畫瘋26夏       # 指定搜索标签
 *   node gnnscreen.js 動畫瘋26夏 新番  # 多个标签
 *
 * 季度自动替换:
 *   1-3月→冬 4-6月→春 7-9月→夏 10-12月→秋
 *   年份取当前年份后两位 (2026→26)
 */

let puppeteer;
try {
  puppeteer = require('puppeteer-extra');
  const StealthPlugin = require('puppeteer-extra-plugin-stealth');
  puppeteer.use(StealthPlugin());
  console.log('Using puppeteer-extra with stealth');
} catch (e) {
  puppeteer = require('puppeteer');
  console.log('Using plain puppeteer (stealth not available)');
}
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'gnn_screenshots');
const README = path.join(__dirname, 'README.md');
const MARKER_FILE = path.join(OUT, '.done_quarters'); // 记录已完成季度
const VPS = {
  desktop: { width: 1920, height: 1080, deviceScaleFactor: 2 },
  mobile:  { width: 390,  height: 844,  deviceScaleFactor: 3 },
};
const MAX = parseInt(process.env.MAX || '20');
const TIMEOUT = parseInt(process.env.TIMEOUT || '45000');

function fmtTag(d) {
  return `動畫瘋${String(d.getFullYear()).slice(-2)}${['冬','春','夏','秋'][Math.floor((d.getMonth())/3)]}`;
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
  console.log(`    ${f} (${(fs.statSync(f).size/1024/1024).toFixed(1)} MB)`);
}

const results = [];

function loadDoneQuarters() {
  try { return new Set(JSON.parse(fs.readFileSync(MARKER_FILE, 'utf8'))); } catch (e) { return new Set(); }
}
function saveDoneQuarter(tag) {
  const done = loadDoneQuarters();
  done.add(tag);
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(MARKER_FILE, JSON.stringify([...done]), 'utf8');
}

function updateReadme() {
  if (!results.length) return;
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
  const tags = [...new Set(results.map(r => r.tag))].join(', ');
  let section = `# GNN ��图记录 (${now})\n\n已完成季度: ${tags}\n\n`;
  for (const r of results) {
    section += `- [${r.tag}] ${r.title} (${r.vn}) — ${r.mb} MB  \`${r.file}\`\n`;
  }
  let readme = '';
  try { readme = fs.readFileSync(README, 'utf8'); } catch (e) { readme = ''; }
  const re = /^# GNN 截图记录[\s\S]*?(?=\n# |\n$|$)/;
  if (re.test(readme)) {
    readme = readme.replace(re, section.trimEnd());
  } else {
    readme = section + '\n\n' + readme;
  }
  fs.writeFileSync(README, readme, 'utf8');
  console.log(`\nREADME updated: ${README}`);
}

(async () => {
  console.log('=== GNN ScreenShot ===\nTags:', tags.join(', '));

  // 检查每个标签是否已经完成
  const done = loadDoneQuarters();
  const pending = tags.filter(t => !done.has(t));
  if (pending.length === 0) {
    console.log('All quarters already done, skipping.');
    return;
  }
  console.log('Pending tags:', pending.join(', '));

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
    console.log(`  URL: ${url}`);
    try {
      await p.goto(url, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });
      // 等待页面内容加载（避开 Cloudflare challenge）
      await p.waitForSelector('a.GNNG-libit2, .GNNG-libit, #search-result, .article-list', { timeout: 15000 }).catch(() => {});
      await p.evaluate(() => new Promise(r => setTimeout(r, 1000)));
    } catch (e) { console.error('  nav error:', e.message); }
    
    // 检查是否被 Cloudflare 拦截
    const pageTitle = await p.title().catch(() => '');
    const bodyText = await p.evaluate(() => document.body?.innerText?.slice(0, 200) || '').catch(() => '');
    if (bodyText.includes('challenge') || pageTitle.toLowerCase().includes('just a moment')) {
      console.error('  BLOCKED by Cloudflare challenge');
      // 截图保存 CF 拦截页面
      await p.screenshot({ path: path.join(OUT, tag, 'cf_blocked.png'), fullPage: false }).catch(() => {});
    }
    console.log(`  Title: ${pageTitle.slice(0, 80)}`);
    console.log(`  Body start: ${bodyText.slice(0, 100)}`);

    let articles = [];
    try {
      articles = await p.evaluate(() =>
        Array.from(document.querySelectorAll('a.GNNG-libit2'), a => ({ title: a.textContent.trim(), href: a.href }))
      );
    } catch (e) { console.error('  parse error:', e.message); continue; }
    console.log(`  ${articles.length} articles`);

    for (const a of articles.slice(0, MAX)) {
      console.log(`\n--- ${a.title} ---`);
      for (const [vn, vp] of Object.entries(VPS)) await shot(p, a, tag, vn, vp);
    }
  }
  await b.close();
  // 标记已完成并更新 README
  if (results.length > 0) {
    for (const tag of pending) saveDoneQuarter(tag);
    updateReadme();
  } else {
    console.log("No screenshots taken, will retry next run.");
  }
  console.log(`\n=== Done in ${((Date.now()-t0)/60000).toFixed(1)} min ===`);
})().catch(e => { console.error(e); process.exit(1); });
