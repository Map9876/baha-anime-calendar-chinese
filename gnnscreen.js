#!/usr/bin/env node
process.env.LD_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu';
/**
 * GNN Search Tag Crawler + Ultra HD Scrolling Screenshot
 * 使用 FlareSolverr 绕过 Cloudflare，Puppeteer 截图.
 *
 * 用法:
 *   node gnnscreen.js                        # 自动当前季度
 *   node gnnscreen.js 動畫瘋26夏              # 指定标签
 *   DEBUG=1 node gnnscreen.js                # 详细日志
 */
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const FS_URL = process.env.FLARESOLVERR_URL || 'http://localhost:8191/v1';
const OUT = path.join(__dirname, 'gnn_screenshots');
const README = path.join(__dirname, 'README.md');
const MARKER = path.join(OUT, '.done_quarters');
const DEBUG = process.env.DEBUG || '0';
const VPS = {
  desktop: { width: 1920, height: 1080, deviceScaleFactor: 2 },
  mobile:  { width: 390,  height: 844,  deviceScaleFactor: 3 },
};
const MAX = parseInt(process.env.MAX || '20');
const TIMEOUT = 60000;
const results = [];
let debugIdx = 0;

function log(msg) { console.log(`[${new Date().toISOString().slice(11,19)}] ${msg}`); }
function debug(msg) { if (DEBUG !== '0') console.log(`  🔍 ${msg}`); }

function fmtTag(d) {
  return `動畫瘋${String(d.getFullYear()).slice(-2)}${['冬','春','夏','秋'][Math.floor(d.getMonth()/3)]}`;
}
function loadDone() { try { return new Set(JSON.parse(fs.readFileSync(MARKER,'utf8'))); } catch(e) { return new Set(); } }
function saveDone(tag) { const d = loadDone(); d.add(tag); fs.mkdirSync(OUT,{recursive:true}); fs.writeFileSync(MARKER,JSON.stringify([...d]),'utf8'); }

function updateReadme() {
  if (!results.length) {
    log('⚠️ 没有截图结果，跳过 README 更新');
    return;
  }
  const now = new Date().toISOString().slice(0,19).replace('T',' ');
  const tags = [...new Set(results.map(r=>r.tag))].join(', ');
  let sec = `# GNN 截图记录 (${now})\n\n已完成季度: ${tags}\n\n`;
  
  // 去重：只显示一次，季度tag优先
  const seen = new Set();
  for (const r of results) {
    if (r.vn === 'mobile' && !seen.has(r.title)) {
      seen.add(r.title);
    }
  }
  for (const r of results) {
    if (r.vn === 'mobile' && seen.has(r.title)) {
      // URL编码路径
      const imgPath = r.file.split("/").map(p => encodeURIComponent(p)).join("/");
      sec += `![${r.tag}](${imgPath})
`;
      sec += `- ${r.title} — ${r.mb} MB\n\n`;
      seen.delete(r.title);
    }
  }
  
  let rm = '';
  try { rm = fs.readFileSync(README,'utf8'); } catch(e) { rm = ''; }
  
  // 用 indexOf 替换 GNN 截图记录章节（比正则更鲁棒）
  const idx = rm.indexOf('# GNN 截图记录');
  if (idx >= 0) {
    const next = rm.indexOf('\n# ', idx + 1);
    if (next > idx) {
      rm = rm.slice(0, idx) + sec.trimEnd() + rm.slice(next);
    } else {
      rm = rm.slice(0, idx) + sec.trimEnd();
    }
  } else {
    rm = sec + '\n\n' + rm;
  }
  fs.writeFileSync(README, rm, 'utf8');
  log(`✅ README 已更新 (${results.length} 张截图)`);
}

