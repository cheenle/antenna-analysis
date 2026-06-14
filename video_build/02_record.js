// 真实录屏 /antenna 看板 — 按 timing.json 每段配音时长驱动页面动作
// 关键：每段动作就绪、解说即将开始的瞬间打时间戳，写出 marks.json
// 合成时按真实时间戳精确放置每段配音，彻底消除声画漂移
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const URL = 'http://radio.vlsc.net:5000/antenna';
const timing = JSON.parse(fs.readFileSync(path.join(DIR, 'timing.json'), 'utf8'));
const board = JSON.parse(fs.readFileSync(path.join(DIR, 'storyboard.json'), 'utf8'));
const segById = Object.fromEntries(board.segments.map(s => [s.id, s]));

const W = 1280, H = 800;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 平滑滚动到某 canvas 所在卡片
async function scrollToCanvas(page, canvasId) {
  await page.evaluate((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const card = el.closest('.card') || el;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, canvasId);
}

// 等待所有图表加载完成（refresh 显示 🟢）
async function waitReady(page, ms = 30000) {
  await page.waitForFunction(() => {
    const r = document.getElementById('refresh');
    return r && r.textContent.includes('🟢');
  }, { timeout: ms }).catch(() => {});
}

async function run() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 2,
    recordVideo: { dir: path.join(DIR, 'raw_video'), size: { width: W, height: H } },
  });
  const page = await context.newPage();

  const t0 = Date.now();           // 视频起点（约等于录制开始）
  const marks = [];                // 每段：{id, start, dur} —— start 为相对 t0 的秒数
  const mark = () => (Date.now() - t0) / 1000;

  console.log('opening', URL);
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
  await waitReady(page, 45000);
  await sleep(1500);

  for (const t of timing) {
    const seg = segById[t.id];
    const action = seg.action || '';
    const holdSec = seg.hold_sec || 0;

    // 执行该段对应的页面动作（动作耗时不计入解说，打点在动作之后）
    if (t.id === '06_lobe_intro') {
      // 第5段切到15m后，这里切回全波段恢复完整数据
      await page.click('#btn-band-all').catch(() => {});
      await waitReady(page, 20000);
    }

    if (action === 'load_top') {
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
      await sleep(700);
    } else if (action.startsWith('scroll_to:') || action.startsWith('hold:')) {
      await scrollToCanvas(page, action.split(':')[1]);
      await sleep(700);
    } else if (action === 'hover_polar_peak') {
      await scrollToCanvas(page, 'polarCanvas');
      await sleep(800);
      const box = await page.locator('#polarCanvas').boundingBox();
      if (box) {
        const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
        const R = box.width / 2 - 20;
        const az = 95, el = 9, elMax = 60;
        const rr = R * (1 - el / elMax);
        const a = (az - 90) * Math.PI / 180;
        await page.mouse.move(cx + rr * Math.cos(a), cy + rr * Math.sin(a), { steps: 20 });
      }
    } else if (action.startsWith('switch_band:')) {
      const band = action.split(':')[1];
      await scrollToCanvas(page, 'polarCanvas');
      await sleep(600);
      await page.click(`#btn-band-${band}`).catch(() => {});
      await waitReady(page, 20000);
    }

    // —— 动作已就绪，解说从此刻开始 —— 打点
    const start = mark();
    marks.push({ id: t.id, start: +start.toFixed(3), dur: t.duration });
    console.log(`[${t.id}] ${action}  start=${start.toFixed(1)}s  narr=${t.duration}s`);

    // 停留 = 配音时长 + hold 缓冲
    await sleep((t.duration + holdSec) * 1000);
  }

  const tEnd = mark();
  await sleep(500);
  await context.close();
  await browser.close();

  const files = fs.readdirSync(path.join(DIR, 'raw_video')).filter(f => f.endsWith('.webm'));
  const webm = files.map(f => ({ f, m: fs.statSync(path.join(DIR, 'raw_video', f)).mtimeMs }))
                    .sort((a, b) => b.m - a.m)[0]?.f;
  fs.writeFileSync(path.join(DIR, 'marks.json'),
    JSON.stringify({ video_end: +tEnd.toFixed(3), webm, marks }, null, 2));
  console.log('video files:', files.join(', '));
  console.log('marks written, video_end=', tEnd.toFixed(1), 's');
}

run().catch(e => { console.error(e); process.exit(1); });
