/* rfauto UI 主题单源（aurora72 A5-B，R6 审计 R-4）：主题判定与双档调色板
   的唯一出处。此前 pages.js 22 处 body.light 判定 + 30 处 `light ? … : …`
   双档三元、app.js CHART_COLORS 表与 pages.js timeline 整档镜像、热图色带
   三份字面量各自为政——镜像纪律是"本层不可 import"的被迫产物（旧注释
   自认），本模块**零依赖、零顶层 DOM 执行**（node 行为钉可裸 import，
   palette.js 先例），app.js/pages.js 同源 import 后镜像注释全拆。
   API 面：
   - themeIsLight(mode, systemPrefersLight)——mode→浅色纯判定真值表
     （pages.js 兼容 re-export；node 行为钉 test_ui_a11y_theme/lifecycle）；
   - bodyIsLight()——DOM 现取 body.light 信号（echarts/canvas 渲染时点）；
   - applyThemeDom(mode)——html[data-theme]（设计系统变量面）+ body.light
     （图表消费面信号）双写单点（与 index.html head 防闪 boot 同口径；
     boot 内联脚本读 localStorage 的键名与语义零变化，CSP 哈希不受扰）；
   - chartPalette(light)——CHART_COLORS dark/light 档单源（对比度核算
     runs/pr1_contrast/；ocean --plot-bg #091525 实测最低 #ba68c8 5.15:1，
     两暗主题共用 dark 档的已固化结论钉在 tests/unit/test_ui_nav_focus.py）；
   - themePick(light, pair) + THEME_COLORS——散置双档色三元逐对收编表；
   - HEAT_BAND——场切片/远场 3D/工具页热图色带单源（旧三份镜像收编）；
   - THEME_KEY / THEME_MODES / THEME_LABEL——主题常量单源。 */

/* 主题持久化键（index.html head 防闪 boot 同键读档——键名不得改；
   test_ui_theme_boot 钉 boot 与本单源一致）。 */
export const THEME_KEY = "rfauto-theme";

/* v5.0 Aurora 四态；"dark" 为旧存量别名（=midnight，读档/set 时映射）。 */
export const THEME_MODES = ["midnight", "ocean", "light", "system"];

/* 主题切换按钮四态标签（pages.js paintBtn 消费）。 */
export const THEME_LABEL = {
  midnight: "🌌 Midnight",
  ocean: "🌊 Ocean",
  light: "☀ 浅色",
  system: "🖥 跟随系统",
};

/* 纯函数（node 行为钉可测）：mode → body 是否应为浅色。
   "dark" 为旧存量别名（=midnight，深色）。 */
export function themeIsLight(mode, systemPrefersLight) {
  if (mode === "light") return true;
  if (mode === "midnight" || mode === "ocean" || mode === "dark") return false;
  return !!systemPrefersLight; // system（含未知值兜底）
}

/* 系统浅色偏好（window/matchMedia 缺席守卫，node → false=深档兜底）。 */
export function systemPrefersLight() {
  try {
    return !!(typeof window !== "undefined" && window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: light)").matches);
  } catch { return false; }
}

/* DOM 双写单源：mode（四态）→ html[data-theme] + body.light 一次落位，
   返回解算档（"light"/"midnight"）。document/body 缺席（node import、
   异常部署）时静默返回 null（#105 best-effort：主题面不得成为业务主路径
   故障点）。旧 pages.js _applyThemeDom/initPages.apply 两份同构实现收编
   于此。 */
export function applyThemeDom(mode) {
  if (typeof document === "undefined" || !document.documentElement ||
      !document.body) return null;
  const r = mode === "system" ? (systemPrefersLight() ? "light" : "midnight") : mode;
  document.documentElement.dataset.theme = r;
  document.body.classList.toggle("light", r === "light");
  return r;
}

/* DOM 现取：body.light 信号（各图表/3D 渲染时点与重绘时点读取）。
   document/body 缺席 → false（深档兜底，与 applyThemeDom 同守卫口径）。 */
export function bodyIsLight() {
  try {
    return typeof document !== "undefined" && !!document.body &&
      document.body.classList.contains("light");
  } catch { return false; }
}

/* PR-1 对比度：图表系列调色板按主题分档（核算见 runs/pr1_contrast/）。
   深色档对 midnight --plot-bg #0d1322 与 ocean --plot-bg #091525 逐色
   ≥3:1（WCAG 图形；ocean 复核 2026-10-11 W2-C，最低 #ba68c8 5.15:1，
   钉在 tests/unit/test_ui_nav_focus.py）——两暗主题共用 dark 档成立，
   无需第三档。浅色档对白底逐色 ≥3:1。显式 s.color 仍优先——调色板只
   兜底缺省系列。字面量形状（const CHART_COLORS = {…}）被对比度钉
   （test_ui_a11y_theme/test_ui_nav_focus）按文本解析，勿改结构。 */
