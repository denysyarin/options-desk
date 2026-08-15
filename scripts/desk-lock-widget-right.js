// Desk lock RIGHT — overnight RV ranks 4–6.
// Pair with desk-lock-widget.js (ranks 1–3). Two Scriptable scripts, two widgets.
// Re-paste this into Scriptable. Tap opens GitHub lock-tape.md in Safari (not Claude).
// iOS tints accessory widgets. Heat is white opacity, not color.
// Not a LOOK list. Chains do not exist until the 09:30 RTH job.

const PANE = "right";

const FEED =
  "https://raw.githubusercontent.com/denysyarin/options-desk/main/snapshots/lock-widget.json";
const CACHE = "desk-lock-widget.json";
const FALLBACK = {
  as_of: "2026-08-14",
  label: "RV",
  hot: [
    { ticker: "NBIS", rv: 1.882, month_vol: 1.894, tone: "hot", earn: false },
    { ticker: "IREN", rv: 1.49, month_vol: 1.554, tone: "hot", earn: true },
    { ticker: "ONTO", rv: 1.089, month_vol: 1.135, tone: "mid", earn: false },
    { ticker: "SPCX", rv: 1.04, month_vol: 1.262, tone: "mid", earn: false },
    { ticker: "DELL", rv: 0.86, month_vol: 1.126, tone: "mid", earn: false },
    { ticker: "AMZN", rv: 0.616, month_vol: 0.392, tone: "cold", earn: false },
  ],
};
const TONE = {
  hot: new Color("#ffffff", 1),
  mid: new Color("#ffffff", 0.55),
  cold: new Color("#ffffff", 0.22),
};

function fmtRv(x) {
  return Number(x).toFixed(2);
}

function pane(data) {
  const hot = data.hot || [];
  return PANE === "right" ? hot.slice(3, 6) : hot.slice(0, 3);
}

function cachePath() {
  const fm = FileManager.local();
  return fm.joinPath(fm.documentsDirectory(), CACHE);
}

function readCache() {
  const fm = FileManager.local();
  const path = cachePath();
  if (!fm.fileExists(path)) return null;
  try {
    return JSON.parse(fm.readString(path));
  } catch (_) {
    return null;
  }
}

function writeCache(data) {
  FileManager.local().writeString(cachePath(), JSON.stringify(data));
}

async function loadFeed() {
  try {
    const req = new Request(FEED);
    req.timeoutInterval = 8;
    const data = await req.loadJSON();
    if (data && Array.isArray(data.hot)) {
      writeCache(data);
      return data;
    }
  } catch (_) {}
  return readCache() || FALLBACK;
}

function buildRectangular(data) {
  const w = new ListWidget();
  w.setPadding(6, 8, 6, 8);
  const items = pane(data);
  for (let i = 0; i < 3; i++) {
    const row = w.addStack();
    row.layoutHorizontally();
    row.centerAlignContent();
    const item = items[i];
    if (item) {
      const color = TONE[item.tone] || TONE.mid;
      const title = row.addText(item.ticker + (item.earn ? " ·" : ""));
      title.font = Font.boldSystemFont(12);
      title.textColor = color;
      title.lineLimit = 1;
      title.minimumScaleFactor = 0.7;
      row.addSpacer();
      const val = row.addText(fmtRv(item.rv));
      val.font = Font.mediumSystemFont(12);
      val.textColor = color;
      val.lineLimit = 1;
    }
    if (i < 2) w.addSpacer(4);
  }
  return w;
}

function buildCircular(data) {
  const w = new ListWidget();
  const item = pane(data)[0];
  if (!item) {
    const empty = w.addText("—");
    empty.font = Font.boldSystemFont(14);
    empty.centerAlignText();
    return w;
  }
  const color = TONE[item.tone] || TONE.hot;
  const title = w.addText(item.ticker);
  title.font = Font.boldSystemFont(12);
  title.textColor = color;
  title.centerAlignText();
  title.minimumScaleFactor = 0.7;
  const val = w.addText(fmtRv(item.rv));
  val.font = Font.mediumSystemFont(11);
  val.textColor = color;
  val.centerAlignText();
  return w;
}

function buildInline(data) {
  const w = new ListWidget();
  const hot = data.hot || [];
  const body = hot.map((h) => `${h.ticker} ${fmtRv(h.rv)}`).join(" · ");
  const line = body || "desk";
  const t = w.addText(line);
  t.font = Font.mediumSystemFont(12);
  t.lineLimit = 1;
  return w;
}

function clickUrl(data) {
  const u = data.click_url && String(data.click_url);
  if (u && u.indexOf("claude.ai") === -1) return u;
  return "https://github.com/denysyarin/options-desk/blob/main/snapshots/lock-tape.md";
}

function decorate(w, data) {
  w.url = clickUrl(data);
  w.refreshAfterDate = new Date(Date.now() + 30 * 60 * 1000);
  return w;
}

const data = await loadFeed();
const family = config.widgetFamily;
let widget;
if (family === "accessoryCircular") widget = buildCircular(data);
else if (family === "accessoryInline") widget = buildInline(data);
else widget = buildRectangular(data);
decorate(widget, data);

if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentAccessoryRectangular();
}
Script.complete();
