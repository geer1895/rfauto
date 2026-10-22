/* rfauto 文献/官方例验收参考值数据模块（aurora_i 人性化三批 R2，R3 设计
   §2③ 的轻量落地：不新增端点、不建 YAML——前端常量单文件；值逐条转录自
   docs/rf_template_references.md 验收基准节（#97 数字口径：每条带 source
   段落出处，转录漂移由 tests/unit/test_ui_cred_lit_lines.py 钉值断言兜住
   ——出处锚在原文可 grep 复核）。

   零 DOM 零 t()（图例标签由消费视图烘焙——cred_curves.js 同款纪律）；
   消费面=view_gallery.js 抽屉「对照曲线」节 + view_sparams.js「对照」卡：
   叠加图第三线=@f0 验收值的水平参考线（青绿），让使用者一眼看到
   "我们的引擎结果与教科书/厂商手册口径同量级"。

   形态学（重要）：plotCard 折线族 category 轴=series[0].x（plotcard.js
   plotCardOption 单源构造），故水平参考线必须采样在首引擎曲线同一频网
   上（litSeriesFor 内建采样），且消费面必须把参考线追加在引擎系列之后
   （首系列决定轴网——引擎线在前的既有次序不动）。参考值锚定 @f0 验收
   基准口径，带内全程画水平线只作"量级对照"呈现（语义由消费面教学行
   i18n 说明，本模块不承载文案）。

   登记纪律（铁律 7 同族）：只转录 docs 面显式数值，不推导不补算——
   无显式文献验收 dB 值的模板（gysel/marchand_balun/patch_array_2x2/
   stepped_impedance/coupled_line 等）诚实缺席本表，不造参考线。 */

import { THEME_COLORS, themePick } from "../theme.js";

/* 转录源文档（单一出处；下表 source 段逐条指回该文档节号）。 */
export const LIT_SOURCE_DOC = "docs/rf_template_references.md";

/* 参考线着色（theme.js 单源色对：青绿=文献/官方例参考档——与 HFSS 橙/
   openEMS 蓝引擎色区分；档位经 themePick(light) 由消费面按当前主题取）。 */
export const LIT_LINE_COLOR_PAIR = THEME_COLORS.seriesTeal;

/* 文献/官方例验收参考值注册表（键=模板名；points.curve=叠加图内 S 参数
   曲线名，points.db=@f0 验收值 dB——只画图内已有同名曲线的参考点）。 */
export const LIT_REFS = {
  wilkinson: {
    source: LIT_SOURCE_DOC +
      " sec.1 (Ansys official FDTD example / Pozar Ex. 7.2, acceptance @f0)",
    points: [
      { curve: "S11", db: -40 },
      { curve: "S31", db: -3 },
      { curve: "S32", db: -43 },
    ],
  },
  branchline: {
    source: LIT_SOURCE_DOC +
      " sec.13.2 (Pozar sec.7.5 single-section ideal: S21=-j/sqrt(2), S31=-1/sqrt(2))",
    points: [
      { curve: "S21", db: -3.01 },
      { curve: "S31", db: -3.01 },
    ],
  },
  branchline_2sect: {
    source: LIT_SOURCE_DOC +
      " sec.13.2 (Pozar sec.7.5 two-section ideal @f0: S21=-1/sqrt(2), S31=+j/sqrt(2))",
    points: [
      { curve: "S21", db: -3.01 },
      { curve: "S31", db: -3.01 },
    ],
  },
  ratrace: {
    source: LIT_SOURCE_DOC +
      " sec.9 (Pozar sec.7.5 ideal S-matrix -j/sqrt(2); ports 1=Sum 2=out1 3=Delta 4=out2)",
    points: [
      { curve: "S21", db: -3.01 },
      { curve: "S41", db: -3.01 },
    ],
  },
  lange: {
    source: LIT_SOURCE_DOC +
      " sec.13.3 (Pozar sec.7.6 Lange / Lange 1969: |S21|=|S31|=-3.01dB @f0)",
    points: [
      { curve: "S21", db: -3.01 },
      { curve: "S31", db: -3.01 },
    ],
  },
  cline_coupler: {
    source: LIT_SOURCE_DOC +
      " sec.13.1 (Pozar sec.7.6 10dB nominal, true-KJ non-synchronous @f0 residual)",
    points: [
      { curve: "S31", db: -10.045 },
      { curve: "S41", db: -23.3 },
      { curve: "S11", db: -32.9 },
    ],
  },
};

/* 模板注册查询（未注册/空表=null；消费面据此决定脚注与参考线有无）。 */
export function litRefOf(template) {
  const e = LIT_REFS[String(template || "")];
  return e && Array.isArray(e.points) && e.points.length ? e : null;
}

/* 文献参考水平线 series 组装（plotCard 契约 {name,x,y,color}）：
   - 采样网=curves[0].x（首引擎曲线=category 轴网，见头注形态学）；
   - 只画图内已有同名曲线的参考点（图里没有的 S 参数不画悬空参考线）；
   - labelOf(point)→图例名由消费视图烘焙（零 t() 纪律）；
   - 无注册/无曲线/轴网形态不合/无命中 → []（消费面零特判直拼）。 */
export function litSeriesFor(template, curves, labelOf, light) {
  const ref = litRefOf(template);
  if (!ref || !Array.isArray(curves) || !curves.length) return [];
  const x = curves[0].x;
  if (!Array.isArray(x) || !x.length ||
      !x.every((v) => Number.isFinite(+v))) return [];
  const present = new Set(curves.map((c) => String(c && c.name)));
  const color = themePick(!!light, LIT_LINE_COLOR_PAIR);
  const out = [];
  for (const p of ref.points) {
    if (!p || !present.has(String(p.curve))) continue;
    const v = +p.db;
    if (!Number.isFinite(v)) continue;
    out.push({
      name: typeof labelOf === "function" ? labelOf(p) : String(p.curve),
      x,
      y: x.map(() => v),
      color,
    });
  }
  return out;
}
