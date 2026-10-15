/* rfauto 使用指南页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）。 */

import { T } from "./context.js";
import { help } from "./dom.js";

/* ═══ 使用指南 ═══ */
export function pageGuide() {
  const v = T.$("view-guide");
  v.innerHTML = help(`
    <li>本页 = 内置说明书。第一次用？按下面 4 步走一遍 fake 演示即可上手。</li>
    <li>随时可以回「总览」点「＋ 添加组件」定制你想盯的面板。</li>`) +
    `<h2 class='page'>使用指南 <small>写给第一次接触 rfauto 的你</small></h2>
    <div class='panel'><b class='title'>rfauto 是做什么的</b>
      <p>HFSS/ADS 这类电磁仿真很慢，直接在真机上反复试参数代价很高。rfauto 的思路是：
      <b>用快速代理（fake/openEMS）先粗筛参数 → 再用 HFSS/ADS 精算少数候选</b>，
      并用 P0 门禁（排序一致性 recall≥80%）保证"粗筛挑出来的确实靠谱"。</p></div>
    <div class='panel'><b class='title'>5 分钟上手路线</b>
      <div class='guide-flow'>
        <div class='guide-step'><span class='n'>1</span><b>工程导入</b><div>读入你的 HFSS 工程（.aedt），勾选要调的变量。</div></div>
        <div class='guide-step'><span class='n'>2</span><b>配方编辑</b><div>补 objectives（什么算"好"，如带内 S11&lt;-15dB），确认优化范围。</div></div>
        <div class='guide-step'><span class='n'>3</span><b>优化调参</b><div>先用 fake adapter 跑通流程（秒级），再切 hfss 真机精算。</div></div>
        <div class='guide-step'><span class='n'>4</span><b>Run 历史</b><div>看 S 参数曲线与指标，best_params 就是推荐工作点。</div></div>
      </div></div>
    <div class='panel'><b class='title'>概念速查</b>
      <table class="glossary"><tbody>
        <tr><td>配方 (recipe)</td><td>一次仿真的完整定义：模型 + 参数 + 扫频 + 目标 + 优化设置（YAML 文件）。</td></tr>
        <tr><td>Run</td><td>配方的一次实际执行；每个 run 有 id、指标、S 参数曲线和产物存档。</td></tr>
        <tr><td>adapter</td><td>执行仿真的通道：fake（秒级解析演示）/ openEMS（免费 FDTD）/ HFSS（商业真机）。</td></tr>
        <tr><td>objectives</td><td>"什么算好"的裁判，如「带内 S11 最大值低于 -15dB」。优化器按它打分。</td></tr>
        <tr><td>多保真</td><td>fake 粗筛 + 高保真精算的两阶段流程；靠 P0 gate 保证排序一致性。</td></tr>
        <tr><td>P0 gate</td><td>可信度验收：fake 与高保真对同一批参数的排名 Spearman ρ≥0.8 且 top-5 命中≥80%。</td></tr>
        <tr><td>Agent 三层 Gate</td><td>LLM 提参数 → L1/L2 自动校验 → 生成 token → 你在收件箱批准才执行。</td></tr>
      </tbody></table></div>
    <div class='panel'><b class='title'>常见问题</b>
      <li><b>为什么第一次都建议跑 fake？</b> fake 秒级返回，先确认配方的目标/范围写得对，再上真机不浪费 license 时间。</li>
      <li><b>调参结果 plateau 在 -6dB？</b> 通常是结构级失配（线宽/端口归一化），纯几何调参到顶了——先审模型再调参。</li>
      <li><b>HFSS 用哪个版本？</b> 以实装版本为准（本机实测 2025 R1/v251）；工程导入页版本留空即跟随服务端缺省，无需手选。</li>
      <li><b>openEMS 第一次跑很慢？</b> 真实谐振结构要跑满能量衰减（旧参考里 280s 是坏模型的假快）。结果会缓存，同配置秒回。</li>
      </div>
    <div class='panel'><b class='title'>下一步去哪</b>
      <li>深入口径与踩坑：仓库 <span class="muted">docs/rf_template_references.md</span> 与 。</li>
      <li>想看某个页面怎么用：每个页面顶部都有「❓ 本页说明」。</li></div>`;
}
