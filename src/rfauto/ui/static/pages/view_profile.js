/* rfauto 剖析页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，PR-8）：
   py-spy 火焰图落 runs/（可选依赖如实降级）。 */

import { T } from "./context.js";
import { esc, help } from "./dom.js";

/* ═══ PR-8 剖析入口（ge8b Wave B 席B2）：py-spy 火焰图落 runs/ ═══
   py-spy 为可选依赖：未装=状态卡如实"未安装"+安装提示（不假装可用）。 */
export async function pageProfile() {
  const v = T.$("view-profile");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>封装 <code>py-spy record</code>（MIT）：对运行中进程（pid）或新起命令采样，产物落 runs/profile/（flamegraph .svg 浏览器直接看 / speedscope .json 可交互）。</li>
      <li>py-spy 缺装时本页如实降级：<code>pip install py-spy</code> 后刷新即可。</li>
      <li>剖析是开发面工具：只读采样不改业务状态；Windows 下附着其他用户进程需管理员。</li>`) +
    `<h2 class='page'>剖析 <small>py-spy 火焰图（PR-8）</small></h2>
     <div class='panel'><b class='title'>环境</b> <span id='pf-status' class='muted'>检测中...</span></div>
     <div class='panel' style='margin-top:var(--space-3)'>
       <b class='title'>采样</b>
       <div class='toolbar' style='margin-top:6px'>
         <b>目标</b><select id='pf-target'><option value='pid'>附着进程 pid</option><option value='cmd'>新起命令</option></select>
         <input id='pf-pid' size='10' placeholder='pid'>
         <input id='pf-cmd' size='34' placeholder='python scripts/x.py --flag（空格分词）'>
       </div>
       <div class='toolbar'>
         <b>时长 s</b><input id='pf-dur' value='30' style='width:70px'>
         <b>频率 Hz</b><input id='pf-rate' value='100' style='width:80px'>
         <b>格式</b><select id='pf-fmt'><option value='flamegraph'>flamegraph (.svg)</option><option value='speedscope'>speedscope (.json)</option></select>
         <button class='primary' id='pf-run'>开始采样</button>
         <span id='pf-msg' class='muted'></span>
       </div>
       <div id='pf-result' class='muted' style='margin-top:var(--space-2)'></div>
     </div>`;
  const st = await T.api("/api/profile");
  T.$("pf-status").innerHTML = st.available
    ? `<span style='color:var(--ok)'>py-spy 可用（${esc(st.exe)}）</span>`
    : `<span style='color:var(--warn)'>${esc(st.hint || "py-spy 未安装")}</span>`;
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
    T.$("pf-msg").textContent = "采样中（页面可切走，采样在服务端）...";
    const r = await T.api("/api/profile", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    T.$("pf-msg").textContent = "";
    const el = T.$("pf-result");
    if (!r.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((r.errors || [r.error]).filter(Boolean).join("; "))}</span>`; return; }
    el.textContent = `✓ 产物：${r.output_path}（${r.fmt} · ${r.duration_s}s @ ${r.rate_hz}Hz）——runs/ 静态挂载开启时可直接在浏览器打开`;
  };
}
