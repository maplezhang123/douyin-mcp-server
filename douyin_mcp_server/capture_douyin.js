const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const sourceUrl = process.env.DOUYIN_CAPTURE_URL || '';
const audioPath = process.env.DOUYIN_AUDIO_PATH || '';
const downloadAudio = process.env.DOUYIN_DOWNLOAD_AUDIO === '1';

function result(value) {
  process.stdout.write(`DOUYIN_CAPTURE_JSON=${JSON.stringify(value)}\n`);
}

function videoId(text) {
  const match = String(text || '').match(/(?:\/video\/|modal_id=|aweme_id=|item_ids=)(\d{16,22})/)
    || String(text || '').match(/\b(\d{16,22})\b/);
  return match ? match[1] : '';
}

function contentRangeTotal(headers) {
  const match = String(headers['content-range'] || '').match(/\/(\d+)$/);
  return match ? Number(match[1]) : 0;
}

async function downloadByRanges(request, url, destination) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const chunkSize = 4 * 1024 * 1024;
  let start = 0;
  let total = 0;
  const handle = fs.openSync(destination, 'w');
  try {
    while (!total || start < total) {
      const end = total ? Math.min(start + chunkSize - 1, total - 1) : start + chunkSize - 1;
      const response = await request.get(url, {
        headers: { Range: `bytes=${start}-${end}`, Referer: 'https://www.douyin.com/' },
        timeout: 60000,
      });
      if (!response.ok() && response.status() !== 206) {
        throw new Error(`audio request failed: HTTP ${response.status()}`);
      }
      const headers = response.headers();
      const body = await response.body();
      const range = String(headers['content-range'] || '').match(/bytes\s+(\d+)-(\d+)\/(\d+)/i);
      if (response.status() === 200) {
        fs.writeSync(handle, body, 0, body.length, 0);
        return body.length;
      }
      if (!range) {
        throw new Error('partial audio response has no Content-Range');
      }
      const responseStart = Number(range[1]);
      const responseEnd = Number(range[2]);
      total = Number(range[3]);
      if (responseStart !== start || body.length !== responseEnd - responseStart + 1) {
        throw new Error(`unexpected audio range ${range[0]} (${body.length} bytes)`);
      }
      fs.writeSync(handle, body, 0, body.length, responseStart);
      start = responseEnd + 1;
    }
  } finally {
    fs.closeSync(handle);
  }
  const size = fs.statSync(destination).size;
  if (total && size !== total) {
    throw new Error(`audio size mismatch: expected ${total}, got ${size}`);
  }
  return size;
}

(async () => {
  if (!sourceUrl) {
    result({ ok: false, error: 'DOUYIN_CAPTURE_URL is empty' });
    process.exitCode = 2;
    return;
  }

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      locale: 'zh-CN',
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    const candidates = [];

    page.on('response', async (response) => {
      try {
        const headers = response.headers();
        const type = String(headers['content-type'] || '').toLowerCase();
        const url = response.url();
        if (type.startsWith('audio/') || /media-audio|\.m4a(?:\?|$)|\.mp3(?:\?|$)/i.test(url)) {
          candidates.push({ url, total: contentRangeTotal(headers), type });
        }
      } catch (_) {
        // One failed response inspection must not stop page capture.
      }
    });

    await page.goto(sourceUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(6000);
    await page.locator('video').first().evaluate((element) => {
      element.muted = true;
      return element.play().catch(() => undefined);
    }).catch(() => undefined);
    await page.waitForTimeout(7000);

    const pageData = await page.evaluate(() => {
      const meta = (property) => document.querySelector(`meta[property="${property}"]`)?.content || '';
      const title = (meta('og:title') || document.title || '').replace(/\s*[-_]\s*抖音.*$/i, '').trim();
      return {
        title,
        description: meta('og:description') || document.querySelector('meta[name="description"]')?.content || '',
        final_url: location.href,
      };
    });

    let audioBytes = 0;
    if (downloadAudio) {
      if (!audioPath) throw new Error('DOUYIN_AUDIO_PATH is empty');
      const unique = [...new Map(candidates.map((item) => [item.url, item])).values()]
        .sort((a, b) => b.total - a.total);
      if (!unique.length) throw new Error('no audio media response was observed');
      let lastError;
      for (const candidate of unique) {
        try {
          audioBytes = await downloadByRanges(context.request, candidate.url, audioPath);
          if (audioBytes > 0) break;
        } catch (error) {
          lastError = error;
        }
      }
      if (!audioBytes) throw lastError || new Error('audio download failed');
    }

    result({
      ok: true,
      ...pageData,
      video_id: videoId(pageData.final_url) || videoId(sourceUrl),
      media_candidates: candidates.length,
      audio_bytes: audioBytes,
    });
  } catch (error) {
    result({ ok: false, error: String(error && error.message ? error.message : error) });
    process.exitCode = 2;
  } finally {
    await browser.close();
  }
})();