const CHART_COLORS = {
  dark: ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"],
  light: ["#0277bd", "#b26a00", "#276b2c", "#c62828", "#6a1b9a"],
};

/* 档位取值：light=true → 浅档，否则深档。drawLineChart/drawEChart/
   uiPlotCard 与 pages.js 各管线统一入口（行为与旧
   `CHART_COLORS[light ? "light" : "dark"]` 逐字节一致）。 */
export function chartPalette(light) {
  return CHART_COLORS[light ? "light" : "dark"];
}

/* Smith 圆图轨迹色（drawSmith 消费）：CHART_COLORS 五档 + 第 6 档。
   第 6 档取值冻结（A5-B 迁移零改值；原 drawSmith 内 light 三元镜像收编）。 */
const SMITH_SIXTH = { light: "#0e8f74", dark: "#fff176" };

export function smithPalette(light) {
  return [...chartPalette(light), themePick(light, SMITH_SIXTH)];
}

/* 双档色表（R-4 镜像收编）：此前散在 pages.js/app.js 的 `light ? "#…" : "#…"`
   三元逐对迁入，键=消费语义，取值一律经 themePick(light, THEME_COLORS.x)。
   数值冻结：迁移零改值（渲染不变铁律）；改值须复核对比度账本
   runs/pr1_contrast/ 与 test_ui_a11y_theme/test_ui_nav_focus 双钉。 */
export const THEME_COLORS = {
  fg: { light: "#1b2330", dark: "#dce3ee" },            // 图表前景（轴题/图例/canvas 文字）
  plotBg: { light: "#ffffff", dark: "#0d1118" },        // 图表导出 PNG 底色（2x）
  grid: { light: "#dde3ec", dark: "#1c2331" },          // drawLineChart 网格线（装饰性）
  read: { light: "#5f6a80", dark: "#7d8aa0" },          // drawLineChart 刻度文字（对底 ≥4.5:1）
  toolAxisLine: { light: "#7f899d", dark: "#5f6a80" },  // 工具页折线轴轴线
  toolAxisLabel: { light: "#5b6780", dark: "#8391a7" }, // 工具页折线轴刻度
  toolSplitLine: { light: "#e7ebf2", dark: "#1c2331" }, // 工具页折线分隔线
  smithGrid: { light: "#b8c2d2", dark: "#3a4458" },     // Smith 圆图网格
  seriesBlue: { light: "#0277bd", dark: "#4fc3f7" },    // 显式系列色·蓝
  seriesOrange: { light: "#b26a00", dark: "#ffb74d" },  // 显式系列色·橙
  seriesTeal: { light: "#0e8f74", dark: "#22d3a5" },    // 显式系列色·青绿
  seriesRed: { light: "#b3261e", dark: "#ef5350" },     // 显式系列色·红（不可行点）
  emptyCell: { light: "#e5e9f0", dark: "#1a2130" },     // 热图空格灰（feasibility/costHeat）
  /* UI-R12（aurora_d 前端深化席）任务3 CSS 审计收编：以下两键为"冻结现值"
     单源迁移（迁移零改值铁律——原视图内联字面量对双主题同值，故两档同值；
     重定标须先复核对比度账本 runs/pr1_contrast/ 与消费页渲染）。 */
  fieldAxisLine: { light: "#55607a", dark: "#55607a" }, // 场/远场极坐标轴线（view_fieldviz）
  calibNullCost: { light: "#8391a7", dark: "#8391a7" }, // 校准散点 cost 缺失兜底色（view_calibration）
};

/* 双档取值助手：themePick(light, pair) = pair[light ? "light" : "dark"]。 */
export function themePick(light, pair) {
  return light ? pair.light : pair.dark;
}

/* 场切片/远场 3D/工具页热图色带（值域单调档；旧 pages.js 三份字面量
   镜像收编为单源）。 */
export const HEAT_BAND = [
  "#0d1118", "#1e3a8a", "#2563eb", "#22c55e", "#facc15", "#ef4444", "#ffffff",
];

/* 场切片等值线分档色（view_fieldviz levelColors 单源收编，UI-R12 任务3；
   冻结现值零改值——白/黄/橙三档按等值级数取模循环，重定标须复核热图
   底色可辨识度）。 */
export const ISO_BAND = ["#ffffff", "#ffeb3b", "#ff5722"];
