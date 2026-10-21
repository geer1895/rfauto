/* rfauto 剖析页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，PR-8）：
   py-spy 火焰图落 runs/（可选依赖如实降级）。
   i18n（发布前软编码批 S2 全清）：help 块分段 t()、标题/面板头/表单标签/
   选项/占位/状态行/结果行全迁词表（profile.* 键域，zh 与旧字面逐字节同、
   en 新增）；采样结果行的产物路径/fmt 为 API 数据照旧模板外拼（textContent
   直写零转义需求），词表只出文案段。 */

import { T } from "./context.js";
import { esc, errorText, help } from "./dom.js";
// i18n（发布前软编码批 S2）：壳静态标签 data-i18n+首扫；状态/结果行动态
// 容器文案 t() 渲染期烘焙。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 2 点）——
// 数据面（py-spy 环境检测）接 viewSignal("profile") 切页收束 + aborted 短路；
// 动作面（开始采样 POST）保持无 signal——采样在服务端持续（页面可切走），
// 用户动作不被切页取消。P2-1（aurora_g W3-S2 审查，W4-S1 修复）：POST 加
// timeoutMs:0 长跑豁免——profile_run 同步阻塞 duration_s（缺省 30s 与
// apiFetch 缺省超时恰好竞速必现假"请求超时"），调大采样时长同理。
import { apiFetch, viewSignal } from "./api.js";
// W14-S2 错误呈现归一（R2 Top10 #4）：采样失败点内联 ✗ span → kitErrorPanel
// 单源（三态 kit 续波——本页原为零三态余量文件，错误态自此收编）。
// R4 交互细节批：长操作按钮三态（kitBtnBusy）——采样同步阻塞 duration_s，
// busy 期 disabled+spinner 防重复触发。
import { kitBtnBusy, kitErrorPanel } from "./kit.js";

/* ═══ PR-8 剖析入口（ge8b Wave B 席B2）：py-spy 火焰图落 runs/ ═══
   py-spy 为可选依赖：未装=状态卡如实"未安装"+安装提示（不假装可用）。 */
export async function pageProfile() {
  const v = T.$("view-profile");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("profile.help_1_lead")}<code>py-spy record</code>${t("profile.help_1_tail")}</li>
      <li>${t("profile.help_2_lead")}<code>pip install py-spy</code>${t("profile.help_2_tail")}</li>
      <li>${t("profile.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='profile.title'>${t("profile.title")}</span> <small data-i18n='profile.subtitle'>${t("profile.subtitle")}</small></h2>
     <div class='panel'><b class='title' data-i18n='profile.env_title'>${t("profile.env_title")}</b> <span id='pf-status' class='muted'>${t("profile.detecting")}</span></div>
     <div class='panel' style='margin-top:var(--space-3)'>
       <b class='title' data-i18n='profile.sampling_title'>${t("profile.sampling_title")}</b>
       <div class='toolbar' style='margin-top:6px'>
         <b data-i18n='profile.target_label'>${t("profile.target_label")}</b><select id='pf-target'><option value='pid'>${t("profile.target_pid")}</option><option value='cmd'>${t("profile.target_cmd")}</option></select>
         <input id='pf-pid' size='10' placeholder='pid'>
         <input id='pf-cmd' size='34' placeholder='${t("profile.cmd_placeholder")}' data-i18n-ph='profile.cmd_placeholder'>
       </div>
       <div class='toolbar'>
         <b data-i18n='profile.dur_label'>${t("profile.dur_label")}</b><input id='pf-dur' value='30' style='width:70px'>
         <b data-i18n='profile.rate_label'>${t("profile.rate_label")}</b><input id='pf-rate' value='100' style='width:80px'>
         <b data-i18n='profile.fmt_label'>${t("profile.fmt_label")}</b><select id='pf-fmt'><option value='flamegraph'>flamegraph (.svg)</option><option value='speedscope'>speedscope (.json)</option></select>
         <button class='primary' id='pf-run' data-i18n='profile.run'>${t("profile.run")}</button>
         <span id='pf-msg' class='muted'></span>
       </div>
       <div id='pf-result' class='muted' style='margin-top:var(--space-2)'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（幂等，动态容器走 t() 烘焙）
  const st = await apiFetch("/api/profile", { signal: viewSignal("profile") });
  if (st.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  T.$("pf-status").innerHTML = st.available
    ? `<span style='color:var(--ok)'>${t("profile.status_ok_lead")}${esc(st.exe)}${t("profile.status_ok_tail")}</span>`
    : `<span style='color:var(--warn)'>${esc(st.hint || t("profile.status_missing"))}</span>`;
  const syncTarget = () => {
    const mode = T.$("pf-target").value;
    T.$("pf-pid").style.display = mode === "pid" ? "" : "none";
    T.$("pf-cmd").style.display = mode === "cmd" ? "" : "none";
  };
  T.$("pf-target").onchange = syncTarget; syncTarget();
  T.$("pf-run").onclick = async () => {
    const mode = T.$("pf-target").value;
    const body = {
      duration_s: Number(T.$("pf-dur").value || 30),
      rate_hz: Number(T.$("pf-rate").value || 100),
      fmt: T.$("pf-fmt").value,
    };
    if (mode === "pid") body.pid = T.$("pf-pid").value.trim();
    else body.cmd = T.$("pf-cmd").value.trim().split(/\s+/).filter(Boolean);
    const btn = T.$("pf-run");
    kitBtnBusy(btn, true); // R4 三态：采样同步阻塞 duration_s（≥30s）
    T.$("pf-msg").textContent = t("profile.sampling_msg");
    const r = await apiFetch("/api/profile", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), timeoutMs: 0 });
    kitBtnBusy(btn, false);
    T.$("pf-msg").textContent = "";
    const el = T.$("pf-result");
    if (!r.ok) { el.innerHTML = kitErrorPanel(errorText(r)); return; } // W14-S2 归一（R2 #4）
    el.textContent = t("profile.result_lead") +
      `${r.output_path}（${r.fmt} · ${r.duration_s}s @ ${r.rate_hz}Hz）` +
      t("profile.result_tail");
  };
}

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 profileCtx ═══════════
   refresh=py-spy 可用性状态重拉（pageProfile 幂等——壳判 innerHTML 已在即
   跳过，采样表单态保留；无轮询面，leave 不需要）。 */
export const profileCtx = {
  refresh: () => pageProfile(),
};
