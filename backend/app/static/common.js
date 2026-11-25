
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? "{}" : JSON.stringify(body),
  });
  const t = await r.text();
  let data;
  try { data = JSON.parse(t); } catch { data = { 原文: t }; }
  if (!r.ok) throw new Error((data && (data.错误 || data.detail)) || t || String(r.status));
  return data;
}
function 行(html) {
  const tr = document.createElement("tr");
  tr.innerHTML = html;
  return tr;
}
function 徽章(文, 类) {
  const tone = 类 || 命运色(文);
  return `<span class="徽章 ${tone || ""}">${安全文本(文)}</span>`;
}
function 空态(文) { return `<p class="说明">${安全文本(文)}</p>`; }
function 安全文本(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
function 命运色(f) {
  if (["已入栏", "在栏", "已汇总", "对齐"].includes(f)) return "ok";
  if (["已坏点", "撕裂"].includes(f)) return "warn";
  return "";
}
function 渲染水位(el, o) {
  if (!el) return;
  el.innerHTML = "";
  for (const [标, 键] of [["观测报文","观测报文"],["在栏","在栏"],["站点汇总","站点汇总"],["坏点","坏点"]]) {
    const d = document.createElement("div");
    d.className = "水卡";
    d.innerHTML = `<div class="数">${o[键] ?? 0}</div><div class="标">${标}</div>`;
    el.appendChild(d);
  }
}
function 渲染门槛(el, 规) {
  if (!el) return;
  const r = 规 || {};
  el.innerHTML = `
    <div class="门槛卡"><div class="k">当前栏</div><div class="v">${安全文本(r["当前栏号"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 上限</div><div class="v">${安全文本(r["PM25上限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 下限</div><div class="v">${安全文本(r["PM25下限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">标定偏移</div><div class="v">${安全文本(r["标定偏移上限"] || "—")}</div></div>
    <div class="门槛卡" data-映射版本卡 title="原因码映射版本门：旁路凭证表钉住版本指纹，未知码禁升格">
      <div class="k">原因码映射版本</div>
      <div class="v" data-映射版本值>v2</div>
      <div class="k" data-映射指纹值>指纹加载中…</div>
    </div>
  `;
  填充映射版本卡(el);
}
async function 填充映射版本卡(根) {
  try {
    const m = await getJSON("/api/原因码映射");
    const v = 根.querySelector("[data-映射版本值]");
    const f = 根.querySelector("[data-映射指纹值]");
    if (v) {
      v.textContent = `${m["版本"] || "—"}${m["新鲜"] ? "" : " · 失鲜"}`;
      v.setAttribute("data-reasonmap-version", m["版本"] || "");
      v.setAttribute("data-fresh", m["新鲜"] ? "1" : "0");
    }
    if (f) f.textContent = `指纹 ${m["短指纹"] || (m["指纹"] || "").slice(0, 12) || "—"} · 未知码拒升`;
  } catch (e) {
    const f = 根.querySelector("[data-映射指纹值]");
    if (f) f.textContent = "映射版本不可读";
  }
}
async function 渲染映射版本条(el) {
  if (!el) return;
  try {
    const m = await getJSON("/api/原因码映射");
    const tone = m["新鲜"] ? "好" : "危";
    el.innerHTML = `
      <span class="徽章 ${tone}" data-reasonmap-version="${安全文本(m["版本"] || "")}">
        原因码映射版本 ${安全文本(m["版本"] || "—")}
      </span>
      <span class="说明">指纹 <code id="映射指纹">${安全文本(m["短指纹"] || "")}</code>
      · 旁路凭证已钉 · ${m["新鲜"] ? "新鲜一致" : "失鲜"} · 未知码一律拒升格</span>`;
  } catch (e) {
    el.innerHTML = `<span class="徽章 危">原因码映射版本读取失败</span>`;
  }
}
function 渲染批次表(el, rows, cols) {
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = `<tr><td colspan="${cols.length}">${空态("尚无批次。")}</td></tr>`;
    return;
  }
  el.innerHTML = "";
  for (const r of rows) {
    const cells = cols.map((c) => `<td>${安全文本(r[c])}</td>`).join("");
    el.appendChild(行(cells));
  }
}
function 装载摘要文(r) {
  if (!r) return "";
  return `入流 ${r["入流"]||0} · 入栏 ${r["入栏"]||0} · 坏点 ${r["坏点"]||0} · 驳回 ${r["驳回"]||0}`;
}
function 结栏摘要文(r) {
  if (!r) return "";
  return `栏 ${r["栏号"]||"?"} · 汇总 ${r["汇总数"]||0} · 缓冲消耗 ${r["缓冲消耗"]||0}`;
}
function 贯验摘要文(r) {
  if (!r) return "";
  return `${r["是否对齐"]?"对齐":"撕裂"} · 在栏 ${r["在栏"]} · 汇总报文 ${r["汇总报文"]} · 坏点 ${r["坏点"]}`;
}
function 填命运字典(el, dict) {
  if (!el || !dict) return;
  el.innerHTML = Object.entries(dict).map(([k, v]) =>
    `<div class="只读框 上距8"><b class="铜字">${安全文本(k)}</b> · ${安全文本(v)}</div>`
  ).join("");
}
window.探栏 = {
  getJSON, postJSON, 行, 徽章, 空态, 安全文本, 命运色,
  渲染水位, 渲染门槛, 渲染批次表, 渲染映射版本条, 填充映射版本卡,
  装载摘要文, 结栏摘要文, 贯验摘要文, 填命运字典,
};