// FlareSolverr 获取页面
async function flareFetch(url, label) {
  debug(`[${label}] 请求 FlareSolverr: ${url}`);
  const resp = await fetch(FS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cmd: 'request.get', url, maxTimeout: TIMEOUT }),
  });
  const data = await resp.json();
  debug(`[${label}] FlareSolverr 响应 status=${data.status} message=${data.message || 'ok'}`);
  if (data.status !== 'ok') throw new Error(`FlareSolverr: ${data.message}`);
  
  const html = data.solution.response;
  debug(`[${label}] HTML 长度: ${html.length} 字节`);
  
  // ��存调试 HTML
  if (DEBUG !== '0') {
    const debugDir = path.join(OUT, '_debug');
    fs.mkdirSync(debugDir, { recursive: true });
    const f = path.join(debugDir, `${label}_${debugIdx++}.html`);
    fs.writeFileSync(f, html, 'utf8');
    debug(`[${label}] HTML 已保存到 ${f}`);
  }
  
  // Cloudflare 检测
  const cfSignals = [
    { key: 'challenge', desc: '包含 challenge' },
    { key: 'cf-browser-verification', desc: 'CF 浏览器验证' },
    { key: 'just a moment', desc: '等待中' },
    { key: 'Attention Required', desc: '需要验证' },
    { key: 'Cloudflare', desc: 'Cloudflare 页面' },
    { key: '__cf_chl', desc: 'CF challenge 参数' },
    { key: 'cf_chl_opt', desc: 'CF 优化参数' },
    { key: '403 Forbidden', desc: '403 禁止' },
    { key: 'access denied', desc: '访问被拒绝' },
  ];
  const htmlLower = html.toLowerCase();
  for (const s of cfSignals) {
    if (htmlLower.includes(s.key)) {
      log(`  ⚠️  [${label}] Cloudflare 拦截: ${s.desc}`);
    }
  }
  
  // HTML 头部预览
  const headMatch = html.match(/<title>([^<]*)<\/title>/i);
  if (headMatch) debug(`[${label}] <title>: ${headMatch[1].slice(0, 100)}`);
  
  return html;
}

