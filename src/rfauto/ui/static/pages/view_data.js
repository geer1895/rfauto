/* rfauto 数据资产页族（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   数据集注册表 + 标定锚 + UQ 不确定度（全部只读，数值只在确定性内核）。 */

import { S, T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal——本文件
// 三页各族 signal：datasets/anchors/uq）
import { apiFetch, viewSignal } from "./api.js";
import { esc, escAttr, help } from "./dom.js";
import { bindClickRows, kitBadge, kitClickRowAttrs, kitErrorPanel, kitPanelHead, kitTable } from "./kit.js";

/* ═══ 数据集（runs/datasets 注册表：清单 + 行级预览，只读）═══ */
export async function pageDatasets() {
  const v = T.$("view-datasets");
  v.innerHTML = help(`
    <li>数据集 = 多次 run 的点级数据物化（Parquet/HDF5），是调参/校准/公开集的输入资产；本页<b>只读</b>。</li>
    <li>点数据集行 → 行级预览（抽样前 N 行）。<b>n_rows 是抽样返回行数，不是全量计数</b>；全量看「点数」列。</li>
    <li>「模板族」来自 manifest 登记的 per_family_rows / ground_truth.per_model 键集；旧 manifest 未登记时如实显示"未登记"，不臆测。</li>`) +
    `<h2 class='page'>数据集 <small>runs/datasets · 只读</small></h2>
     <div class='panel'><div class='toolbar'>
       <input id='ds-filter' size='24' placeholder='按名称/模板族过滤…'>
       <select id='ds-family'><option value=''>全部模板族</option></select>
       <button class='minor' id='ds-reload'>刷新</button>
       <span id='ds-count' class='muted'></span></div>
     <div id='ds-body' class='muted'>加载中...</div></div>
     <div id='ds-preview'></div>`;
  const d = await apiFetch("/api/datasets", { signal: viewSignal("datasets") });
  if (d.aborted) return; // UI-R12：切页取消——不写隐藏区
  const body = T.$("ds-body");
  if (!d.ok) {
    // A8-A（R6 P-4 面）：错误态动作化——badge+错误串+重试钮（W7-C 模式推广）
    body.innerHTML = kitErrorPanel((d.errors || []).join("; "), "ds-retry");
    const rb = T.$("ds-retry");
    if (rb) rb.onclick = () => pageDatasets();
    return;
  }
  S.dsAll = d.datasets || [];
  const families = [...new Set(S.dsAll.flatMap((x) => x.models || []))].sort();
  T.$("ds-family").innerHTML = "<option value=''>全部模板族</option>" +
    families.map((f) => `<option>${esc(f)}</option>`).join("");

  const render = () => {
    const ft = T.$("ds-filter").value.trim().toLowerCase();
    const fam = T.$("ds-family").value;
    const rows = S.dsAll.filter((x) => {
      if (ft && !(`${x.name} ${(x.models || []).join(" ")}`.toLowerCase().includes(ft))) return false;
      if (fam && !(x.models || []).includes(fam)) return false;
      return true;
    });
    T.$("ds-count").textContent = `${rows.length} / ${S.dsAll.length} 个数据集`;
    if (!rows.length) { body.innerHTML = "<span class='muted'>无匹配数据集（runs/datasets 下先物化）</span>"; return; }
    body.innerHTML = "<table><thead><tr><th scope='col'>名称</th><th scope='col'>点数</th><th scope='col'>行数</th><th scope='col'>模板族</th><th scope='col'>可见性</th><th scope='col'>GT 标注</th><th scope='col'>HF 导出</th><th scope='col'>格式</th><th scope='col'>创建时间</th></tr></thead><tbody>" +
      rows.map((x) => {
        const gt = x.n_gt_rows == null ? "<span class='muted'>-</span>"
          : `${esc(x.n_gt_rows)} 行${x.gt_unlocked ? " " + T.badge("unlocked", "ok") : ""}`;
        const famTxt = (x.models || []).length ? esc(x.models.join("、"))
          : "<span class='muted'>未登记</span>";
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
        return `<tr class='clickable' data-n='${escAttr(x.name)}' title='${escAttr(x.dataset_dir)}' ${kitClickRowAttrs({ role: null, label: "预览数据集：" + (x.name || "") })}>
          <td><b>${esc(x.name)}</b></td><td>${esc(x.n_points)}</td><td>${esc(x.n_rows)}</td>
          <td class='muted'>${famTxt}</td>
          <td>${x.visibility === "public" ? T.badge("public", "ok") : T.badge("private", "muted")}</td>
          <td class='muted'>${gt}</td>
          <td>${x.has_hf ? T.badge("有", "ok") : "<span class='muted'>无</span>"}</td>
          <td class='muted'>${esc(x.format)}</td>
          <td class='muted'>${esc((x.created_at || "").slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class='muted' style='margin-top:6px;font-size:11.5px'>点数据集行进入行级预览；目录：${escAttr(d.out_dir)}</div>`;
    bindClickRows(body, (tr) => loadPreview(tr.dataset.n), "tr.clickable"); // UI-R4：click/Enter/Space 同一激活
  };
  T.$("ds-filter").oninput = render;
  T.$("ds-family").onchange = render;
  T.$("ds-reload").onclick = () => pageDatasets();
  render();

  async function loadPreview(name) {
    const model = T.$("ds-family").value || "";
    const q = model ? `&model=${encodeURIComponent(model)}` : "";
    const p = await apiFetch(`/api/datasets/${encodeURIComponent(name)}/preview?limit=20${q}`,
      { signal: viewSignal("datasets") });
    if (p.aborted) return; // UI-R12：切页取消——不写隐藏区
    const el = T.$("ds-preview");
    if (!p.ok) { el.innerHTML = `<div class='panel'><b class='title'>预览 — ${escAttr(name)}</b><span style="color:var(--err)">${esc((p.errors || []).join("; "))}</span></div>`; return; }
    const cols = p.columns || [];
    const fmtCell = (val) => {
      if (val == null) return "<span class='muted'>-</span>";
      if (typeof val === "number") return String(+val.toFixed(6));
      if (typeof val === "object") return `<code>${esc(JSON.stringify(val))}</code>`;
      return esc(String(val));
    };
    el.innerHTML = `<div class='panel'><b class='title'>行级预览 — ${esc(p.dataset)}（${p.filters?.model ? `模板族 ${esc(p.filters.model)} · ` : ""}抽样 ${esc(p.n_rows)} 行；n_rows 为抽样返回行数，非全量计数）</b>
      <div style='overflow:auto;max-height:420px'><table><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${(p.rows || []).map((r) => `<tr>${cols.map((c) => `<td>${fmtCell(r[c])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div></div>`;
  }
}

/* ═══ 标定锚（锚注册表 + 新鲜度，只读）═══ */
export async function pageAnchors() {
  const v = T.$("view-anchors");
  v.innerHTML = help(`
    <li>锚 = (模板族 × 引擎对 × 域) → (常量|曲线|公式|指针) 的物理标定单源（knowledge/anchors.yaml），运行时只读；修订不改历史，新证据登记 -vN+1。指针锚=双引擎分歧双值登记（不产常数、不就地求值）。</li>
    <li><b>状态</b>即注册表裁决：active 健在 / stale 已过期 / experimental 实验指针（双值分歧待归因） / awaiting_data 骨架待回填 / retired 退役。无 last_verified 的锚新鲜度如实显示 UNKNOWN（不虚构判定）。</li>
    <li>点锚行看全量记录（provenance / uncertainty / consumers）。</li>`) +
    `<h2 class='page'>标定锚 <small>物理标定锚注册表 · 只读</small></h2>
     <div class='panel'><div class='toolbar'>
       <span id='an-kpi' class='muted'>加载中...</span>
       <button class='minor' id='an-reload'>刷新</button></div>
     <div id='an-body'></div></div>
     <div id='an-detail'></div>`;
  const load = async () => {
    const d = await apiFetch("/api/anchors", { signal: viewSignal("anchors") });
    if (d.aborted) return; // UI-R12：切页取消——不写隐藏区
    const body = T.$("an-body");
    if (!d.ok) {
      // A8-A（R6 P-4 面）：错误态动作化——badge+错误串+重试钮（W7-C 模式推广）
      body.innerHTML = kitErrorPanel((d.errors || []).join("; "), "an-retry");
      const rb = T.$("an-retry");
      if (rb) rb.onclick = load;
      return;
    }
    T.$("an-kpi").innerHTML =
      `共 <b>${d.count}</b>/${d.expected_count} 锚 · ` +
      (d.stale_count ? T.badge(`${d.stale_count} stale`, "warn") : T.badge("0 stale", "ok")) + " " +
      (d.no_date_count ? T.badge(`${d.no_date_count} 无验证日期（UNKNOWN）`, "muted") : "");
    if (d.load_errors?.length)
      body.insertAdjacentHTML("beforeend",
        `<div style="color:var(--err);margin-bottom:var(--space-2)">注册表装载告警：${esc(d.load_errors.join("; "))}</div>`);
    // A7-A ui-kit：锚状态→类单源（kitBadge 查 KIT_STATUS_CLS；未知状态
    // 一律 muted——原查表回退同串；无状态 UNKNOWN 同串）
    const stBadge = (st) => kitBadge(st || "UNKNOWN", st);
    body.insertAdjacentHTML("beforeend",
      "<table><thead><tr><th scope='col'>anchor_id</th><th scope='col'>状态</th><th scope='col'>锚类型</th><th scope='col'>模板族</th><th scope='col'>量 / 值</th><th scope='col'>引擎对</th><th scope='col'>新鲜度</th></tr></thead><tbody>" +
      (d.anchors || []).map((a) => {
        const si = a.stale_info || {};
        const fresh = si.stale === true
          ? T.badge(`stale（龄期 ${si.age_days} 天）`, "warn")
          : si.stale === false ? T.badge("新鲜", "ok")
          : T.badge("UNKNOWN（无验证日期）", "muted");
        const unit = a.quantity?.unit ? ` ${esc(a.quantity.unit)}` : "";
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
        return `<tr class='clickable' data-id='${escAttr(a.anchor_id)}' ${kitClickRowAttrs({ role: null, label: "查看锚详情：" + (a.anchor_id || "") })}>
          <td><b>${esc(a.anchor_id)}</b></td><td>${stBadge(a.status)}</td><td class='muted'>${esc(a.kind)}</td>
          <td class='muted'>${esc((a.template_family || []).join("、"))}</td>
          <td>${esc(a.quantity?.name ?? "")} = <b>${esc(a.value ?? "-")}</b>${unit}</td>
          <td class='muted'>${a.engine_pair ? `${esc(a.engine_pair.calibrated)}→${esc(a.engine_pair.referee)}` : "-"}</td>
          <td>${fresh}</td></tr>`;
      }).join("") + "</tbody></table>");
    // UI-R4：click/Enter/Space 同一激活（详情回调 async 形态保持）
    bindClickRows(body, async (tr) => {
      const det = await apiFetch("/api/anchors/" + encodeURIComponent(tr.dataset.id),
        { signal: viewSignal("anchors") });
      if (det.aborted) return; // UI-R12：切页取消——不写隐藏区
      T.$("an-detail").innerHTML = det.ok
        ? `<div class='panel'><b class='title'>锚详情 — ${esc(det.anchor.anchor_id)}</b><pre>${esc(JSON.stringify(det.anchor, null, 2))}</pre></div>`
        : `<div class='panel'><span style="color:var(--err)">${esc(det.error || "详情不可读")}</span></div>`;
    }, "tr.clickable");
  };
  T.$("an-reload").onclick = load;
  await load();
}

/* ═══ UQ 不确定度（代理蒙特卡洛良率 + 敏感性；数值只在确定性内核）═══ */
export async function pageUq() {
  const v = T.$("view-uq");
  v.innerHTML = help(`
    <li>UQ = 代理蒙特卡洛公差分析：给定校准样本集 + 逐参数公差 σ，免费评估良率 / 指标分布 / 参数敏感性——不跑真机。</li>
    <li>数值全部由确定性内核（uq_service.surrogate_yield）产出，前端只渲染；<b>无样本集/无公差时如实空态，不 mock</b>。</li>
    <li>敏感性 = 单参数 ±1σ 扰动的指标响应幅值合计（|Δmetric| 求和），越大越该优先收公差。</li>`) +
    `<h2 class='page'>UQ 不确定度 <small>代理蒙特卡洛 · 良率 / 分布 / 敏感性</small></h2>
     ${kitPanelHead("① 校准样本集（runs/ 下 samples 资产，点选填入）")}
       <div id='uq-assets' class='muted'>加载中...</div></div>
     <div class='panel'><b class='title'>② 运行（确定性内核，万点级秒回）</b>
       <div class='toolbar'>样本集: <input id='uq-path' style='flex:1;min-width:280px' placeholder='runs/xxx/calibration/samples.json'>
         代理: <select id='uq-kind'><option>poly_ridge</option><option>nn</option></select>
         抽样: <input id='uq-n' value='10000' size='7'> seed: <input id='uq-seed' value='42' size='5'>
         <button class='act' id='uq-run'>运行 UQ</button><span id='uq-spin'></span></div>
       <div id='uq-tol' class='muted' style='margin-top:6px'>选中样本集后这里列出逐参数公差 σ（留空=该参数不扰动）</div></div>
     <div id='uq-result'></div>`;
  const assets = await apiFetch("/api/uq/samples", { signal: viewSignal("uq") });
  if (assets.aborted) return; // UI-R12：切页取消——不写隐藏区
  const el = T.$("uq-assets");
  if (!assets.ok) { el.innerHTML = `<span style="color:var(--err)">${esc((assets.errors || []).join("; "))}</span>`; return; }
  if (!(assets.items || []).length) {
    el.innerHTML = "<span class='muted'>runs/ 下未发现校准样本集（samples.json 族）——先跑校准或战役，本页如实空态</span>";
  } else {
    el.innerHTML = "<table><thead><tr><th scope='col'>文件</th><th scope='col'>样本数</th><th scope='col'>目标数</th><th scope='col'>参数（bounds）</th><th scope='col'>修改时间</th></tr></thead><tbody>" +
      assets.items.map((it) => {
        const n = it.parsed ? `${esc(it.n_samples)}` : "<span class='muted'>未解析（过大/损坏）</span>";
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
        return `<tr class='clickable' data-p='${escAttr(it.path)}' ${kitClickRowAttrs({ role: null, label: "选用样本集：" + (it.path || "") })}>
          <td><b>${esc(it.path)}</b></td><td>${n}</td>
          <td class='muted'>${it.parsed ? esc(it.n_objectives ?? "-") : "-"}</td>
          <td class='muted'>${esc((it.bounds_params || []).join("、")) || "-"}</td>
          <td class='muted'>${esc(new Date(it.mtime * 1000).toISOString().slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      (assets.truncated ? "<div class='muted' style='margin-top:var(--space-1)'>清单已达上限，未全列</div>" : "");
    bindClickRows(el, (tr) => pickAsset(tr.dataset.p), "tr.clickable"); // UI-R4：click/Enter/Space 同一激活
  }
  async function pickAsset(path) {
    T.$("uq-path").value = path;
    const item = (assets.items || []).find((x) => x.path === path);
    const params = (item && item.bounds_params) || [];
    // UI-R11（A6 P2-7 可测试性半边）：pg-s-* 惯例 id（key() 消毒参数名）
    const key = (v) => String(v).replace(/\W/g, "_");
    T.$("uq-tol").innerHTML = params.length
      ? "<table><thead><tr><th scope='col'>参数</th><th scope='col'>容差 σ（与参数同单位）</th></tr></thead><tbody>" +
        params.map((n) => `<tr><td><b>${esc(n)}</b></td><td><input id='uq-sig-${key(n)}' class='uq-sigma' data-p='${escAttr(n)}' size='12' step='any' placeholder='σ（留空不扰动）' aria-label='参数 ${escAttr(n)} 的公差 σ'></td></tr>`).join("") +
        "</tbody></table>"
      : "该样本集无 bounds 参数清单，σ 需按参数名手填内核参数（或换样本集）";
  }
  T.$("uq-run").onclick = async () => {
    const tolerances = {};
    let bad = null;
    document.querySelectorAll("#uq-tol .uq-sigma").forEach((inp) => {
      const raw = inp.value.trim();
      if (raw === "" || bad) return;
      const num = Number(raw);
      if (isNaN(num)) { bad = inp.dataset.p; return; }
      tolerances[inp.dataset.p] = num;
    });
    if (bad) return T.msg(`参数 ${bad} 的 σ 不是数值`, false);
    if (!Object.keys(tolerances).length) return T.msg("至少填一个参数公差 σ（内核要求 {param: σ} 非空）", false);
    const btn = T.$("uq-run");
    btn.disabled = true; T.$("uq-spin").innerHTML = "<span class='spin'></span>";
    const r = await apiFetch("/api/uq/yield", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples_path: T.$("uq-path").value.trim(),
                             tolerances, n: parseInt(T.$("uq-n").value) || 10000,
                             seed: parseInt(T.$("uq-seed").value) || 42,
                             kind: T.$("uq-kind").value }),
      signal: viewSignal("uq"), // UI-R12：统一 API 层（token 透传/切页取消）
    });
    btn.disabled = false; T.$("uq-spin").innerHTML = "";
    if (r.aborted) return; // UI-R12：切页取消——不写隐藏区（按钮态已在上方复位）
    renderUqResult(r);
  };

  function renderUqResult(r) {
    const el = T.$("uq-result");
    if (!r.ok) {
      el.innerHTML = `<div class='panel'><span style="color:var(--err)">UQ 未出结果（如实）：${esc((r.errors || ["未知错误"]).join("; "))}</span></div>`;
      return;
    }
    const yPct = (r.yield_rate * 100).toFixed(1) + "%";
    const yCls = r.yield_rate >= 0.9 ? "ok" : r.yield_rate >= 0.7 ? "warn" : "err";
    const stats = Object.entries(r.metric_stats || {});
    const deltas = r.sensitivity_violation_delta || {};
    const maxD = Math.max(...Object.values(deltas).map((x) => Math.abs(x)), 1e-12);
    el.innerHTML = `<div class='cards'>
        <div class='card'><div class='k'>良率</div><div class='v ${yCls}'>${yPct}</div></div>
        <div class='card'><div class='k'>抽样点数</div><div class='v'>${r.n_draws}</div></div>
        <div class='card'><div class='k'>代理</div><div class='v'>${esc(r.surrogate_kind)}</div></div>
        <div class='card'><div class='k'>名义点指标均值</div><div class='v'>${stats.length} 项</div></div>
      </div>
      <div class='grid2'>
        ${kitPanelHead("指标分布（蒙特卡洛）")}
          ${kitTable({
            columns: ["指标", "mean", "std", "q05", "q95"],
            rowsHtml: stats.map(([m, s]) => `<tr><td><b>${esc(m)}</b></td><td>${(+s.mean).toFixed(4)}</td><td>${(+s.std).toFixed(4)}</td><td>${(+s.q05).toFixed(4)}</td><td>${(+s.q95).toFixed(4)}</td></tr>`).join(""),
            empty: "<tr><td colspan='5' class='muted'>无</td></tr>",
          })}
          <div class='muted' style='margin-top:6px;font-size:11.5px'>名义参数：${esc(JSON.stringify(r.nominal_params))}<br>实现：${esc(r.implementation || "-")} · 不确定度状态：${esc(r.uncertainty_status ?? "-")}</div></div>
        <div class='panel'><b class='title'>逐参数敏感性（±1σ 指标响应合计，降序）</b>
          ${(r.sensitivity_ranking || []).map((p) => {
            const dv = Math.abs(deltas[p] || 0);
            return `<div style='margin-bottom:var(--space-2)'><b>${esc(p)}</b> <span class='muted'>|Δ|=${dv.toFixed(5)}</span>
              <div style='height:8px;border-radius:4px;background:var(--panel2);margin-top:3px'>
              <div style='height:8px;border-radius:4px;width:${(dv / maxD * 100).toFixed(1)}%;background:var(--accent)'></div></div></div>`;
          }).join("") || "<span class='muted'>无</span>"}
          <div class='muted' style='margin-top:6px;font-size:11.5px'>敏感性越大 = 该参数公差对指标影响越大，优先收公差或换设计中心。</div></div>
      </div>`;
    T.msg("UQ 完成（确定性内核）", true);
  }
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子（数据资产三页）════════
   refresh=各自 page 函数整体重拉（三页均只读数据面；datasets/anchors 与页内
   「刷新」钮同语义，uq 与重进同语义——σ 表单态随重建清空，palette 旧回退
   路径本就如此，无行为增量）。无轮询面，leave 不需要。 */
export const datasetsCtx = {
  refresh: () => pageDatasets(),
};
export const anchorsCtx = {
  refresh: () => pageAnchors(),
};
export const uqCtx = {
  refresh: () => pageUq(),
};
