/* rfauto 数据资产页族（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   数据集注册表 + 标定锚 + UQ 不确定度（全部只读，数值只在确定性内核）。
   i18n（架构批 W2-S1 批 4，R1 §面2 P9-5）：三页 chrome 文案全迁词表
   （datasets./anchors./uq. 键域，zh 与旧字面逐字节同、en 新增）——静态
   壳标题/过滤框/刷新钮挂 data-i18n（h2 内含 small 子元素，静态文案包
   span——detail 页先例）；随数据重建的容器（表体/选项表/预览面板）一律
   t() 渲染期烘焙（i18n.js 头注纪律）；API 数据照旧走 esc/escAttr 不进词表。
   aria 行标签经 t() 组装后仍由 kit escAttr 出口单点转义（test_ui_a11y_rows
   钉面同笔更新）。 */

import { T } from "./context.js";
// UI-R12 任务2：统一 API 层（apiFetch + 视图作用域取消 signal——本文件
// 三页各族 signal：datasets/anchors/uq）
import { apiFetch, viewSignal } from "./api.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（批 4）：三页接线（壳静态标注 + 动态容器烘焙）
import { t, applyI18nRoot } from "./i18n.js";
import { bindClickRows, kitBadge, kitClickRowAttrs, kitErrorPanel, kitPanelHead, kitTable } from "./kit.js";

/* 数据集清单缓存（W6-S2 S 状态收编：原 S.dsAll 单模块私有键降级模块级
   ——属主=本模块三页共壳，契约表见 context.js；进页重拉语义不变）。 */
let _dsAll = null;