async function shot(page, html, art, tag, vn, vp) {
  log(`  [${vn}] ${art.title}`);
  await page.setViewport(vp);
  // 注入 CSS 隐藏评论区等无关内容
  const cleanHtml = html.replace('</head>', `<style>
#forum, .forum, .c_msg, .c留言, .comment, #comment, .comment-list, .BH-footer,
div[id*="comment" i], div[class*="comment" i],
div[id*="forum" i], div[class*="forum" i],
section[id*="comment" i], section[class*="comment" i],
.BH-menu, .sidenav, .fixed-right, .member-service,
.event-prj, .bh-banner, .footer__wrap, .footer__copyright,
div[class*="ad-"], div[id*="ad-"],
iframe, .gsc-search-box
{ display:none !important; }
/* 强制中文字体 */
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&display=swap" rel="stylesheet">
<style>
* { font-family:'Noto Sans SC','Noto Sans CJK SC','Noto Sans CJK','Source Han Sans SC','Microsoft YaHei','PingFang SC',sans-serif !important; }
</style>
/* 让正文区域全宽 */
.GN-lbox2B, .GN-lbox2D, .GN-lbox2C { max-width:none !important; }
</style></head>`);
  debug(`[${vn}] 设置 HTML 内容 (${cleanHtml.length} 字节)`);
  await page.setContent(cleanHtml, { waitUntil: 'networkidle0', timeout: TIMEOUT }).catch(e => {
    log(`  ⚠️ setContent 超时/错误: ${e.message}`);
  });
  debug(`[${vn}] ��待渲染`);
  // 等待中文字体加载
  try { await page.evaluate(() => document.fonts.ready); } catch(e) {}
  await page.evaluate(() => new Promise(r => setTimeout(r, 2000)));
  debug(`[${vn}] 滚动触发懒加载`);
  await page.evaluate(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    for (let y = 0; y < document.body.scrollHeight; y += 400) { window.scrollTo(0, y); await w(120); }
    window.scrollTo(0, 0); await w(300);
  });
  const n = art.title.replace(/[/\\?%*:|"<>]/g, '_').slice(0, 80);
  const d = path.join(OUT, tag, vn);
  fs.mkdirSync(d, { recursive: true });
  const f = `${d}/${n}.png`;
  debug(`[${vn}] 截图保存到 ${f}`);
  await page.screenshot({ path: f, fullPage: true, type: 'png' });
  const mb = (fs.statSync(f).size/1024/1024).toFixed(1);
  log(`    ✅ ${f} (${mb} MB)`);
  results.push({ tag, title: art.title, vn, file: path.relative(__dirname, f), mb });
}

(async () => {
  log('=== GNN ScreenShot 开始 ===');
  log(`FlareSolverr: ${FS_URL}`);
  log(`调试模式: ${DEBUG !== '0' ? '开启' : '��闭'}`);
  
  const tags = process.argv.slice(2).length ? process.argv.slice(2) : [fmtTag(new Date())];
  log(`搜索标签: ${tags.join(', ')}`);
  
  const done = loadDone();
  const pending = tags.filter(t => !done.has(t));
  log(`已完成季度: ${[...done].join(', ') || '(无)'}`);
  log(`待处理: ${pending.join(', ') || '(无)'}`);
  if (!pending.length) { log('所有季度已完成，跳过'); return; }

  // 测试 FlareSolverr 连通性
  log('测试 FlareSolverr...');
  try {
    const testUrl = 'https://www.google.com';
    const resp = await fetch(FS_URL, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cmd:'request.get', url:testUrl, maxTimeout:15000})
    });
    const d = await resp.json();
    debug(`FlareSolverr 测试响应: status=${d.status}, message=${d.message || 'ok'}`);
    if (d.status !== 'ok') throw new Error(`FlareSolverr 测试失败: ${d.message}`);
    const testHtml = d.solution?.response || '';
    log(`FlareSolverr 测试: OK (${testHtml.length} 字节)`);
  } catch(e) {
    log(`❌ FlareSolverr 不可用: ${e.message}`);
    process.exit(1);
  }

  // ��理每个标签
  for (const tag of pending) {
    log(`\n====== 标签: ${tag} ======`);
    const url = `https://gnn.gamer.com.tw/search_tag.php?q=${encodeURIComponent(tag)}`;
    log(`目标 URL: ${url}`);
    
    let html;
    try {
      html = await flareFetch(url, `search_${tag}`);
    } catch(e) {
      log(`❌ FlareSolverr 获取失败: ${e.message}`);
      continue;
    }
    
    // HTML 基础检测
    log(`HTML 大小: ${(html.length / 1024).toFixed(1)} KB`);
    if (html.length < 500) {
      log(`⚠️ HTML 太小 (${html.length} 字节)，可能是错误页面:`);
      log(`   ${html.slice(0, 300)}`);
    }
    
    // 解析文章列表
    log('解析文章列表...');
    const articles = [];
    
    // 方法1: GN-lbox2D 内的文章链接 (GNN 正确结构)
    const re1 = /<h1 class="GN-lbox2D"[^>]*>\s*<a href="(\/\/gnn\.gamer\.com\.tw\/detail\.php\?sn=\d+)"[^>]*>([\s\S]*?)<\/a>\s*<\/h1>/gi;
    let m1;
    while ((m1 = re1.exec(html)) !== null) {
      const title = m1[2].replace(/<[^>]+>/g, '').trim();
      const href = 'https:' + m1[1];
      if (title) articles.push({ title, href, method: 'GN-lbox2D' });
    }
    log(`  方法1 (GN-lbox2D): ${articles.filter(a => a.method === 'GN-lbox2D').length} 个`);
    
    // 方法2: 任意 detail.php?sn= 链接 (协议相对)
    const re2 = /<a[^>]+href="(?:https:)?(?:\/\/gnn\.gamer\.com\.tw)?\/detail\.php\?sn=\d+"[^>]*>([\s\S]*?)<\/a>/gi;
    let m2;
    while ((m2 = re2.exec(html)) !== null) {
      const title = m2[1].replace(/<[^>]+>/g, '').trim();
      const hrefMatch = m2[0].match(/href="([^"]+)"/);
      if (!hrefMatch || !title) continue;
      let href = hrefMatch[1];
      if (href.startsWith('//')) href = 'https:' + href;
      if (!articles.find(a => a.href === href)) {
        articles.push({ title, href, method: 'detail.php' });
      }
    }
    log(`  方法2 (detail.php): ${articles.filter(a => a.method === 'detail.php').length} 个`);
    log(`  去重后总数: ${articles.length}`);    
    if (articles.length === 0) {
      log('⚠️ 没有找到任何文章，尝试保存调试信息');
      // 保存一份原始 HTML 的预览
      const preview = html.slice(0, 3000);
      debug(`HTML 预览:\n${preview}`);
      
      // 检查页面中可能的链接模式
      const linkPatterns = html.match(/<a[^>]*href="[^"]*"[^>]*>([\s\S]{0,50})<\/a>/g);
      if (linkPatterns) {
        log(`页面中链接数: ${linkPatterns.length}`);
        debug(`前 5 个链接:\n${linkPatterns.slice(0, 5).join('\n')}`);
      }
      continue;
    }
    
    // 显示找到的文章
    log(`找到 ${articles.length} 篇文章`);
    for (const a of articles.slice(0, 5)) {
      log(`  📄 [${a.method}] ${a.title.slice(0, 60)}`);
      debug(`     URL: ${a.href}`);
    }
    if (articles.length > 5) log(`  ... 还有 ${articles.length - 5} 篇`);

    // 启动 Chromium 截图
    log('启动 Chromium 用于截图...');
    const b = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],
    });
    const p = await b.newPage();
    await p.setExtraHTTPHeaders({ 'Accept-Language': 'zh-TW,zh;q=0.9;en;q=0.7' });
    await p.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36');
    log('Chromium 就绪');

    for (const a of articles.slice(0, MAX)) {
      log(`\n--- ${a.title.slice(0, 60)} ---`);
      log(`URL: ${a.href}`);
      let articleHtml;
      try {
        articleHtml = await flareFetch(a.href, `article_${a.title.slice(0, 20)}`);
        log(`文章 HTML: ${(articleHtml.length / 1024).toFixed(1)} KB`);
      } catch(e) {
        log(`❌ FlareSolverr 获取文章失败: ${e.message}`);
        continue;
      }
      // 过滤：只有正文含播出时间 (xx:xx) 的季度时间表才要
      const hasTime = /\b\d{1,2}:\d{2}\b/.test(articleHtml);
      if (!hasTime) {
        log(`  \u23ed 过滤掉: ${a.title.slice(0, 50)}（无播出时间）`);
        continue;
      }
      // 保存文章正文到 txt 文件
      const txtTagDir = path.join(OUT, tag);
      fs.mkdirSync(txtTagDir, { recursive: true });
      const txt = articleHtml.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
      fs.writeFileSync(path.join(txtTagDir, 'article.txt'), txt, 'utf8');
      log(`  正文已保存: ${txtTagDir}/article.txt`);
      for (const [vn, vp] of Object.entries(VPS)) {
        await shot(p, articleHtml, a, tag, vn, vp);
      }
    }
    await b.close();
    log('Chromium 已关闭');
  }

  if (results.length > 0) {
    log(`截图成功: ${results.length} 张`);
    for (const tag of pending) saveDone(tag);
    updateReadme();
  } else {
    log('❌ 没有产生截图，下次重试');
  }
  log(`\n=== 完成 (耗时 ${((Date.now()-Date.now())/60000).toFixed(1)} 分钟) ===`);
})().catch(e => { console.error('❌ 致命错误:', e); process.exit(1); });
