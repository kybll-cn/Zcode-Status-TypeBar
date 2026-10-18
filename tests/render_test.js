/* 状态条渲染回归测试（无依赖，node tests/render_test.js 即可跑）。
 *
 * 为什么需要它：overlay.js 的 html() 跑在客户端渲染进程里，语法检查（new Function）
 * 查不出运行时错误 —— v31 事故就是这么来的：html() 里一个局部变量遮蔽了同名辅助函数，
 * 调用时抛 TypeError，整个 html() 崩掉、状态条整条消失（不是某一项不显示），
 * 而 `new Function()` 语法校验照样通过。
 *
 * 用法：
 *   node tests/render_test.js                      # 用内置样例数据（无需数据库）
 *   node tests/render_test.js payload.json         # 用真实 payload（python zusage.py json > payload.json）
 *
 * 约定（踩过的坑，勿改）：
 *   1. 抽取的是 overlay.js 里真实的那段渲染代码，不是副本 —— 复制一份出来测等于没测；
 *   2. 辅助函数一律用真实函数名，不要为了让测试通过而改名（改名正好会掩盖遮蔽 bug）；
 *   3. 新增显示项时在下面补一个用例。 */
"use strict";
const fs = require("fs");
const path = require("path");

const OVERLAY = path.join(__dirname, "..", "overlay.js");
const src = fs.readFileSync(OVERLAY, "utf8");

/* 抽取渲染段：fmt 定义 → pickCurrent 前的注释块。段内含 fmt/sec/relAgo/excActive/
 * cachePct/fmtTime/ioc/ico/html；state 与 L 在段外，按同款实现补上。 */
const startMark = "    function fmt(n) {";
const endMark = "    /* 当前会话识别（v34 起 mine 优先";
const i1 = src.indexOf(startMark), i2 = src.indexOf(endMark);
if (i1 < 0 || i2 < 0 || i2 <= i1) {
  console.error("✗ 抽取标记未找到（overlay.js 结构变了？）startMark=" + i1 + " endMark=" + i2);
  process.exit(1);
}
const renderSrc = src.slice(i1, i2);

const factory = new Function(`
"use strict";
var state = { show: { speed: 1, ctx: 1, win: 1, err: 1, today: 1 }, ctxOv: "", lang: "zh", data: null };
function L(zh, en) { return state.lang === "en" ? en : zh; }
${renderSrc}
return { html: html, state: state };
`);
let mod;
try {
  mod = factory();
} catch (e) {
  console.error("✗ 渲染段加载失败:", e.stack);
  process.exit(1);
}
const html = mod.html, state = mod.state;

/* 内置样例：结构必须与 zusage.py 的 _session_snapshot / _last_metrics 完全对齐 */
const SAMPLE = {
  session: {
    sid: "sess_sample-0000", title: "样例会话", active: true,
    turns: 8, requests: 42, input: 12500000, output: 96000, reasoning: 0,
    cache_read: 12490000, cache_write: 0, total: 12596000, tool_calls: 176, retries: 0,
    ctx: 347000, updated: "12:00:00", last_at: 0, ctx_exc: 0,
    last_turn: { requests: 6, retries: 0, tool_calls: 6, tool_errors: 0, input: 340000,
      output: 2100, reasoning: 0, cache_read: 339000, cache_write: 0, total: 343000,
      duration_ms: 48000, ttft_ms: 8400 },
    code: { add: null, del: null, files: null },
    tools: { total: 176, errors: 0, list: [] },
    sub: { requests: 0, total: 0, input: 0, output: 0, cache_read: 0, active: false, list: [] },
    context_window: 1000000, context_auto: false,
  },
  last: {
    duration_ms: 6100, ttft_ms: 8400, model: "tokenrhythm/deepseek-flash",
    tps: 27.9, tps_gen: 162.0, tps_last: 158.4, tps_e2e: 43.8,
    gen_ms: 12900, gen_out: 2090, gen_req: 6, gen_cov: 0.96,
    turn_out: 2100, turn_ms: 48000, api_ttft_ms: 4200, client_ms: 4200,
    ttft_partial: false, cache_read: 12490000, input: 12500000, cache_write: 0,
    cache_fresh: 10000, ago_ms: 1200, stale: false, at: 0,
  },
  today: { requests: 120, input: 150000000, output: 320000, cache_read: 149000000,
    total: 156320000, reasoning: 0, retries: 0, cache_write: 0 },
  tools: { total: 176, errors: 0, list: [] },
  err: { turns: 0, tools: 0, retries: 0, total: 0 },
  recent: [], not_local: [], remote_enabled: false, remote_today: null,
  context_window: 1000000, context_auto: false, code: { add: null, del: null, files: null },
  ctx_exc: 0,
};
/* 真实 payload（可选）：python zusage.py json > payload.json */
const payload = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], "utf8")) : SAMPLE;
payload.session.last = payload.last;   // 真实 payload 里 last 在顶层与 session 各一份