/* ═══ 数据集（runs/datasets 注册表：清单 + 行级预览，只读）═══ */
export async function pageDatasets() {
  const v = T.$("view-datasets");
  v.innerHTML = help(`
    <li>${t("datasets.help_1_lead")}<b>${t("datasets.help_1_core")}</b>${t("datasets.help_1_tail")}</li>
    <li>${t("datasets.help_2_lead")}<b>${t("datasets.help_2_core")}</b>${t("datasets.help_2_tail")}</li>
    <li>${t("datasets.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='datasets.title'>${t("datasets.title")}</span> <small data-i18n='datasets.subtitle'>${t("datasets.subtitle")}</small></h2>
     <div class='panel'><div class='toolbar'>
       <input id='ds-filter' size='24' placeholder='${t("datasets.filter_ph")}' data-i18n-ph='datasets.filter_ph'>
       <select id='ds-family'><option value=''>${t("datasets.all_families")}</option></select>
       <button class='minor' id='ds-reload' data-i18n='datasets.reload'>${t("datasets.reload")}</button>
       <span id='ds-count' class='muted'></span></div>
     <div id='ds-body' class='muted'>${t("datasets.loading")}</div></div>
     <div id='ds-preview'></div>`;
  applyI18nRoot(v); // 壳静态标注首扫（标题/过滤框/刷新钮；动态容器走 t() 烘焙）
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
  _dsAll = d.datasets || [];
  const families = [...new Set(_dsAll.flatMap((x) => x.models || []))].sort();
  T.$("ds-family").innerHTML = `<option value=''>${t("datasets.all_families")}</option>` +
    families.map((f) => `<option>${esc(f)}</option>`).join("");

  const render = () => {
    const ft = T.$("ds-filter").value.trim().toLowerCase();
    const fam = T.$("ds-family").value;
    const rows = _dsAll.filter((x) => {
      if (ft && !(`${x.name} ${(x.models || []).join(" ")}`.toLowerCase().includes(ft))) return false;
      if (fam && !(x.models || []).includes(fam)) return false;
      return true;
    });
    T.$("ds-count").textContent = t("datasets.count_tpl", { n: rows.length, total: _dsAll.length });
    if (!rows.length) { body.innerHTML = `<span class='muted'>${t("datasets.empty_filter")}</span>`; return; }
    body.innerHTML = "<table><thead><tr>" +
      `<th scope='col'>${t("datasets.th_name")}</th><th scope='col'>${t("datasets.th_points")}</th>` +
      `<th scope='col'>${t("datasets.th_rows")}</th><th scope='col'>${t("datasets.th_family")}</th>` +
      `<th scope='col'>${t("datasets.th_visibility")}</th><th scope='col'>${t("datasets.th_gt")}</th>` +
      `<th scope='col'>${t("datasets.th_hf")}</th><th scope='col'>${t("datasets.th_format")}</th>` +
      `<th scope='col'>${t("datasets.th_created")}</th>` +
      "</tr></thead><tbody>" +
      rows.map((x) => {
        const gt = x.n_gt_rows == null ? "<span class='muted'>-</span>"
          : `${t("datasets.gt_rows_tpl", { n: esc(x.n_gt_rows) })}${x.gt_unlocked ? " " + T.badge("unlocked", "ok") : ""}`;
        const famTxt = (x.models || []).length ? esc(x.models.join("、"))
          : `<span class='muted'>${t("datasets.unregistered")}</span>`;
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作
        // ——t() 组装后仍由 kit escAttr 出口单点转义）
        return `<tr class='clickable' data-n='${escAttr(x.name)}' title='${escAttr(x.dataset_dir)}' ${kitClickRowAttrs({ role: null, label: t("datasets.aria_preview_tpl", { name: (x.name || "") }) })}>
          <td><b>${esc(x.name)}</b></td><td>${esc(x.n_points)}</td><td>${esc(x.n_rows)}</td>
          <td class='muted'>${famTxt}</td>
          <td>${x.visibility === "public" ? T.badge("public", "ok") : T.badge("private", "muted")}</td>
          <td class='muted'>${gt}</td>
          <td>${x.has_hf ? T.badge(t("datasets.hf_yes"), "ok") : `<span class='muted'>${t("datasets.hf_no")}</span>`}</td>
          <td class='muted'>${esc(x.format)}</td>
          <td class='muted'>${esc((x.created_at || "").slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class='muted' style='margin-top:6px;font-size:11.5px'>${t("datasets.footer_lead")}${escAttr(d.out_dir)}</div>`;
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
    if (!p.ok) { el.innerHTML = `<div class='panel'><b class='title'>${t("datasets.preview_lead")}${escAttr(name)}</b><span style="color:var(--err)">${esc((p.errors || []).join("; "))}</span></div>`; return; }
    const cols = p.columns || [];
    const fmtCell = (val) => {
      if (val == null) return "<span class='muted'>-</span>";
      if (typeof val === "number") return String(+val.toFixed(6));
      if (typeof val === "object") return `<code>${esc(JSON.stringify(val))}</code>`;
      return esc(String(val));
    };
    el.innerHTML = `<div class='panel'><b class='title'>${t("datasets.pl_lead")}${esc(p.dataset)}（${p.filters?.model ? t("datasets.pl_fam_tpl", { m: esc(p.filters.model) }) : ""}${t("datasets.pl_tail_tpl", { n: esc(p.n_rows) })}）</b>
      <div style='overflow:auto;max-height:420px'><table><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${(p.rows || []).map((r) => `<tr>${cols.map((c) => `<td>${fmtCell(r[c])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div></div>`;
  }
}

/* ═══ 标定锚（锚注册表 + 新鲜度，只读）═══ */
export async function pageAnchors() {
  const v = T.$("view-anchors");
  v.innerHTML = help(`
    <li>${t("anchors.help_1")}</li>
    <li><b>${t("anchors.help_2_core")}</b>${t("anchors.help_2_tail")}</li>
    <li>${t("anchors.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='anchors.title'>${t("anchors.title")}</span> <small data-i18n='anchors.subtitle'>${t("anchors.subtitle")}</small></h2>
     <div class='panel'><div class='toolbar'>
       <span id='an-kpi' class='muted'>${t("anchors.loading")}</span>
       <button class='minor' id='an-reload' data-i18n='anchors.reload'>${t("anchors.reload")}</button></div>
     <div id='an-body'></div></div>
     <div id='an-detail'></div>`;
  applyI18nRoot(v); // 壳静态标注首扫
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
      t("anchors.kpi_lead") + `<b>${d.count}</b>` + t("anchors.kpi_count_tpl", { n: d.expected_count }) +
      (d.stale_count ? T.badge(`${d.stale_count} stale`, "warn") : T.badge("0 stale", "ok")) + " " +
      (d.no_date_count ? T.badge(t("anchors.badge_nodate_tpl", { n: d.no_date_count }), "muted") : "");
    if (d.load_errors?.length)
      body.insertAdjacentHTML("beforeend",
        `<div style="color:var(--err);margin-bottom:var(--space-2)">${t("anchors.load_warn_lead")}${esc(d.load_errors.join("; "))}</div>`);
    // A7-A ui-kit：锚状态→类单源（kitBadge 查 KIT_STATUS_CLS；未知状态
    // 一律 muted——原查表回退同串；无状态 UNKNOWN 同串）
    const stBadge = (st) => kitBadge(st || "UNKNOWN", st);
    body.insertAdjacentHTML("beforeend",
      "<table><thead><tr><th scope='col'>anchor_id</th>" +
      `<th scope='col'>${t("anchors.th_status")}</th><th scope='col'>${t("anchors.th_kind")}</th>` +
      `<th scope='col'>${t("anchors.th_family")}</th><th scope='col'>${t("anchors.th_quantity")}</th>` +
      `<th scope='col'>${t("anchors.th_engine")}</th><th scope='col'>${t("anchors.th_fresh")}</th>` +
      "</tr></thead><tbody>" +
      (d.anchors || []).map((a) => {
        const si = a.stale_info || {};
        const fresh = si.stale === true
          ? T.badge(t("anchors.fresh_stale_tpl", { n: si.age_days }), "warn")
          : si.stale === false ? T.badge(t("anchors.fresh_ok"), "ok")
          : T.badge(t("anchors.fresh_unknown"), "muted");
        const unit = a.quantity?.unit ? ` ${esc(a.quantity.unit)}` : "";
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
        return `<tr class='clickable' data-id='${escAttr(a.anchor_id)}' ${kitClickRowAttrs({ role: null, label: t("anchors.aria_detail_tpl", { name: (a.anchor_id || "") }) })}>
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
        ? `<div class='panel'><b class='title'>${t("anchors.detail_lead")}${esc(det.anchor.anchor_id)}</b><pre>${esc(JSON.stringify(det.anchor, null, 2))}</pre></div>`
        : `<div class='panel'><span style="color:var(--err)">${esc(det.error || t("anchors.detail_unreadable"))}</span></div>`;
    }, "tr.clickable");
  };
  T.$("an-reload").onclick = load;
  await load();
}

/* ═══ UQ 不确定度（代理蒙特卡洛良率 + 敏感性；数值只在确定性内核）═══ */
export async function pageUq() {
  const v = T.$("view-uq");
  v.innerHTML = help(`
    <li>${t("uq.help_1")}</li>
    <li>${t("uq.help_2_lead")}<b>${t("uq.help_2_core")}</b>${t("uq.help_2_tail")}</li>
    <li>${t("uq.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='uq.title'>${t("uq.title")}</span> <small data-i18n='uq.subtitle'>${t("uq.subtitle")}</small></h2>
     ${kitPanelHead(t("uq.panel_assets"))}
       <div id='uq-assets' class='muted'>${t("uq.loading")}</div></div>
     <div class='panel'><b class='title'>${t("uq.panel_run")}</b>
       <div class='toolbar'>${t("uq.label_samples")}<input id='uq-path' style='flex:1;min-width:280px' placeholder='runs/xxx/calibration/samples.json'>
         ${t("uq.label_kind")}<select id='uq-kind'><option>poly_ridge</option><option>nn</option></select>
         ${t("uq.label_draws")}<input id='uq-n' value='10000' size='7'> seed: <input id='uq-seed' value='42' size='5'>
         <button class='act' id='uq-run'>${t("uq.run")}</button><span id='uq-spin'></span></div>
       <div id='uq-tol' class='muted' style='margin-top:6px'>${t("uq.tol_hint")}</div></div>
     <div id='uq-result'></div>`;
  applyI18nRoot(v); // 壳静态标注首扫
  const assets = await apiFetch("/api/uq/samples", { signal: viewSignal("uq") });
  if (assets.aborted) return; // UI-R12：切页取消——不写隐藏区
  const el = T.$("uq-assets");
  if (!assets.ok) { el.innerHTML = `<span style="color:var(--err)">${esc((assets.errors || []).join("; "))}</span>`; return; }
  if (!(assets.items || []).length) {
    el.innerHTML = `<span class='muted'>${t("uq.empty_assets")}</span>`;
  } else {
    el.innerHTML = "<table><thead><tr>" +
      `<th scope='col'>${t("uq.th_file")}</th><th scope='col'>${t("uq.th_samples")}</th>` +
      `<th scope='col'>${t("uq.th_objectives")}</th><th scope='col'>${t("uq.th_bounds")}</th>` +
      `<th scope='col'>${t("uq.th_mtime")}</th>` +
      "</tr></thead><tbody>" +
      assets.items.map((it) => {
        const n = it.parsed ? `${esc(it.n_samples)}` : `<span class='muted'>${t("uq.unparsed")}</span>`;
        // UI-R4：键盘可达（tr 行 role:null 保 row/cell 语义；aria-label 行动作）
        return `<tr class='clickable' data-p='${escAttr(it.path)}' ${kitClickRowAttrs({ role: null, label: t("uq.aria_pick_tpl", { name: (it.path || "") }) })}>
          <td><b>${esc(it.path)}</b></td><td>${n}</td>
          <td class='muted'>${it.parsed ? esc(it.n_objectives ?? "-") : "-"}</td>
          <td class='muted'>${esc((it.bounds_params || []).join("、")) || "-"}</td>
          <td class='muted'>${esc(new Date(it.mtime * 1000).toISOString().slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      (assets.truncated ? `<div class='muted' style='margin-top:var(--space-1)'>${t("uq.truncated")}</div>` : "");
    bindClickRows(el, (tr) => pickAsset(tr.dataset.p), "tr.clickable"); // UI-R4：click/Enter/Space 同一激活
  }
  async function pickAsset(path) {
    T.$("uq-path").value = path;
    const item = (assets.items || []).find((x) => x.path === path);
    const params = (item && item.bounds_params) || [];
    // UI-R11（A6 P2-7 可测试性半边）：pg-s-* 惯例 id（key() 消毒参数名）
    const key = (v) => String(v).replace(/\W/g, "_");
    T.$("uq-tol").innerHTML = params.length
      ? "<table><thead><tr>" +
        `<th scope='col'>${t("uq.th_param")}</th><th scope='col'>${t("uq.th_sigma")}</th>` +
        "</tr></thead><tbody>" +
        params.map((n) => `<tr><td><b>${esc(n)}</b></td><td><input id='uq-sig-${key(n)}' class='uq-sigma' data-p='${escAttr(n)}' size='12' step='any' placeholder='${t("uq.sigma_ph")}' aria-label='${t("uq.sigma_aria_tpl", { n: escAttr(n) })}'></td></tr>`).join("") +
        "</tbody></table>"
      : t("uq.no_bounds");
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
    if (bad) return T.msg(t("uq.err_sigma_tpl", { p: bad }), false);
    if (!Object.keys(tolerances).length) return T.msg(t("uq.err_sigma_empty"), false);
    const btn = T.$("uq-run");
    btn.disabled = true; T.$("uq-spin").innerHTML = "<span class='spin'></span>";
    const r = await apiFetch("/api/uq/yield", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples_path: T.$("uq-path").value.trim(),
                             tolerances, n: parseInt(T.$("uq-n").value) || 10000,
                             seed: parseInt(T.$("uq-seed").value) || 42,
                             kind: T.$("uq-kind").value }),
      signal: viewSignal("uq"), // UI-R12：统一 API 层（token 透传/切页取消）
      timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：万点重采样分钟级
    });
    btn.disabled = false; T.$("uq-spin").innerHTML = "";
    if (r.aborted) return; // UI-R12：切页取消——不写隐藏区（按钮态已在上方复位）
    renderUqResult(r);
  };

  function renderUqResult(r) {
    const el = T.$("uq-result");
    if (!r.ok) {
      el.innerHTML = `<div class='panel'><span style="color:var(--err)">${t("uq.err_lead")}${esc((r.errors || [t("uq.unknown_error")]).join("; "))}</span></div>`;
      return;
    }
    const yPct = (r.yield_rate * 100).toFixed(1) + "%";
    const yCls = r.yield_rate >= 0.9 ? "ok" : r.yield_rate >= 0.7 ? "warn" : "err";
    const stats = Object.entries(r.metric_stats || {});
    const deltas = r.sensitivity_violation_delta || {};
    const maxD = Math.max(...Object.values(deltas).map((x) => Math.abs(x)), 1e-12);
    el.innerHTML = `<div class='cards'>
        <div class='card'><div class='k'>${t("uq.k_yield")}</div><div class='v ${yCls}'>${yPct}</div></div>
        <div class='card'><div class='k'>${t("uq.k_draws")}</div><div class='v'>${r.n_draws}</div></div>
        <div class='card'><div class='k'>${t("uq.k_kind")}</div><div class='v'>${esc(r.surrogate_kind)}</div></div>
        <div class='card'><div class='k'>${t("uq.k_nominal")}</div><div class='v'>${t("uq.stats_count_tpl", { n: stats.length })}</div></div>
      </div>
      <div class='grid2'>
        ${kitPanelHead(t("uq.metric_dist_title"))}
          ${kitTable({
            columns: [t("uq.th_metric"), "mean", "std", "q05", "q95"],
            rowsHtml: stats.map(([m, s]) => `<tr><td><b>${esc(m)}</b></td><td>${(+s.mean).toFixed(4)}</td><td>${(+s.std).toFixed(4)}</td><td>${(+s.q05).toFixed(4)}</td><td>${(+s.q95).toFixed(4)}</td></tr>`).join(""),
            empty: `<tr><td colspan='5' class='muted'>${t("uq.none")}</td></tr>`,
          })}
          <div class='muted' style='margin-top:6px;font-size:11.5px'>${t("uq.nominal_lead")}${esc(JSON.stringify(r.nominal_params))}<br>${t("uq.impl_lead")}${esc(r.implementation || "-")} · ${t("uq.uncert_lead")}${esc(r.uncertainty_status ?? "-")}</div></div>
        <div class='panel'><b class='title'>${t("uq.sens_title")}</b>
          ${(r.sensitivity_ranking || []).map((p) => {
            const dv = Math.abs(deltas[p] || 0);
            return `<div style='margin-bottom:var(--space-2)'><b>${esc(p)}</b> <span class='muted'>|Δ|=${dv.toFixed(5)}</span>
              <div style='height:8px;border-radius:4px;background:var(--panel2);margin-top:3px'>
              <div style='height:8px;border-radius:4px;width:${(dv / maxD * 100).toFixed(1)}%;background:var(--accent)'></div></div></div>`;
          }).join("") || `<span class='muted'>${t("uq.none")}</span>`}
          <div class='muted' style='margin-top:6px;font-size:11.5px'>${t("uq.sens_note")}</div></div>
      </div>`;
    T.msg(t("uq.done_msg"), true);
  }
}

/* ═══ R-1（架构批 W4-S17）：PageContext 增量钩子（数据资产三页）════════
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