function view(p, lastObj, extra) {
  return Object.assign({
    session: p, last_turn: p.last_turn || {}, last: lastObj || payload.last || {},
    mine_idle: false,
    today: payload.today, native_ctx: 0,
    context_window: p.context_window, context_auto: false,
    code: p.code, ctx_exc: p.ctx_exc || 0, tools: p.tools,
    remote: false, remote_host: "", remote_error: "", not_local: false,
    remote_enabled: false, remote_empty: false,
    sub: p.sub || { requests: 0, total: 0, input: 0, output: 0, cache_read: 0, active: false, list: [] },
  }, extra || {});
}
function strip(h) {
  return h.s.replace(/<svg[\s\S]*?<\/svg>/g, "◈").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}
let ok = true, n = 0;
function dump(tag, v, expect) {
  n++;
  let h;
  try { h = html(v); } catch (e) {
    console.error("✗ [" + tag + "] 渲染抛异常: " + e.message + "\n" + e.stack.split("\n").slice(0, 4).join("\n"));
    ok = false;
    return;
  }
  console.log("[" + tag + "] " + strip(h));
  if (h.tips.length !== (h.s.match(/class="it/g) || []).length) {
    console.error("  ✗ 条目数与 tips 数量不匹配（tooltip 会错位）");
    ok = false;
  }
  for (const kw of expect || []) {
    if (strip(h).indexOf(kw) < 0) { console.error("  ✗ 缺少预期片段: " + kw); ok = false; }
  }
}

const sess = payload.session, last = payload.last;
console.log("数据源: " + (process.argv[2] ? process.argv[2] : "内置样例") + " | 速度 " + last.tps_gen +
  " | 首字 " + last.ttft_ms + "ms | ago " + last.ago_ms + "ms\n");

dump("活跃", view(sess, last), [String(last.tps_gen), "t/s", "首字"]);
const l5 = Object.assign({}, last, { at: Date.now() - (5 * 60 * 1000 + 1234), stale: true });
dump("停滞5m(at 现算)", view(sess, l5), ["5分钟前"]);
dump("停滞3m(旧后端仅 ago_ms)", view(sess, Object.assign({}, last, { at: 0, ago_ms: 3 * 60 * 1000, stale: true })), ["3分钟前"]);
dump("12小时前", view(sess, Object.assign({}, last, { at: Date.now() - 12 * 3600 * 1000, stale: true })), ["12小时前"]);
dump("闲置上轮(泵 mine_idle)", view(sess, last, { mine_idle: true }), ["上轮"]);
const stub = Object.assign({}, sess, { turns: 0, requests: 0, input: 0, output: 0, cache_read: 0,
  total: 0, tool_calls: 0, ctx: 0,
  last: { duration_ms: 0, ttft_ms: 0, model: "", tps: 0, tps_gen: 0, tps_last: 0, tps_e2e: 0,
    gen_ms: 0, gen_out: 0, gen_req: 0, gen_cov: 0, turn_out: 0, turn_ms: 0, api_ttft_ms: 0,
    client_ms: 0, ttft_partial: false, cache_read: 0, input: 0, cache_write: 0, cache_fresh: 0,
    ago_ms: 0, stale: false, at: 0 } });
dump("空会话(占位不隐藏)", view(stub, stub.last), ["– t/s"]);
dump("旧后端(仅 last.tps)", view(sess, { duration_ms: 6100, ttft_ms: 8400, tps: 27.9,
  cache_read: 12490000, input: 12500000, cache_write: 0, cache_fresh: 10000 }));
dump("无覆盖率字段", view(sess, Object.assign({}, last, { gen_cov: 0, gen_req: 0 })));
state.lang = "en";
dump("英文", view(sess, last), ["t/s", "TTFT"]);
state.lang = "zh";
state.show.speed = 0;
dump("speed 项关闭", view(sess, last));
state.show.speed = 1;

console.log(ok ? "\n✓ " + n + " 个用例全部通过" : "\n✗ 存在失败用例");
process.exit(ok ? 0 : 1);
