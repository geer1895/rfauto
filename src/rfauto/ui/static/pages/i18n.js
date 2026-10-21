/* rfauto UI i18n 骨架（aurora_f W1-S2；规格=runs/aurora_f/R1_ui_v8_audit.md
   §面2，W5-S23 决议"自研词表+t()"的实现落地）。

   ═══ 与 esc 体系共存纪律（R1 规格写死，违者返工）═══
   - t() 产出 = 开发侧可信文本（与既有字面同信任级）；API 动态数据照旧走
     esc/escAttr——禁止 t() 包数据、禁止把数据拼进词表值；
   - 词表值永不含 HTML（纯文本三个注入口：textContent / placeholder /
     aria-label，零 innerHTML）；
   - CSP：零内联脚本（zh 用户首帧零闪变；en 用户首帧闪 zh 在 localhost 可
     忽略；未来零闪变需第三个内联 boot 哈希钉——test_w1e_ui_csp +
     test_ui_theme_boot 双门同笔，v8 不做）。

   零依赖零构建：原生 ESM 相对 import，浏览器直跑；document/localStorage
   全 try/catch 守卫（node 行为钉可裸 import，#105 best-effort——i18n 面
   不得成为业务主路径故障点）。

   键命名：`<域>.<语义>`（nav.* / nav.group.* / common.* / palette.* /
   foot.* / tools.* / gallery.* / queue.* / dashboard.* / runs.* /
   detail.* / sparams.* / agent.* / timeline.* / datasets.* / anchors.* /
   uq.* / guide.*）。已收静态壳（index.html）+ 三试点页（tools/gallery/
   queue）+ W6-S21 扩面五页（dashboard/runs/detail/sparams/agent）+
   W8-S32 批 3（timeline 页接线=第 9 页 + dashboard 控件钮/KPI/activity/
   图表系列名深化 + help() 壳 summary 全站单点 + detail 骨架 aria +
   sparams 相位轴 + agent 对话浮窗静态面）+ W2-S1 批 4（aurora_g：
   TOP3 全迁 view_tools/view_data 三页/view_guide + kit.js 三串
   common.empty/load_failed/retry 单源化——kit 是 11 视图错误/空态单源，
   一处迁全站受益；view_tools 组名展示层翻译（协议标识符仍以中文单源，
   显示经 GROUP_I18N 映射）+ 计算器名/用途兜底表词表化（tools.cn_ 键/cp_ 键，
   calcZhName locale 感知）；help 块富 HTML=分段 t() 方案不变）；
   全量迁移（~1500 键/40 文件）按 W5-S23 口径后续分波（help 块富 HTML=
   分段 t() 方案，先例=view_dashboard help 块：结构留模板、纯文本段进
   词表，值零 HTML 纪律不变；guide/datasets 值中 &lt; 形态为渲染保真的
   字符实体非标签，进 innerHTML 模板语境渲染为字面 <）。 */

/* localStorage 语言档键（与 rfauto-theme 同族命名）。 */
export const LOCALE_KEY = "rfauto-locale";

/* 支持的语言档全集（键=locale 码；zh 缺省）。 */
export const LOCALE_MODES = ["zh", "en"];

/* ═══ 单源词表（W2-S1 批 4 扩面 498 键）═══
   壳面（index.html）：26 nav + 3 nav.group + 1 skip + 3 common.aria +
   8 palette + 2 foot；三试点页：tools 10 + gallery 12 + queue 13；
   扩面五页：dashboard 12 + runs 11 + detail 11 + sparams 10 + agent 14；
   W8-S32 批 3：common.help_summary 1 + dashboard 55 + detail 4 +
   timeline 10 + sparams 1 + agent 12；
   W2-S1 批 4：common.kit 3（empty/load_failed/retry，kit.js 单源消费）+
   tools 130（help/组名/计算器名与用途兜底 cn_ 键·cp_ 键/扫参/结果面）+
   datasets 34 + anchors 24 + uq 47 + guide 41。
   值永不含 HTML（见头注纪律；&lt; 等字符实体除外，见上）；{name} 为
   t(key, params) 占位符。 */
export const LOCALES = {
  /* ── nav.*（键名=index.html nav data-v 值，单源对齐）── */
  "nav.dashboard": { zh: "总览", en: "Dashboard" },
  "nav.import": { zh: "工程导入", en: "Import Project" },
  "nav.recipe": { zh: "配方编辑", en: "Recipes" },
  "nav.tune": { zh: "优化调参", en: "Tuning" },
  "nav.optstack": { zh: "优化洞察", en: "Optimization Insights" },
  "nav.loopboard": { zh: "执行看板", en: "Execution Board" },
  "nav.campaign": { zh: "战役仪表盘", en: "Campaigns" },
  "nav.queue": { zh: "调度队列", en: "Queue" },
  "nav.gallery": { zh: "模板画廊", en: "Template Gallery" },
  "nav.runs": { zh: "Run 历史", en: "Run History" },
  "nav.detail": { zh: "Run 详情", en: "Run Detail" },
  "nav.sparams": { zh: "S 参数分析", en: "S-Parameters" },
  "nav.farfield": { zh: "远场方向图", en: "Far Field" },
  "nav.field": { zh: "场可视化 3D", en: "3D Fields" },
  "nav.calibration": { zh: "校准工作台", en: "Calibration" },
  "nav.datasets": { zh: "数据集", en: "Datasets" },
  "nav.anchors": { zh: "标定锚", en: "Anchors" },
  "nav.uq": { zh: "UQ 不确定度", en: "UQ" },
  "nav.playground": { zh: "代理 Playground", en: "Surrogate Playground" },
  "nav.timeline": { zh: "成本时间线", en: "Cost Timeline" },
  "nav.reports": { zh: "报告中心", en: "Reports" },
  "nav.tools": { zh: "微波工具箱", en: "Microwave Tools" },
  "nav.agent": { zh: "Agent 助手", en: "Agent" },
  "nav.guide": { zh: "使用指南", en: "Guide" },
  "nav.solvers": { zh: "求解器", en: "Solvers" },
  "nav.profile": { zh: "剖析", en: "Profiler" },
  /* ── nav.group.*（侧栏分组标签 ×3）── */
  "nav.group.workspace": { zh: "工作区", en: "Workspace" },
  "nav.group.analysis": { zh: "分析", en: "Analysis" },
  "nav.group.help": { zh: "帮助与系统", en: "Help & System" },
  /* ── common.*（skip 链接 + 壳 aria 标签）── */
  "common.skip_to_content": { zh: "跳到主内容", en: "Skip to content" },
  "common.aside_aria": { zh: "侧边栏", en: "Sidebar" },
  "common.nav_aria": { zh: "主导航", en: "Main navigation" },
  "common.lightbox_aria": { zh: "图片灯箱预览", en: "Image lightbox preview" },
  /* ── palette.*（命令面板占位/提示/aria；hint 三段夹 <code> 芯片排版）── */
  "palette.placeholder": {
    zh: "跳转页面、# 搜 run、> 命令…",
    en: "Jump to page, # search runs, > commands…",
  },
  "palette.input_aria": { zh: "搜索命令、页面与 run", en: "Search commands, pages and runs" },
  "palette.dialog_aria": { zh: "命令面板", en: "Command palette" },
  "palette.open_aria": { zh: "打开命令面板（Ctrl+K）", en: "Open command palette (Ctrl+K)" },
  "palette.open_label": { zh: "命令面板", en: "Commands" },
  "palette.hint.nav": {
    zh: "↑↓ 选择 · Enter 跳转 · Esc 关闭 · ",
    en: "↑↓ Select · Enter Open · Esc Close · ",
  },
  "palette.hint.run": { zh: " run · ", en: " runs · " },
  "palette.hint.cmd": { zh: " 命令 · Ctrl+K 开关", en: " commands · Ctrl+K toggle" },
  /* ── foot.*（侧栏版本注记，A6-D 中性化口径的 en 对照）── */
  "foot.version_note": {
    zh: "HFSS/ADS 以实装版本为准（本机实测 2025 R1 / v251）",
    en: "HFSS/ADS per installed version (local: 2025 R1 / v251)",
  },
  "foot.local": { zh: "本机服务", en: "Local service" },
  /* ── tools.*（试点页 1：微波工具箱静态壳标签）── */
  "tools.title": { zh: "微波工具箱", en: "Microwave Tools" },
  "tools.search_label": { zh: "搜索", en: "Search" },
  "tools.search_placeholder": { zh: "键名 / 中文名 / 用途", en: "key / name / purpose" },
  "tools.search_aria": {
    zh: "搜索计算器（键名、中文名、用途）",
    en: "Search calculators (key, name, purpose)",
  },
  "tools.calculators_label": { zh: "计算器", en: "Calculators" },
  "tools.run": { zh: "计算", en: "Compute" },
  "tools.result_title": { zh: "结果", en: "Results" },
  "tools.result_hint": {
    zh: "选择计算器，填参数后点「计算」",
    en: "Pick a calculator, fill in parameters, then click Compute",
  },
  "tools.formula_summary": {
    zh: "公式与出处（description 全文）",
    en: "Formula & source (full description)",
  },
  "tools.sweep_label": { zh: "扫参模式", en: "Sweep mode" },
  /* ── gallery.*（试点页 2：模板画廊；R2 人性化席 2026-10-19 重写——
     顶栏去内部概念、卡面瘦身、72 卡详情抽屉，详见 view_gallery 头注）── */
  "gallery.title": { zh: "模板画廊", en: "Template Gallery" },
  "gallery.subtitle": {
    zh: "内置模板库 · 点「详情」看器件说明与参数表",
    en: "Built-in template library · click Details for the blurb and parameter table",
  },
  "gallery.filter_placeholder": { zh: "按名称/拓扑过滤…", en: "Filter by name/topology…" },
  "gallery.loading": { zh: "加载中...", en: "Loading..." },
  "gallery.count_tpl": {
    zh: "{n} 模板 · {p} 配闭式预览通道",
    en: "{n} templates · {p} with closed-form preview",
  },
  "gallery.preview_badge": { zh: "闭式预览", en: "Closed-form preview" },
  "gallery.no_preview": { zh: "预览未覆盖", en: "no preview" },
  "gallery.detail_btn": { zh: "详情", en: "Details" },
  "gallery.detail_aria_tpl": {
    zh: "查看模板详情：{name}",
    en: "View template details: {name}",
  },
  "gallery.compute": { zh: "计算", en: "Compute" },
  "gallery.result_hint": { zh: "拖动滑块后点「计算」", en: "Drag sliders, then click Compute" },
  /* 三态收敛（aurora_f W2-S5，R1 #8 批1）：过滤零命中空态（kitEmptyState 消费） */
  "gallery.empty_filter": {
    zh: "无匹配模板——调整过滤词再试",
    en: "No matching templates — adjust the filter",
  },
  /* ── queue.*（试点页 3：调度队列）── */
  "queue.title": { zh: "调度队列", en: "Queue" },
  "queue.subtitle": {
    zh: "战役计划 · 调度决策日志",
    en: "Campaign plans · scheduling decision log",
  },
  "queue.runs_root": { zh: "runs 根", en: "runs root" },
  "queue.machine_label": { zh: "远程机器", en: "Remote machine" },
  "queue.machine_placeholder": { zh: "（留空=不查远程机器）", en: "(empty = skip remote machines)" },
  "queue.reload": { zh: "刷新", en: "Reload" },
  "queue.info_tpl": { zh: "{n} 个战役计划", en: "{n} campaign plans" },
  "queue.empty": {
    zh: "runs/ 下暂无 campaign.plan.json（先立战役）",
    en: "No campaign.plan.json under runs/ (create a campaign first)",
  },
  "queue.empty_action": { zh: "去战役仪表盘", en: "Go to Campaigns" },
  "queue.th_campaign": { zh: "战役", en: "Campaign" },
  "queue.th_stages": { zh: "阶段进度", en: "Stages" },
  "queue.th_schedule": { zh: "调度", en: "Scheduling" },
  "queue.th_decision_log": { zh: "决策日志", en: "Decision log" },
  /* ── dashboard.*（扩面页 1：总览——组件化仪表盘；widget 标题经注册表
     tk 字段 t() 渲染期烘焙，随数据重建的动态容器不挂 data-i18n）── */
  "dashboard.title": { zh: "总览", en: "Dashboard" },
  "dashboard.add_widget_label": { zh: "添加组件：", en: "Add widgets:" },
  "dashboard.all_added": { zh: "已全部添加", en: "All widgets added" },
  "dashboard.w_kpi": { zh: "关键指标", en: "Key metrics" },
  "dashboard.w_recent_runs": { zh: "最近 Run", en: "Recent runs" },
  "dashboard.w_activity": { zh: "最近活动", en: "Recent activity" },
  "dashboard.w_s11_trend": { zh: "S11 趋势", en: "S11 trend" },
  "dashboard.w_solvers": { zh: "求解器状态", en: "Solver status" },
  "dashboard.w_tune_status": { zh: "调参状态", en: "Tuning status" },
  "dashboard.w_status_mix": { zh: "pass/fail 分布", en: "pass/fail mix" },
  "dashboard.w_adapter_mix": { zh: "adapter 分布", en: "adapter mix" },
  "dashboard.w_quick_links": { zh: "快速开始", en: "Quick start" },
  /* ── runs.*（扩面页 2：Run 历史）── */
  "runs.title": { zh: "Run 历史", en: "Run History" },
  "runs.filter_placeholder": { zh: "run_id 过滤…", en: "filter by run_id…" },
  "runs.all_channels": { zh: "全部通道", en: "All adapters" },
  "runs.s11_better_than": { zh: "S11 优于:", en: "S11 better than:" },
  "runs.clear": { zh: "清除", en: "Clear" },
  "runs.th_time": { zh: "时间", en: "Time" },
  "runs.th_inband_s11": { zh: "带内 S11", en: "In-band S11" },
  "runs.th_status": { zh: "状态", en: "Status" },
  "runs.th_best_metric": { zh: "best 指标", en: "best metric" },
  "runs.empty_filter": {
    zh: "无匹配 run——调整筛选条件试试",
    en: "No matching runs — adjust the filters and try again",
  },
  "runs.clear_filter": { zh: "清除筛选", en: "Clear filters" },
  /* ── detail.*（扩面页 3：Run 详情——h2 内含动态 small#detail-id，
     静态文案包 span 挂 data-i18n（textContent 重扫不伤动态子元素））── */
  "detail.title": { zh: "Run 详情", en: "Run Detail" },
  "detail.empty_no_run": {
    zh: "未指定 run——从「Run 历史」或总览点选一个，或直接打开 #/detail/〈run_id〉。",
    en: "No run specified — pick one from Run History or the Dashboard, or open #/detail/〈run_id〉 directly.",
  },
  "detail.goto_runs": { zh: "去 Run 历史", en: "Go to Run History" },
  "detail.sparams_title": {
    zh: "S 参数（图例点击切换分量；滚轮缩放、悬停读数）",
    en: "S-params (click legend to toggle; wheel zoom, hover readout)",
  },
  "detail.model3d": { zh: "3D 模型", en: "3D model" },
  "detail.files_title": { zh: "产物清单", en: "Artifacts" },
  "detail.th_file": { zh: "文件", en: "File" },
  "detail.th_size": { zh: "大小", en: "Size" },
  "detail.recipe_title": { zh: "配方快照", en: "Recipe snapshot" },
  "detail.load_failed": { zh: "加载失败", en: "Load failed" },
  "detail.retry": { zh: "重试", en: "Retry" },
  /* ── sparams.*（扩面页 4：S 参数分析——空态=词表段+esc 警示段拼接，
     API 数据不进词表值；深链占位选项=前缀 id+后缀词表段）── */
  "sparams.title": { zh: "S 参数分析", en: "S-Parameter Analysis" },
  "sparams.mode_deg": { zh: "相位", en: "Phase" },
  "sparams.add_external": { zh: "+外部 .sNp", en: "+ External .sNp" },
  "sparams.clear_overlay": { zh: "清除叠加", en: "Clear overlays" },
  "sparams.deeplink_suffix": {
    zh: "（深链 run，不在最近清单内）",
    en: " (deep-linked run, not in recent list)",
  },
  "sparams.empty_lead": {
    zh: "该 run 无 Touchstone 产物",
    en: "No Touchstone artifacts for this run",
  },
  "sparams.empty_smith_tail": {
    zh: "——可用「+外部 .sNp」导入",
    en: " — import it via + External .sNp",
  },
  "sparams.empty_db_tail": {
    zh: "——fake 通道请到 Run 详情页看 PNG 曲线，或用「+外部 .sNp」直接导入文件",
    en: " — for the fake adapter see PNG curves in Run Detail, or import the file via + External .sNp",
  },
  "sparams.overlay_title": {
    zh: "对比图（run 产物 + 外部叠加）",
    en: "Comparison (run artifacts + external overlays)",
  },
  "sparams.overlay_only_title": {
    zh: "外部叠加（该 run 无 Touchstone 产物）",
    en: "External overlays (no Touchstone artifacts for this run)",
  },
  /* ── agent.*（扩面页 5：Agent 助手——对话浮窗与 toast 走下一波，
     本波收页面壳静态 chrome + 徽章/空态烘焙）── */
  "agent.title": { zh: "Agent 助手", en: "Agent Assistant" },
  "agent.model_settings": { zh: "⚙ 模型设置", en: "⚙ Model settings" },
  "agent.ph_model": { zh: "模型名", en: "model name" },
  "agent.ph_key": { zh: "不改则留空", en: "leave empty to keep" },
  "agent.save": { zh: "保存", en: "Save" },
  "agent.clear_chat": { zh: "清空对话", en: "Clear chat" },
  "agent.prompt_summary": {
    zh: "内置提示词（系统 prompt，透明可查）",
    en: "Built-in prompt (system prompt, fully transparent)",
  },
  "agent.inbox_title": {
    zh: "审批收件箱（提案以参数 diff 展示）",
    en: "Approval inbox (proposals shown as parameter diffs)",
  },
  "agent.sandbox_title": {
    zh: "Agent 沙箱草稿（agent 在对话里改的配方先落这里，送审批后进收件箱）",
    en: "Agent sandbox drafts (recipe edits made in chat land here first; send for approval to reach the inbox)",
  },
  "agent.open_chat": { zh: "💬 打开对话浮窗", en: "💬 Open chat window" },
  "agent.loading": { zh: "加载中...", en: "Loading..." },
  "agent.no_pending": { zh: "无待审批提案", en: "No pending proposals" },
  "agent.cfg_ok": { zh: "已配置真实 LLM", en: "Real LLM configured" },
  "agent.cfg_none": { zh: "未配置（指令模式）", en: "Not configured (command mode)" },

  /* ═══ W8-S32 i18n 批 3 扩面（+83 键）══════════════════════════════════
     zh 值=既有字面同笔迁入（渲染逐字节不变），en 值新增。富 HTML 面（help
     块/图注）=分段 t() 方案：结构留模板、纯文本段进词表（W1-S2 hint 芯片
     先例），值零 HTML 纪律不变；跨段标点归前段键尾（en 语序自由）。 */

  /* ── common.help_summary（dom.js help() 壳，26 个调用点一次收口）── */
  "common.help_summary": { zh: "❓ 本页说明（点开查看）", en: "❓ Page guide (click to open)" },
  /* ── dashboard.*（W8-S32 批 3：help 块分段 16 + 控件钮/aria 6 + KPI 3 +
     activity 5 + 分布图 4 + S11 趋势 8 + solvers 4 + tune 4 + adapter 1 +
     快速开始 4；quick links 标题复用 nav.* 键不重立）── */
  "dashboard.help_1_lead": { zh: "总览由", en: "The dashboard is built from " },
  "dashboard.help_1_core": { zh: "可增删的组件", en: "add/remove widgets" },
  "dashboard.help_1_tail": {
    zh: "拼成：点右上「＋ 添加组件」勾选想看的，点组件右上「×」移除（自动记住）。",
    en: " — click “＋ Add widgets” at the top right to pick panels, click “×” on a widget to remove it (remembered automatically).",
  },
  "dashboard.help_2_core1": { zh: "最近活动", en: "Recent activity" },
  "dashboard.help_2_mid": { zh: "＝run 流水（新→旧，点条目进详情）；", en: " = run stream (new→old, click an entry for detail); " },
  "dashboard.help_2_core2": { zh: "关键指标", en: "Key metrics" },
  "dashboard.help_2_tail": {
    zh: "右上角圆环＝数据新鲜度（绿 1 小时内／黄 24 小时内／灰更久，悬浮看具体时间）。",
    en: " have a top-right freshness ring (green <1 h / yellow <24 h / grey older; hover for the exact time).",
  },
  "dashboard.help_3_core": { zh: "pass/fail 分布", en: "pass/fail mix" },
  "dashboard.help_3_tail": {
    zh: "＝全部 run 的状态环形图（工具条可导出 CSV/PNG）。",
    en: " = status donut over all runs (toolbar exports CSV/PNG).",
  },
  "dashboard.help_4_core1": { zh: "S11 趋势", en: "S11 trend" },
  "dashboard.help_4_mid": { zh: "：每个", en: ": each " },
  "dashboard.help_4_core2": { zh: "点 = 一次 run 的带内 S11 最大值", en: "dot = one run's in-band S11 max" },
  "dashboard.help_4_tail1": {
    zh: "按 run 时间排布（越往后越低 = 调参在变好）——",
    en: " ordered by run time (later and lower = tuning improving) — ",
  },
  "dashboard.help_4_core3": { zh: "不是频域曲线", en: "not a frequency curve" },
  "dashboard.help_4_tail2": {
    zh: "；要看频率↔S11 曲线请去「S 参数分析」或「报告中心」。",
    en: "; for frequency↔S11 curves see S-Parameters or Reports.",
  },
  "dashboard.help_5": {
    zh: "新到项目？去「使用指南」页有 5 分钟上手路线。",
    en: "New here? The Guide page has a 5-minute quick start.",
  },
  "dashboard.btn_span": { zh: "加宽/收窄", en: "Resize" },
  "dashboard.btn_remove": { zh: "移除组件", en: "Remove widget" },
  "dashboard.aria_span_tpl": { zh: "加宽/收窄组件：{name}", en: "Resize widget: {name}" },
  "dashboard.aria_remove_tpl": { zh: "移除组件：{name}", en: "Remove widget: {name}" },
  "dashboard.loading_aria": { zh: "组件数据加载中", en: "Loading widget data" },
  "dashboard.recent_caption": {
    zh: "最近 Run 表：点行打开 run 详情，点表头排序",
    en: "Recent runs table: click a row to open run detail, click a header to sort",
  },
  "dashboard.kpi_runs": { zh: "Run 总数", en: "Total runs" },
  "dashboard.kpi_best_s11": { zh: "带内 S11 最优", en: "Best in-band S11" },
  "dashboard.kpi_adapters": { zh: "使用过的通道", en: "Adapters used" },
  "dashboard.activity_empty": {
    zh: "暂无活动——去「工程导入」跑第一个 run",
    en: "No activity yet — run your first job from Import Project",
  },
  "dashboard.activity_go_import": { zh: "去工程导入", en: "Go to Import Project" },
  "dashboard.activity_done": { zh: "完成", en: "done" },
  "dashboard.activity_fail": { zh: "失败", en: "failed" },
  "dashboard.activity_unknown": { zh: "未知", en: "unknown" },
  "dashboard.mix_empty": {
    zh: "暂无 run——分布图待第一个 run 落盘后出现",
    en: "No runs yet — the donut appears after the first run lands",
  },
  "dashboard.mix_other": { zh: "其他", en: "Other" },
  "dashboard.mix_aria_prefix": { zh: "图表：run 状态分布甜甜圈（", en: "Chart: run status donut (" },
  "dashboard.mix_csv_name": { zh: "run 状态分布", en: "run status mix" },
  "dashboard.trend_empty": {
    zh: "数据不足（至少 2 个带指标的 run）",
    en: "Not enough data (need at least 2 runs with metrics)",
  },
  "dashboard.trend_series": { zh: "带内 S11 (dB)", en: "In-band S11 (dB)" },
  "dashboard.trend_xlabel": { zh: "run（旧→新）", en: "runs (old→new)" },
  "dashboard.trend_aria": {
    zh: "图表：带内 S11 (dB)，纵轴 dB，横轴 run（旧→新）",
    en: "Chart: in-band S11 (dB), y-axis dB, x-axis runs (old→new)",
  },
  "dashboard.trend_cap_a": {
    zh: "每个点 = 一次 run 的带内 S11 最大值（",
    en: "Each dot = one run's in-band S11 max (",
  },
  "dashboard.trend_cap_notfreq": { zh: "非频域曲线", en: "not a frequency curve" },
  "dashboard.trend_cap_b": {
    zh: "）；悬停读数 / 滚轮缩放 / 拖动滑块；S11 越低越好。频率↔S11 曲线见 ",
    en: "); hover to read, wheel to zoom, drag the slider; lower S11 is better. For frequency↔S11 curves see ",
  },
  "dashboard.trend_cap_or": { zh: " 或 ", en: " or " },
  "dashboard.solvers_available": { zh: "可用", en: "available" },
  "dashboard.solvers_unavailable": { zh: "不可用", en: "unavailable" },
  "dashboard.solvers_note_hfss": {
    zh: "HFSS/AEDT：以实装版本为准（本仓实测 2025 R1/v251）",
    en: "HFSS/AEDT: per installed version (repo-tested 2025 R1 / v251)",
  },
  "dashboard.solvers_note_ads": { zh: "ADS 2027：link 已验证", en: "ADS 2027: link verified" },
  "dashboard.tune_running": {
    zh: "调参运行中…（详情见「优化调参」页）",
    en: "Tuning in progress… (see the Tuning page)",
  },
  "dashboard.tune_error": { zh: "上次调参出错", en: "Last tuning errored" },
  "dashboard.tune_done": { zh: "上次调参已完成", en: "Last tuning completed" },
  "dashboard.tune_never": { zh: "尚未运行调参", en: "No tuning run yet" },
  "dashboard.adapter_count_tpl": { zh: "{n} 次 ({p}%)", en: "{n} runs ({p}%)" },
  "dashboard.ql_import_d": {
    zh: "读入 HFSS .aedt，勾选要调的参数",
    en: "Import an HFSS .aedt and pick the parameters to tune",
  },
  "dashboard.ql_recipe_d": { zh: "设定目标（什么算好）", en: "Set objectives (what counts as good)" },
  "dashboard.ql_tune_d": { zh: "fake 粗筛 → 精算", en: "fake screening → high-fidelity runs" },
  "dashboard.ql_runs_d": { zh: "查看每次仿真结果", en: "Inspect each simulation result" },
  /* ── detail.*（W8-S32 批 3 补 4：骨架 aria + fake 曲线引导 + 3D 空态 +
     配方快照缺省）── */
  "detail.loading_aria": { zh: "run 数据加载中", en: "Loading run data" },
  "detail.no_touchstone": {
    zh: "无 Touchstone（fake 通道），曲线图：",
    en: "No Touchstone (fake adapter), figure curves:",
  },
  "detail.no_model3d": {
    zh: "该 run 无可渲染的 3D 模板",
    en: "No renderable 3D template for this run",
  },
  "detail.recipe_none": { zh: "(无快照)", en: "(no snapshot)" },
  /* ── timeline.*（W8-S32 批 3：本页接入壳扫描=第 9 页；壳 3 + 状态行 3 +
     图表 props 3 + 空态 1）── */
  "timeline.title": { zh: "成本时间线", en: "Cost Timeline" },
  "timeline.panel_cost": {
    zh: "Run 目标成本时间线（低=好）",
    en: "Run objective cost timeline (lower is better)",
  },
  "timeline.panel_tune": {
    zh: "调参收敛（最近 tune run）",
    en: "Tuning convergence (latest tune run)",
  },
  "timeline.info_cost_tpl": { zh: "{n} 个 run 有成本", en: "{n} runs with cost" },
  "timeline.info_nocost_tpl": { zh: " · {n} 个无快照/指标未画", en: " · {n} without snapshot/metrics skipped" },
  "timeline.info_latest_lead": { zh: " · 最新 ", en: " · latest " },
  "timeline.empty_tune": {
    zh: "暂无调参 run（到「优化调参」页启动一次）",
    en: "No tuning run yet (start one on the Tuning page)",
  },
  "timeline.series_trial_cost": { zh: "trial cost", en: "trial cost" },
  "timeline.xlabel_cost": { zh: "run 时间（旧→新）", en: "run time (old→new)" },
  "timeline.aria_tune": {
    zh: "图表：trial cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
    en: "Chart: trial cost, y-axis cost, x-axis trial (with best-so-far staircase)",
  },
  /* ── sparams.*（W8-S32 批 3 补 1：相位模式纵轴）── */
  "sparams.ylabel_deg": { zh: "相位（deg）", en: "Phase (deg)" },
  /* ── agent.*（W8-S32 批 3 补 12：对话浮窗静态面 + 快捷提问 chips +
     提示词缺省；统计条（updateStats）与审批/沙箱面板=后续波次）── */
  "agent.chat_float_aria": { zh: "Agent 对话浮窗", en: "Agent chat window" },
  "agent.chat_title": { zh: "💬 对话（历史自动保存）", en: "💬 Chat (history auto-saved)" },
  "agent.chat_input_ph": {
    zh: "例如：分析最近一次 run 并提议参数修改",
    en: "e.g. analyze the latest run and propose parameter changes",
  },
  "agent.chat_send": { zh: "发送", en: "Send" },
  "agent.chat_sending": { zh: "发送中…", en: "Sending…" },
  "agent.chat_thinking": {
    zh: "思考中（可能连续调用多个工具，约 10-60 秒，复杂任务可能更久）…",
    en: "Thinking (may call several tools; ~10-60 s, complex tasks can take longer)…",
  },
  "agent.tools_prefix": { zh: "🔧 工具: ", en: "🔧 Tools: " },
  "agent.prompt_missing": { zh: "(未取到)", en: "(not fetched)" },
  "agent.sug_analyze": { zh: "分析最近一次 run", en: "analyze the latest run" },
  "agent.sug_list": { zh: "list solvers", en: "list solvers" },
  "agent.sug_validate": {
    zh: "校验 recipes/wilkinson_pd_v1.yaml",
    en: "validate recipes/wilkinson_pd_v1.yaml",
  },
  "agent.sug_propose": {
    zh: "帮 wilkinson 配方提议一组新参数",
    en: "propose a new parameter set for the wilkinson recipe",
  },

  /* ═══ W2-S1 i18n 批 4 扩面（+278 键，aurora_g）════════════════════════
     zh 值=既有字面同笔迁入（渲染逐字节不变），en 值新增。kit 三串为
     11 视图错误/空态单源（字节等价钉 test_ui_kit/test_ui_polish 在
     node zh 档下逐字节复现）。 */

  /* ── common.*（kit.js 共享组件单源：空态/错误态/重试，11 视图受益）── */
  "common.empty": { zh: "暂无数据", en: "No data" },
  "common.load_failed": { zh: "加载失败", en: "Load failed" },
  "common.retry": { zh: "重试", en: "Retry" },

  /* ── W6-S2 kitConfirm 破坏性动作确认（R1 P9-8 / R2 Top10 #6）────────
     钮面=kit.js 单源缺省（common.confirm/cancel）；标题/正文由接线点传
     t() 烘焙串（agent.clear_chat_body=清空对话；loopboard.takeover(_body)
     =接管环控制——loopboard 页未接 i18n 扫描域，键经 t() 动态消费）。 */
  "common.confirm": { zh: "确认", en: "Confirm" },
  "common.cancel": { zh: "取消", en: "Cancel" },

  /* ── W14-S2 离线检测（R1 P9-12 / R2 Top10 #8）────────────────────────
     app.js 壳面 toast 单源消费（#msg role=status aria-live 在壳，断网/
     恢复读屏同播；online 侧同笔触发当前页 PAGE_CTX.refresh 自愈）。 */
  "common.offline": {
    zh: "网络连接已断开——页面数据暂停刷新，恢复后自动续拉",
    en: "Network offline — data refresh paused, will resume automatically",
  },
  "common.online": { zh: "网络已恢复", en: "Network back online" },
  "agent.clear_chat_body": {
    zh: "将清空对话历史（含本地保存的记录），不可恢复。确定继续？",
    en: "This clears the chat history (including locally saved messages) and cannot be undone. Continue?",
  },
  "loopboard.takeover": { zh: "✋ 接管", en: "✋ Take over" },
  "loopboard.takeover_body": {
    zh: "接管后环将停止自动推进、改由你手动控制（可再下发「继续」恢复自动模式）。确定接管？",
    en: "After taking over, the loop stops auto-advancing and waits for manual control (send Resume to return to auto). Take over?",
  },

  /* ── guide.*（使用指南页：纯静态页整页分段 t() 迁入）── */
  "guide.help_1": {
    zh: "本页 = 内置说明书。第一次用？按下面 4 步走一遍 fake 演示即可上手。",
    en: "This page = the built-in manual. First time? Walk through the 4-step fake demo below.",
  },
  "guide.help_2": {
    zh: "随时可以回「总览」点「＋ 添加组件」定制你想盯的面板。",
    en: "Any time, go back to Dashboard and click “＋ Add widgets” to customize your panels.",
  },
  "guide.title": { zh: "使用指南", en: "Guide" },
  "guide.subtitle": { zh: "写给第一次接触 rfauto 的你", en: "For your first contact with rfauto" },
  "guide.what_title": { zh: "rfauto 是做什么的", en: "What does rfauto do" },
  "guide.what_lead": {
    zh: "HFSS/ADS 这类电磁仿真很慢，直接在真机上反复试参数代价很高。rfauto 的思路是：",
    en: "Full-wave simulators like HFSS/ADS are slow; probing parameters on them directly is expensive. The rfauto idea:",
  },
  "guide.what_core": {
    zh: "用快速代理（fake/openEMS）先粗筛参数 → 再用 HFSS/ADS 精算少数候选",
    en: "screen parameters with fast surrogates (fake/openEMS) first, then high-fidelity-run the few candidates in HFSS/ADS",
  },
  "guide.what_tail": {
    zh: "，再用可信度门把关——粗筛挑出的排名要和高保真对得上（回测命中率≥80%）才算靠谱。",
    en: " — then a credibility gate keeps it honest: the screen's rankings must match high fidelity (hit rate ≥80%).",
  },
  "guide.steps_title": { zh: "5 分钟上手路线", en: "5-minute quick start" },
  "guide.step1_t": { zh: "工程导入", en: "Import Project" },
  "guide.step1_d": {
    zh: "读入你的 HFSS 工程（.aedt），勾选要调的变量。",
    en: "Read in your HFSS project (.aedt) and pick the variables to tune.",
  },
  "guide.step2_t": { zh: "配方编辑", en: "Recipes" },
  "guide.step2_d": {
    zh: "补 objectives（什么算“好”，如带内 S11&lt;-15dB），确认优化范围。",
    en: "Fill in objectives (what counts as “good”, e.g. in-band S11&lt;-15dB) and confirm the search ranges.",
  },
  "guide.step3_t": { zh: "优化调参", en: "Tuning" },
  "guide.step3_d": {
    zh: "先用 fake adapter 跑通流程（秒级），再切 hfss 真机精算。",
    en: "Run the loop end-to-end with the fake adapter (seconds), then switch to hfss for high-fidelity runs.",
  },
  "guide.step4_t": { zh: "Run 历史", en: "Run History" },
  "guide.step4_d": {
    zh: "看 S 参数曲线与指标，best_params 就是推荐工作点。",
    en: "Inspect S-parameter curves and metrics; best_params is the recommended operating point.",
  },
  "guide.gl_title": { zh: "概念速查", en: "Concept glossary" },
  "guide.gl_recipe_t": { zh: "配方 (recipe)", en: "Recipe" },
  "guide.gl_recipe_d": {
    zh: "一次仿真的完整定义：模型 + 参数 + 扫频 + 目标 + 优化设置（YAML 文件）。",
    en: "The complete definition of one simulation: model + parameters + sweep + objectives + optimizer settings (a YAML file).",
  },
  "guide.gl_run_d": {
    zh: "配方的一次实际执行；每个 run 有 id、指标、S 参数曲线和产物存档。",
    en: "One actual execution of a recipe; each run has an id, metrics, S-parameter curves and archived artifacts.",
  },
  "guide.gl_adapter_d": {
    zh: "执行仿真的通道：fake（秒级解析演示）/ openEMS（免费 FDTD）/ HFSS（商业真机）。",
    en: "The channel that runs the simulation: fake (seconds, analytic demo) / openEMS (free FDTD) / HFSS (commercial solver).",
  },
  "guide.gl_obj_d": {
    zh: "“什么算好”的裁判，如「带内 S11 最大值低于 -15dB」。优化器按它打分。",
    en: "The judge of “what counts as good”, e.g. “in-band S11 max below -15dB”. The optimizer scores against it.",
  },
  "guide.gl_mf_t": { zh: "多保真", en: "Multi-fidelity" },
  "guide.gl_mf_d": {
    zh: "两阶段流程：fake 粗筛 + 高保真精算；两边的排序要对得上（见下方可信度门）。",
    en: "A two-stage flow: fake screening then high-fidelity refinement; the two stages must rank parameters consistently (see the credibility gate below).",
  },
  "guide.gl_p0_t": { zh: "可信度门", en: "Credibility gate" },
  "guide.gl_p0_d": {
    zh: "fake 粗筛挑出的参数要和高保真精算对照：排序相关 ρ≥0.8 且前 5 命中≥80%，达标才可信。",
    en: "The fake screen's picks are checked against high-fidelity results: ranking correlation ρ≥0.8 and top-5 hit rate ≥80% must both pass.",
  },
  "guide.gl_gate_t": { zh: "Agent 审批链", en: "Agent approval chain" },
  "guide.gl_gate_d": {
    zh: "LLM 提参数 → 自动校验 → 你在收件箱批准 → 才真正执行。",
    en: "The LLM proposes parameters → automatic checks run → you approve in the inbox → only then does it execute.",
  },
  "guide.faq_title": { zh: "常见问题", en: "FAQ" },
  "guide.faq1_q": { zh: "为什么第一次都建议跑 fake？", en: "Why is fake recommended first?" },
  "guide.faq1_a": {
    zh: " fake 秒级返回，先确认配方的目标/范围写得对，再上真机不浪费 license 时间。",
    en: " fake returns in seconds — confirm the recipe's objectives/ranges are right before spending solver time.",
  },
  "guide.faq2_q": { zh: "调参结果 plateau 在 -6dB？", en: "Tuning plateaus at -6dB?" },
  "guide.faq2_a": {
    zh: " 通常是结构级失配（线宽/端口归一化），纯几何调参到顶了——先审模型再调参。",
    en: " Usually a structure-level mismatch (line width / port normalization) — geometric tuning has topped out; audit the model first.",
  },
  "guide.faq3_q": { zh: "HFSS 用哪个版本？", en: "Which HFSS version is used?" },
  "guide.faq3_a": {
    zh: " 以实装版本为准（本机实测 2025 R1/v251）；工程导入页版本留空即跟随服务端缺省，无需手选。",
    en: " Per the installed version (repo-tested 2025 R1 / v251); leave the version field empty on Import Project to follow the server default.",
  },
  "guide.faq4_q": { zh: "openEMS 第一次跑很慢？", en: "openEMS slow on first run?" },
  "guide.faq4_a": {
    zh: " 真实谐振结构要跑满能量衰减（旧参考里 280s 是坏模型的假快）。结果会缓存，同配置秒回。",
    en: " Real resonant structures must run out the full energy decay (the 280s in old references was a bad model's fake speed). Results are cached — same config returns instantly.",
  },
  "guide.next_title": { zh: "下一步去哪", en: "Where to go next" },
  "guide.next_1_lead": { zh: "深入口径与踩坑：仓库 ", en: "For deeper conventions and pitfalls: repo " },
  "guide.next_1_tail": { zh: " 与 DEVLOG。", en: " and the DEVLOG." },
  "guide.next_2": {
    zh: "想看某个页面怎么用：每个页面顶部都有「❓ 本页说明」。",
    en: "To learn a specific page: every page has a “❓ Page guide” at the top.",
  },

  /* ── datasets.*（数据集页：runs/datasets 注册表，只读）── */
  "datasets.help_1_lead": {
    zh: "数据集 = 多次 run 攒下的参数与指标数据（Parquet/HDF5），是调参、校准和基准集的原料；本页",
    en: "Datasets = the parameter and metric data accumulated across runs (Parquet/HDF5), the raw material for tuning, calibration and benchmark sets; this page is ",
  },
  "datasets.help_1_core": { zh: "只读", en: "read-only" },
  "datasets.help_1_tail": { zh: "。", en: "." },
  "datasets.help_2_lead": {
    zh: "点数据集行看行级预览（抽样前 N 行）。",
    en: "Click a point-dataset row for a row-level preview (first N sampled rows). ",
  },
  "datasets.help_2_core": {
    zh: "n_rows 是抽样返回行数，不是全量计数",
    en: "n_rows is the sampled row count, not the full count",
  },
  "datasets.help_2_tail": { zh: "；全量看「点数」列。", en: "; see the Points column for the full count." },
  "datasets.help_3": {
    zh: "「模板族」读自数据集的 manifest 登记项；旧数据没登记的如实显示「未登记」，不猜。",
    en: "“Template family” reads the dataset's manifest entries; older manifests honestly show “unregistered” rather than guessing.",
  },
  "datasets.title": { zh: "数据集", en: "Datasets" },
  "datasets.subtitle": { zh: "runs/datasets · 只读", en: "runs/datasets · read-only" },
  "datasets.filter_ph": { zh: "按名称/模板族过滤…", en: "filter by name/family…" },
  "datasets.reload": { zh: "刷新", en: "Reload" },
  "datasets.loading": { zh: "加载中...", en: "Loading..." },
  "datasets.all_families": { zh: "全部模板族", en: "All template families" },
  "datasets.count_tpl": { zh: "{n} / {total} 个数据集", en: "{n} / {total} datasets" },
  "datasets.empty_filter": {
    zh: "无匹配数据集（先在 runs/datasets 下生成）",
    en: "No matching datasets (generate some under runs/datasets first)",
  },
  "datasets.th_name": { zh: "名称", en: "Name" },
  "datasets.th_points": { zh: "点数", en: "Points" },
  "datasets.th_rows": { zh: "行数", en: "Rows" },
  "datasets.th_family": { zh: "模板族", en: "Families" },
  "datasets.th_visibility": { zh: "可见性", en: "Visibility" },
  "datasets.th_gt": { zh: "GT 标注", en: "GT labels" },
  "datasets.th_hf": { zh: "HF 导出", en: "HF export" },
  "datasets.th_format": { zh: "格式", en: "Format" },
  "datasets.th_created": { zh: "创建时间", en: "Created" },
  "datasets.gt_rows_tpl": { zh: "{n} 行", en: "{n} rows" },
  "datasets.unregistered": { zh: "未登记", en: "unregistered" },
  "datasets.aria_preview_tpl": { zh: "预览数据集：{name}", en: "Preview dataset: {name}" },
  "datasets.hf_yes": { zh: "有", en: "yes" },
  "datasets.hf_no": { zh: "无", en: "no" },
  "datasets.footer_lead": {
    zh: "点数据集行进入行级预览；目录：",
    en: "Click a point-dataset row for a row-level preview; directory: ",
  },
  "datasets.preview_lead": { zh: "预览 — ", en: "Preview — " },
  "datasets.pl_lead": { zh: "行级预览 — ", en: "Row-level preview — " },
  "datasets.pl_fam_tpl": { zh: "模板族 {m} · ", en: "family {m} · " },
  "datasets.pl_tail_tpl": {
    zh: "抽样 {n} 行；n_rows 为抽样返回行数，非全量计数",
    en: "{n} rows sampled; n_rows is the sampled count, not the full count",
  },

  /* ── anchors.*（标定锚页：锚注册表 + 新鲜度，只读）── */
  "anchors.help_1": {
    zh: "锚 = 物理标定值的单一出处：每个「模板族 × 引擎对 × 物理量」登记一个常量、曲线、公式或指针（清单在 knowledge/anchors.yaml，运行时只读）。修订不覆盖历史，新证据登记为 -vN+1 新版本；两个引擎有分歧时登记双值，不强行合成一个数。",
    en: "Anchors = the single source of physical calibration values: each template family × engine pair × quantity registers a constant, curve, formula or pointer (the list lives in knowledge/anchors.yaml, read-only at runtime). Revisions never overwrite history — new evidence lands as a -vN+1 version; when two engines disagree, both values are registered instead of forcing one number.",
  },
  "anchors.help_2_core": { zh: "状态", en: "Status" },
  "anchors.help_2_tail": {
    zh: "是注册表的裁决：active 在用 / stale 已过期 / experimental 实验性（双值待归一） / awaiting_data 等数据回填 / retired 已退役。没有验证日期的锚，新鲜度如实显示 UNKNOWN，不编判定。",
    en: " is the registry verdict: active / stale / experimental (dual values pending) / awaiting_data (skeleton) / retired. Anchors without a verified date honestly show UNKNOWN — never a made-up verdict.",
  },
  "anchors.help_3": {
    zh: "点锚行看完整记录：出处、不确定度、消费方。",
    en: "Click an anchor row for the full record: provenance, uncertainty, consumers.",
  },
  "anchors.title": { zh: "标定锚", en: "Calibration Anchors" },
  "anchors.subtitle": { zh: "物理标定锚注册表 · 只读", en: "Physical calibration anchor registry · read-only" },
  "anchors.loading": { zh: "加载中...", en: "Loading..." },
  "anchors.reload": { zh: "刷新", en: "Reload" },
  "anchors.kpi_lead": { zh: "共 ", en: "Total " },
  "anchors.kpi_count_tpl": { zh: "/{n} 锚 · ", en: "/{n} anchors · " },
  "anchors.badge_nodate_tpl": {
    zh: "{n} 无验证日期（UNKNOWN）",
    en: "{n} without verified date (UNKNOWN)",
  },
  "anchors.load_warn_lead": { zh: "注册表装载告警：", en: "Registry load warnings: " },
  "anchors.th_status": { zh: "状态", en: "Status" },
  "anchors.th_kind": { zh: "锚类型", en: "Kind" },
  "anchors.th_family": { zh: "模板族", en: "Families" },
  "anchors.th_quantity": { zh: "量 / 值", en: "Quantity / value" },
  "anchors.th_engine": { zh: "引擎对", en: "Engine pair" },
  "anchors.th_fresh": { zh: "新鲜度", en: "Freshness" },
  "anchors.fresh_stale_tpl": { zh: "stale（龄期 {n} 天）", en: "stale ({n} d old)" },
  "anchors.fresh_ok": { zh: "新鲜", en: "fresh" },
  "anchors.fresh_unknown": { zh: "UNKNOWN（无验证日期）", en: "UNKNOWN (no verified date)" },
  "anchors.aria_detail_tpl": { zh: "查看锚详情：{name}", en: "View anchor detail: {name}" },
  "anchors.detail_lead": { zh: "锚详情 — ", en: "Anchor detail — " },
  "anchors.detail_unreadable": { zh: "详情不可读", en: "detail unreadable" },

  /* ── uq.*（UQ 不确定度页：代理蒙特卡洛良率 + 敏感性）── */
  "uq.help_1": {
    zh: "UQ = 用代理模型做蒙特卡洛公差分析：选一个校准样本集、给每个参数填公差 σ，即可估算良率、指标分布和参数敏感性——全程不跑真机。",
    en: "UQ = Monte-Carlo tolerance analysis on a surrogate: pick a calibration sample set, give each parameter a tolerance σ, and estimate yield, metric distributions and parameter sensitivity — no solver runs.",
  },
  "uq.help_2_lead": {
    zh: "所有数字由本地计算内核算出，页面只负责显示；",
    en: "All numbers come from the local compute kernel; the page only renders. ",
  },
  "uq.help_2_core": {
    zh: "没有样本集或公差时如实显示空态，不放假数据",
    en: "empty states are honest when no sample set or tolerances exist — no fake data",
  },
  "uq.help_2_tail": { zh: "。", en: "." },
  "uq.help_3": {
    zh: "敏感性 = 单参数 ±1σ 扰动的指标响应幅值合计（|Δmetric| 求和），越大越该优先收公差。",
    en: "Sensitivity = total metric response to a ±1σ perturbation of one parameter (sum of |Δmetric|); larger = tighten that tolerance first.",
  },
  "uq.title": { zh: "UQ 不确定度", en: "UQ" },
  "uq.subtitle": { zh: "代理蒙特卡洛 · 良率 / 分布 / 敏感性", en: "Surrogate Monte-Carlo · yield / distributions / sensitivity" },
  "uq.panel_assets": {
    zh: "① 校准样本集（点选下方文件填入）",
    en: "① Calibration sample sets (click one to fill it in)",
  },
  "uq.loading": { zh: "加载中...", en: "Loading..." },
  "uq.panel_run": { zh: "② 运行（万点级秒回）", en: "② Run (10k points in seconds)" },
  "uq.label_samples": { zh: "样本集: ", en: "Samples: " },
  "uq.label_kind": { zh: "代理: ", en: "Surrogate: " },
  "uq.label_draws": { zh: "抽样: ", en: "Draws: " },
  "uq.run": { zh: "运行 UQ", en: "Run UQ" },
  "uq.tol_hint": {
    zh: "选中样本集后这里列出逐参数公差 σ（留空=该参数不扰动）",
    en: "After picking a sample set, per-parameter tolerances σ are listed here (empty = parameter not perturbed)",
  },
  "uq.empty_assets": {
    zh: "runs/ 下没找到校准样本集（samples.json）——先跑一次校准或战役",
    en: "No calibration sample sets (samples.json) found under runs/ — run a calibration or campaign first",
  },
  "uq.th_file": { zh: "文件", en: "File" },
  "uq.th_samples": { zh: "样本数", en: "Samples" },
  "uq.th_objectives": { zh: "目标数", en: "Objectives" },
  "uq.th_bounds": { zh: "参数（bounds）", en: "Params (bounds)" },
  "uq.th_mtime": { zh: "修改时间", en: "Modified" },
  "uq.unparsed": { zh: "未解析（过大/损坏）", en: "unparsed (too large/corrupt)" },
  "uq.aria_pick_tpl": { zh: "选用样本集：{name}", en: "Pick sample set: {name}" },
  "uq.truncated": { zh: "清单已达上限，未全列", en: "Listing capped — not all entries shown" },
  "uq.th_param": { zh: "参数", en: "Parameter" },
  "uq.th_sigma": { zh: "容差 σ（与参数同单位）", en: "Tolerance σ (same unit as the parameter)" },
  "uq.sigma_ph": { zh: "σ（留空不扰动）", en: "σ (empty = not perturbed)" },
  "uq.sigma_aria_tpl": { zh: "参数 {n} 的公差 σ", en: "Tolerance σ of parameter {n}" },
  "uq.no_bounds": {
    zh: "该样本集没有参数清单，σ 需按参数名手填（或换一个样本集）",
    en: "This sample set has no parameter list — fill in σ by parameter name (or pick another set)",
  },
  "uq.err_sigma_tpl": { zh: "参数 {p} 的 σ 不是数值", en: "σ of parameter {p} is not a number" },
  "uq.err_sigma_empty": {
    zh: "至少填一个参数的公差 σ",
    en: "Fill in at least one parameter tolerance σ",
  },
  "uq.err_lead": { zh: "UQ 没出结果：", en: "UQ produced no result: " },
  "uq.unknown_error": { zh: "未知错误", en: "unknown error" },
  "uq.k_yield": { zh: "良率", en: "Yield" },
  "uq.k_draws": { zh: "抽样点数", en: "Draws" },
  "uq.k_kind": { zh: "代理", en: "Surrogate" },
  "uq.k_nominal": { zh: "名义点指标均值", en: "Metrics at nominal" },
  "uq.stats_count_tpl": { zh: "{n} 项", en: "{n} metrics" },
  "uq.metric_dist_title": { zh: "指标分布（蒙特卡洛）", en: "Metric distributions (Monte Carlo)" },
  "uq.th_metric": { zh: "指标", en: "Metric" },
  "uq.none": { zh: "无", en: "None" },
  "uq.nominal_lead": { zh: "名义参数：", en: "Nominal params: " },
  "uq.impl_lead": { zh: "实现：", en: "Implementation: " },
  "uq.uncert_lead": { zh: "不确定度状态：", en: "Uncertainty status: " },
  "uq.sens_title": {
    zh: "逐参数敏感性（±1σ 指标响应合计，降序）",
    en: "Per-parameter sensitivity (±1σ metric response total, descending)",
  },
  "uq.sens_note": {
    zh: "敏感性越大 = 该参数公差对指标影响越大，优先收公差或换设计中心。",
    en: "Larger sensitivity = that parameter's tolerance drives the metric more — tighten it first or move the design center.",
  },
  "uq.done_msg": { zh: "UQ 完成", en: "UQ done" },

  /* ── tools.*（W2-S1 批 4：微波工具箱余量全迁。cn_ 键/cp_ 键=计算器中文名/
     用途兜底表词表化（键尾=注册表 name，zh 与旧 CALC_ZH 逐字节同）；组名
     键=展示层翻译（协议标识符以中文单源在 view_tools，显示经 GROUP_I18N
     映射，服务端未知组名回退原文）。 ── */
  "tools.help_1_lead": { zh: "闭式微波计算器 ", en: "Closed-form microwave calculators " },
  "tools.help_1_tail": {
    zh: "——组清单由注册表实时生成，不手工维护。顶部搜索框支持键名／中文名／用途实时过滤；下拉按组浏览。",
    en: " — the group list is generated live from the registry, never hand-maintained. The search box filters by key/name/purpose in real time; browse by group in the dropdown.",
  },
  "tools.help_groups_loading": { zh: "清单加载中…", en: "loading list…" },
  "tools.help_2": {
    zh: "与综合引擎同口径（skrf Hammerstad-Jensen / Balanis 闭式）；必填参数标 *，留空的可选参数不传。",
    en: "Same conventions as the synthesis engines (skrf Hammerstad-Jensen / Balanis closed forms); required params are marked *, empty optional params are not sent.",
  },
  "tools.help_3_lead": {
    zh: "这些计算器也开放在命令行（rfauto calc）与 MCP（run_calculator）——同一套内核；深链 ",
    en: "The same calculators are exposed on the CLI (rfauto calc) and MCP (run_calculator) — one kernel, three frontends; deep link ",
  },
  "tools.help_3_code": { zh: "#/tools/&lt;键名&gt;", en: "#/tools/&lt;key&gt;" },
  "tools.help_3_tail": { zh: " 可直达并分享某计算器。", en: " jumps straight to (and shares) a calculator." },
  "tools.help_groups_tpl": {
    zh: "共 {n} 键 · {m} 组：{list}",
    en: "{n} keys · {m} groups: {list}",
  },
  "tools.help_groups_unavailable": {
    zh: "清单不可用（服务未就绪？刷新重试）",
    en: "List unavailable (service not ready? reload to retry)",
  },
  "tools.badge_experimental": {
    zh: "实验态（默认不放行）",
    en: "Experimental (blocked by default)",
  },
  "tools.opt_experimental": { zh: " [实验]", en: " [exp]" },
  /* ── 组名展示层翻译（16 已知组 + 实验/其他殿后组）── */
  "tools.group_txlines": { zh: "传输线正反解", en: "Transmission lines" },
  "tools.group_match": { zh: "匹配·功分·衰减·耦合", en: "Matching · Splitting · Attenuation · Coupling" },
  "tools.group_filter": { zh: "滤波器与耦合矩阵", en: "Filters & coupling matrices" },
  "tools.group_resonator": { zh: "谐振器与腔体", en: "Resonators & cavities" },
  "tools.group_antenna": { zh: "天线与阵列", en: "Antennas & arrays" },
  "tools.group_doa": { zh: "DOA 与波束形成", en: "DOA & beamforming" },
  "tools.group_mimo": { zh: "MIMO 与 RIS", en: "MIMO & RIS" },
  "tools.group_radar": { zh: "雷达", en: "Radar" },
  "tools.group_link": { zh: "链路与传播", en: "Links & propagation" },
  "tools.group_xcvr": { zh: "收发链路·频综", en: "TX/RX chains · frequency synthesis" },
  "tools.group_mod": { zh: "调制与数字链路", en: "Modulation & digital links" },
  "tools.group_emc": { zh: "EMC·安规·放电", en: "EMC · Safety · Discharge" },
  "tools.group_thermal": { zh: "热·功率·可靠性", en: "Thermal · Power · Reliability" },
  "tools.group_metrol": { zh: "测量与校准", en: "Measurement & calibration" },
  "tools.group_metam": { zh: "超材料·超表面", en: "Metamaterials · Metasurfaces" },
  "tools.group_quantum": { zh: "量子读出", en: "Quantum readout" },
  "tools.group_experimental": { zh: "实验", en: "Experimental" },
  "tools.group_other": { zh: "其他", en: "Other" },
  /* ── 计算器中文名（cn_*，zh=旧 CALC_ZH[0] 逐字节同）── */
  "tools.cn_attenuator_bridged_t": { zh: "桥式 T 型衰减器", en: "Bridged-T attenuator" },
  "tools.cn_attenuator_pi": { zh: "π 型衰减器", en: "Pi attenuator" },
  "tools.cn_attenuator_t": { zh: "T 型衰减器", en: "T attenuator" },
  "tools.cn_cavity_perturbation_shift": { zh: "腔体微扰谐振频移", en: "Cavity perturbation frequency shift" },
  "tools.cn_chebyshev_prototype": { zh: "Chebyshev 低通原型", en: "Chebyshev lowpass prototype" },
  "tools.cn_chebyshev_prototype_asym": { zh: "Chebyshev 非对称原型", en: "Chebyshev asymmetric prototype" },
  "tools.cn_chebyshev_refl_fn": { zh: "Chebyshev 反射函数", en: "Chebyshev reflection function" },
  "tools.cn_coupling_matrix_arrow": { zh: "箭头拓扑耦合矩阵", en: "Arrow-topology coupling matrix" },
  "tools.cn_coupling_matrix_extract": { zh: "耦合矩阵提取", en: "Coupling matrix extraction" },
  "tools.cn_coupling_matrix_folded": { zh: "折叠拓扑耦合矩阵", en: "Folded-topology coupling matrix" },
  "tools.cn_coupling_matrix_response": { zh: "耦合矩阵响应", en: "Coupling matrix response" },
  "tools.cn_coupling_matrix_synthesize_explicit": { zh: "耦合矩阵综合（显式）", en: "Coupling matrix synthesis (explicit)" },
  "tools.cn_coupling_matrix_synthesize_n2": { zh: "耦合矩阵综合（N+2）", en: "Coupling matrix synthesis (N+2)" },
  "tools.cn_cps_analysis": { zh: "共面带状线 CPS 分析", en: "Coplanar stripline (CPS) analysis" },
  "tools.cn_cps_synthesis": { zh: "共面带状线 CPS 综合", en: "Coplanar stripline (CPS) synthesis" },
  "tools.cn_cpw_analysis": { zh: "共面波导 CPW 分析", en: "Coplanar waveguide (CPW) analysis" },
  "tools.cn_cpw_synthesis": { zh: "共面波导 CPW 综合", en: "Coplanar waveguide (CPW) synthesis" },
  "tools.cn_cpwg_analysis": { zh: "接地共面波导 CPWG 分析", en: "Conductor-backed CPW (CPWG) analysis" },
  "tools.cn_cpwg_synthesis": { zh: "接地共面波导 CPWG 综合", en: "Conductor-backed CPW (CPWG) synthesis" },
  "tools.cn_ecss_multipactor_fd": { zh: "ECSS 微放电频域判据", en: "ECSS multipactor frequency-domain criterion" },
  "tools.cn_ipc2152_trace_temp_rise": { zh: "IPC-2152 走线温升", en: "IPC-2152 trace temperature rise" },
  "tools.cn_microstrip_analysis": { zh: "微带线分析", en: "Microstrip analysis" },
  "tools.cn_microstrip_lambda_g": { zh: "微带导波波长 λg", en: "Microstrip guided wavelength λg" },
  "tools.cn_microstrip_loss_heat": { zh: "微带损耗与发热", en: "Microstrip loss & heating" },
  "tools.cn_microstrip_synthesis": { zh: "微带线综合", en: "Microstrip synthesis" },
  "tools.cn_parallel_plate_breakdown_margin": { zh: "平行板击穿裕度", en: "Parallel-plate breakdown margin" },
  "tools.cn_patch_f0_symbolic_e13": { zh: "贴片谐振频率（符号回归，实验）", en: "Patch resonance frequency (symbolic regression, experimental)" },
  "tools.cn_patch_length": { zh: "贴片谐振长度", en: "Patch resonance length" },
  "tools.cn_quarter_wave_transformer": { zh: "λ/4 阻抗变换器", en: "Quarter-wave impedance transformer" },
  "tools.cn_resonator_thermal_drift": { zh: "谐振器热漂移", en: "Resonator thermal drift" },
  "tools.cn_stripline_analysis": { zh: "带状线分析", en: "Stripline analysis" },
  "tools.cn_stripline_synthesis": { zh: "带状线综合", en: "Stripline synthesis" },
  "tools.cn_suspended_stripline_analysis": { zh: "悬置带状线分析", en: "Suspended stripline analysis" },
  "tools.cn_suspended_stripline_synthesis": { zh: "悬置带状线综合", en: "Suspended stripline synthesis" },
  "tools.cn_thermal_resistance_stack": { zh: "叠层热阻", en: "Layered thermal resistance" },
  "tools.cn_vswr_convert": { zh: "驻波/反射换算", en: "VSWR/reflection conversion" },
  /* ── 计算器用途兜底（cp_*，zh=旧 CALC_ZH[1] 逐字节同；仅 description
     缺用途段时兜底显示）── */
  "tools.cp_attenuator_bridged_t": { zh: "给定衰减量/Z0 → 桥式 T 网络电阻值", en: "Given attenuation & Z0 → bridged-T network resistors" },
  "tools.cp_attenuator_pi": { zh: "给定衰减量/Z0 → π 网络电阻值", en: "Given attenuation & Z0 → pi-network resistors" },
  "tools.cp_attenuator_t": { zh: "给定衰减量/Z0 → T 网络电阻值", en: "Given attenuation & Z0 → T-network resistors" },
  "tools.cp_cavity_perturbation_shift": { zh: "小样品/形变引起的谐振频率偏移估算", en: "Estimates the resonance shift from a small sample/deformation" },
  "tools.cp_chebyshev_prototype": { zh: "阶数/纹波 → 归一化 g 元件值", en: "Order/ripple → normalized g-values" },
  "tools.cp_chebyshev_prototype_asym": { zh: "非对称端接的低通原型元件值", en: "Lowpass prototype g-values for asymmetric terminations" },
  "tools.cp_chebyshev_refl_fn": { zh: "等纹波反射特性函数取值", en: "Equiripple reflection characteristic evaluation" },
  "tools.cp_coupling_matrix_arrow": { zh: "N+2 耦合矩阵折到箭头形拓扑", en: "Fold an N+2 coupling matrix to the arrow topology" },
  "tools.cp_coupling_matrix_extract": { zh: "从响应/多项式反推耦合矩阵", en: "Recover a coupling matrix from response/polynomial" },
  "tools.cp_coupling_matrix_folded": { zh: "N+2 耦合矩阵折到折叠形拓扑", en: "Fold an N+2 coupling matrix to the folded topology" },
  "tools.cp_coupling_matrix_response": { zh: "给定耦合矩阵 → S11/S21 频响", en: "Given a coupling matrix → S11/S21 frequency response" },
  "tools.cp_coupling_matrix_synthesize_explicit": { zh: "由指定多项式显式综合耦合矩阵", en: "Explicit coupling-matrix synthesis from a given polynomial" },
  "tools.cp_coupling_matrix_synthesize_n2": { zh: "滤波器规格 → N+2 横向耦合矩阵", en: "Filter specs → N+2 transversal coupling matrix" },
  "tools.cp_cps_analysis": { zh: "几何 → Z0/εeff", en: "Geometry → Z0/εeff" },
  "tools.cp_cps_synthesis": { zh: "目标 Z0 → 几何尺寸", en: "Target Z0 → geometry" },
  "tools.cp_cpw_analysis": { zh: "中心导带宽/缝宽 → Z0/εeff", en: "Strip width/gap → Z0/εeff" },
  "tools.cp_cpw_synthesis": { zh: "目标 Z0 → 中心导带宽/缝宽", en: "Target Z0 → strip width/gap" },
  "tools.cp_cpwg_analysis": { zh: "带底地 CPW 几何 → Z0/εeff", en: "Grounded CPW geometry → Z0/εeff" },
  "tools.cp_cpwg_synthesis": { zh: "目标 Z0 → 带底地 CPW 几何", en: "Target Z0 → grounded CPW geometry" },
  "tools.cp_ecss_multipactor_fd": { zh: "间隙×频率 → 微放电击穿裕度（ECSS 口径）", en: "Gap×frequency → multipactor margin (ECSS)" },
  "tools.cp_ipc2152_trace_temp_rise": { zh: "电流/线宽/铜厚 → 走线温升估算", en: "Current/width/copper thickness → trace ΔT estimate" },
  "tools.cp_microstrip_analysis": { zh: "线宽 → Z0/εeff（skrf Hammerstad-Jensen）", en: "Width → Z0/εeff (skrf Hammerstad-Jensen)" },
  "tools.cp_microstrip_lambda_g": { zh: "几何/频率 → εeff、λ0、λg", en: "Geometry/frequency → εeff, λ0, λg" },
  "tools.cp_microstrip_loss_heat": { zh: "导体/介质损耗 → 单位长度耗散功率", en: "Conductor/dielectric loss → dissipated power per unit length" },
  "tools.cp_microstrip_synthesis": { zh: "目标 Z0 → 线宽（求逆+自洽回代）", en: "Target Z0 → width (inversion + self-consistent back-substitution)" },
  "tools.cp_parallel_plate_breakdown_margin": { zh: "间隙/电压 → 击穿场强裕度", en: "Gap/voltage → breakdown field margin" },
  "tools.cp_patch_f0_symbolic_e13": { zh: "自动归纳经验式，默认不放行", en: "Auto-induced empirical formula, blocked by default" },
  "tools.cp_patch_length": { zh: "目标频率/基板 → 贴片长度（Balanis 闭式）", en: "Target frequency/substrate → patch length (Balanis closed form)" },
  "tools.cp_quarter_wave_transformer": { zh: "两端阻抗 → 变换段 Z0 与长度", en: "Two port impedances → section Z0 & length" },
  "tools.cp_resonator_thermal_drift": { zh: "温度变化 → 谐振频率漂移", en: "Temperature change → resonance frequency drift" },
  "tools.cp_stripline_analysis": { zh: "线宽/介质厚 → Z0", en: "Width/dielectric thickness → Z0" },
  "tools.cp_stripline_synthesis": { zh: "目标 Z0 → 线宽", en: "Target Z0 → width" },
  "tools.cp_suspended_stripline_analysis": { zh: "悬置结构几何 → Z0/εeff", en: "Suspended-substrate geometry → Z0/εeff" },
  "tools.cp_suspended_stripline_synthesis": { zh: "目标 Z0 → 悬置结构几何", en: "Target Z0 → suspended-substrate geometry" },
  "tools.cp_thermal_resistance_stack": { zh: "多层材料/厚度 → 总热阻与温升", en: "Layer materials/thicknesses → total thermal resistance & ΔT" },
  "tools.cp_vswr_convert": { zh: "VSWR ↔ |Γ| ↔ 回波损耗 dB 互换", en: "VSWR ↔ |Γ| ↔ return loss (dB) conversion" },
  /* ── 参数表/扫参/结果可视化杂项 ── */
  "tools.ph_required": { zh: "必填", en: "required" },
  "tools.ph_optional": { zh: "可选，留空不传", en: "optional, empty = not sent" },
  "tools.sweep_note": {
    zh: "（逐点串行计算，点数 ≤101）",
    en: " (computed point by point, ≤101 points)",
  },
  "tools.sweep_start": { zh: "起点 ", en: "Start " },
  "tools.sweep_stop": { zh: "终点 ", en: "Stop " },
  "tools.sweep_points": { zh: "点数 ", en: "Points " },
  "tools.sweep_go": { zh: "扫描", en: "Sweep" },
  "tools.sweep_unavailable": {
    zh: "该计算器没有 float/int 数值参数，扫参不可用",
    en: "No float/int numeric parameters for this calculator — sweep unavailable",
  },
  "tools.sweep_not_ready": {
    zh: "扫参控件未就绪（请重选计算器）",
    en: "Sweep controls not ready (reselect the calculator)",
  },
  "tools.sweep_need_num": { zh: "起点/终点须为数值", en: "Start/stop must be numbers" },
  "tools.sweep_points_range": {
    zh: "点数须为 2–101 的整数（上限 101 防滥用）",
    en: "Points must be an integer in 2–101 (capped at 101 against abuse)",
  },
  "tools.sweep_progress_tpl": {
    zh: "扫描中 {i}/{n}（{p}={x}）",
    en: "Sweeping {i}/{n} ({p}={x})",
  },
  "tools.th_response": { zh: "响应", en: "Response" },
  "tools.th_status": { zh: "状态", en: "Status" },
  "tools.skipped_prefix": { zh: "跳过：", en: "skipped: " },
  "tools.no_metric": { zh: "无标量响应指标", en: "no scalar response metric" },
  "tools.sweep_no_curve": {
    zh: "响应指标探测不到（或有效点 <2）——不出曲线只出表格",
    en: "No response metric detected (or fewer than 2 valid points) — table only, no curve",
  },
  "tools.unknown_error": { zh: "未知错误", en: "unknown error" },
  "tools.computing": { zh: "计算中...", en: "Computing..." },
  "tools.done": { zh: "完成", en: "Done" },
  "tools.curve_title_tpl": { zh: "曲线（x={x}）", en: "Curve (x={x})" },
  "tools.curvefam_title_tpl": { zh: "曲线族（x={x}）", en: "Curve family (x={x})" },
  "tools.col": { zh: "列", en: "col" },
  "tools.row": { zh: "行", en: "row" },
  "tools.heat_complex_tpl": {
    zh: "{key} 热图（复数取模 |·|，{rows}×{cols}）",
    en: "{key} heatmap (complex |·|, {rows}×{cols})",
  },
  "tools.heat_tpl": { zh: "{key} 热图（{rows}×{cols}）", en: "{key} heatmap ({rows}×{cols})" },
  "tools.cell_matrix_tpl": { zh: "[{r}×{c} 矩阵]", en: "[{r}×{c} matrix]" },
  "tools.cell_nested_tpl": { zh: "[嵌套数组 {n} 行]", en: "[nested array, {n} rows]" },
  "tools.cell_truncated_tpl": { zh: " …（共 {n} 项）", en: " …({n} total)" },
  "tools.select_aria": { zh: "选择计算器（按组）", en: "Pick a calculator (by group)" },
  "tools.sweep_select_aria": {
    zh: "选择扫参（数值参数）",
    en: "Pick sweep parameter (numeric)",
  },

  /* ═══ aurora_h W4-S1 扩面（+155 键）══════════════════════════════════
     半程三页收尾（agent 全清/loopboard 全清/tools 壳尾清——tools 协议
     标识符组名表仍以中文单源留在视图，见 view_tools 头注）+ 新页四页
     壳层迁移（tune/reports/recipe/campaign：chrome 文案+help 块；动态
     数据面不迁）。zh 值=既有字面同笔迁入（渲染逐字节不变），en 新增；
     help 富文本面=分段 t()（结构留模板、纯文本段进词表，dashboard 先例）；
     拼接数据段一律视图侧 esc 后拼模板，词表值零 HTML 纪律不变。 */

  /* ── agent.*（半程收尾：help 块分段 9 + 浮窗提示 1 + 保存 toast 2 +
     统计条 4 + 审批面板 10 + 沙箱面板 15）── */
  "agent.help_1_tail": {
    zh: "：填 OpenAI 兼容 API（base_url/model/api_key，如 deepseek、gpt、本地 ollama）并保存后，对话即切换为真实 LLM——它能调用框架工具（查 run、诊断、校验配方、生成参数提案）。",
    en: ": fill in an OpenAI-compatible API (base_url/model/api_key, e.g. deepseek, gpt, local ollama) and save — chat switches to a real LLM that can call framework tools (inspect runs, diagnose, validate recipes, propose parameters).",
  },
  "agent.help_2_lead": { zh: "未配置时为", en: "Without configuration it runs in " },
  "agent.help_2_core": { zh: "指令模式", en: "command mode" },
  "agent.help_2_tail": {
    zh: "：直接发 \"list runs\"、\"validate recipes/xxx.yaml\"、\"diagnose run_id\" 等指令。",
    en: ": send commands like \"list runs\", \"validate recipes/xxx.yaml\", \"diagnose run_id\".",
  },
  "agent.help_3_core": { zh: "安全边界", en: "Security boundary" },
  "agent.help_3_mid": {
    zh: "：agent 的工具大多是只读的；唯一会写盘的是「参数提案」——只写 recipes/ 下的提案文件，且要经过自动校验加你在收件箱批准（diff 展示改了什么）才生效。",
    en: ": most agent tools are read-only; the only disk-writing one is the parameter proposal — it only writes proposal files under recipes/, and takes effect only after automatic checks plus your approval in the inbox (a diff shows what changed). ",
  },
  "agent.help_3_core2": { zh: "它接触不到框架源码", en: "It cannot touch the framework source" },
  "agent.help_3_tail": { zh: "。", en: "." },
  "agent.help_4": {
    zh: "内置系统提示词见下方「内置提示词」折叠块（完全透明）。",
    en: "The built-in system prompt is in the collapsible block below (fully transparent).",
  },
  "agent.float_hint": {
    zh: "浮窗可拖拽（按住标题栏）、右下角缩放、可最小化，位置自动记忆。",
    en: "The window is draggable (hold the title bar), resizable from the bottom-right corner, minimizable; position is remembered.",
  },
  "agent.saved_ok": { zh: "模型设置已保存", en: "Model settings saved" },
  "agent.save_failed": { zh: "保存失败", en: "Save failed" },
  "agent.stats_turns_tpl": {
    zh: "轮数 {n} · LLM {t}（{c} 次调用）",
    en: "turns {n} · LLM {t} ({c} calls)",
  },
  "agent.stats_tools_tpl": {
    zh: " · 工具 {n} 次耗时 {t}",
    en: " · tools {n} calls in {t}",
  },
  "agent.stats_tokens_tpl": {
    zh: " · 输入 {i} tok · 输出 {o} tok",
    en: " · in {i} tok · out {o} tok",
  },
  "agent.stats_cache_tpl": { zh: " · 缓存命中 {p}%", en: " · cache hit {p}%" },
  "agent.diff_new": { zh: "(新增)", en: "(new)" },
  "agent.diff_del": { zh: "(删除)", en: "(removed)" },
  "agent.proposal_unreadable": {
    zh: "当前配方值不可读，仅列提案值",
    en: "Current recipe values unreadable — proposal values only",
  },
  "agent.badge_proposal": { zh: "参数提案", en: "Parameter proposal" },
  "agent.th_param": { zh: "参数", en: "Parameter" },
  "agent.th_current": { zh: "当前值", en: "Current" },
  "agent.th_proposed": { zh: "提案值", en: "Proposed" },
  "agent.approve_run": { zh: "批准并执行", en: "Approve & run" },
  "agent.approved_ok": { zh: "已批准并执行", en: "Approved and executed" },
  "agent.approve_fail_lead": { zh: "审批失败: ", en: "Approval failed: " },
  "agent.sandbox_unreadable": { zh: "沙箱状态不可读", en: "Sandbox status unreadable" },
  "agent.sandbox_empty": {
    zh: "无沙箱草稿（agent 在对话中编辑配方后会出现在这里）",
    en: "No sandbox drafts (they appear here after the agent edits a recipe in chat)",
  },
  "agent.no_param_diff": { zh: "无参数差异", en: "No parameter differences" },
  "agent.draft_unmatched_suffix": {
    zh: "（草稿未匹配到 recipes/ 源配方）",
    en: " (draft not matched to a source recipe under recipes/)",
  },
  "agent.source_unmatched": { zh: "来源未匹配", en: "source unmatched" },
  "agent.th_draft": { zh: "草稿值", en: "Draft" },
  "agent.diff_view": { zh: "查看 diff", en: "View diff" },
  "agent.diff_hide": { zh: "收起 diff", en: "Hide diff" },
  "agent.diff_none": { zh: "(无文本差异)", en: "(no textual differences)" },
  "agent.diff_fail": { zh: "diff 失败", en: "diff failed" },
  "agent.promote_send": { zh: "送审批（进收件箱）", en: "Send for approval (to inbox)" },
  "agent.promote_note": {
    zh: "送审批只接受 params 差异，其余节的改动会被自动校验拒绝",
    en: "Only params differences are accepted; changes to other sections are rejected by the automatic checks",
  },
  "agent.promoted_ok": {
    zh: "已生成提案，等你在收件箱批准",
    en: "Proposal created — approve it in the inbox",
  },
  "agent.promote_reject_lead": { zh: "promote 被拒: ", en: "promote rejected: " },
  "agent.reason_unknown": { zh: "未知原因", en: "unknown reason" },

  /* ── loopboard.*（半程收尾全清：help 块分段 10 + 壳 12 + 状态行/空态/
     控制 toast 10 + 公告 1 + 表头 7；takeover(_body) 两键已在 W14-S2 收）── */
  "loopboard.title": { zh: "执行看板", en: "Execution Board" },
  "loopboard.subtitle": {
    zh: "自治环步骤可视化，支持暂停/继续/接管",
    en: "Watch the autonomous loop step by step; pause, resume or take over",
  },
  "loopboard.help_1_lead": {
    zh: "自验证环（提参数 → 验证 → 修正，里程碑由易到难）在后台批处理跑，本页",
    en: "The self-verification loop (propose → verify → fix, milestones easy to hard) runs as a background batch; this page ",
  },
  "loopboard.help_1_core": { zh: "观察", en: "observes" },
  "loopboard.help_1_mid": {
    zh: "当前步骤与逐里程碑验收，并可下发 ",
    en: " the current step and per-milestone acceptance, and can issue ",
  },
  "loopboard.help_1_core2": { zh: "暂停/继续/接管", en: "pause/resume/take-over" },
  "loopboard.help_1_tail": { zh: "。", en: "." },
  "loopboard.help_2_lead": { zh: "暂停是", en: "Pause is " },
  "loopboard.help_2_core": { zh: "协作式", en: "cooperative" },
  "loopboard.help_2_tail": {
    zh: "的：环只在步骤边界响应，不打断进行中的仿真；暂停超时后会自动继续，不会一直挂着。",
    en: ": the loop only responds at step boundaries and never interrupts a running simulation; after a pause timeout it resumes by itself instead of hanging forever.",
  },
  "loopboard.help_3_core": { zh: "接管", en: "Take-over" },
  "loopboard.help_3_tail": {
    zh: "：环立即停下，目前最优参数已存为沙箱草稿——到「Agent 助手」送审批，你批准后继续生效。",
    en: ": the loop stops immediately and the best-so-far parameters are saved as a sandbox draft — send them for approval on the Agent page; they take effect once you approve.",
  },
  "loopboard.board_label": { zh: "看板: ", en: "Board: " },
  "loopboard.reload": { zh: "刷新清单", en: "Reload list" },
  "loopboard.ms_title": { zh: "里程碑（由易到难，逐项验收）", en: "Milestones (easy to hard, accepted one by one)" },
  "loopboard.th_milestone": { zh: "里程碑", en: "Milestone" },
  "loopboard.th_difficulty": { zh: "难度", en: "Difficulty" },
  "loopboard.th_acceptance": { zh: "验收判据", en: "Acceptance" },
  "loopboard.th_status": { zh: "状态", en: "Status" },
  "loopboard.control_title": { zh: "控制（环在步骤边界响应）", en: "Control (loop responds at step boundaries)" },
  "loopboard.pause": { zh: "⏸ 暂停", en: "⏸ Pause" },
  "loopboard.resume": { zh: "▶ 继续", en: "▶ Resume" },
  "loopboard.steps_title": { zh: "步骤历史", en: "Step history" },
  "loopboard.th_step": { zh: "步骤", en: "Step" },
  "loopboard.th_detail": { zh: "详情", en: "Detail" },
  "loopboard.th_time": { zh: "时间", en: "Time" },
  "loopboard.no_boards": {
    zh: "（暂无看板——跑自治环后出现）",
    en: "(no boards yet — run the autonomous loop first)",
  },
  "loopboard.announce_lead": { zh: "执行看板状态：", en: "Execution board status: " },
  "loopboard.current_lead": { zh: "当前步骤：", en: "Current step: " },
  "loopboard.idle_lead": { zh: "配方：", en: "Recipe: " },
  "loopboard.idle_tail": { zh: " · 步骤空闲 · 更新于 ", en: " · step idle · updated " },
  "loopboard.no_milestones": { zh: "无里程碑", en: "No milestones" },
  "loopboard.best_mid": { zh: " · 参数 ", en: " · params " },
  "loopboard.no_points": { zh: "尚无有效评估点", en: "No valid evaluation points yet" },
  "loopboard.no_steps": { zh: "暂无完成步骤", en: "No completed steps yet" },
  "loopboard.select_first": { zh: "先选择看板", en: "Pick a board first" },
  "loopboard.control_sent_tpl": {
    zh: "已下发 {a}，环在步骤边界响应",
    en: "{a} sent — the loop responds at step boundaries",
  },
  "loopboard.control_failed": { zh: "命令失败", en: "Command failed" },

  /* ── tune.*（新页壳层；UI 人性化席 R1 2026-10-19 人话重写：短句动宾、
     每句一件事、术语进白话——内部黑话挪折叠区/原始 JSON）── */
  "tune.title": { zh: "优化调参", en: "Tuning" },
  "tune.subtitle": {
    zh: "自动寻找更好的参数（fake 练手 → 真机精算）",
    en: "Auto-search better params (rehearse on fake, refine on real)",
  },
  "tune.help_flow": {
    zh: "这页自动寻找更好的参数：每一轮（trial）按一组参数值仿真一次并打分，跑完后给出评分最好的那组参数。",
    en: "This page auto-searches better parameter values: each trial simulates once with one parameter set and scores it; when it finishes you get the best-scoring set.",
  },
  "tune.help_channel": {
    zh: "仿真通道先选 fake：秒级出结果、不占用软件许可，用来把流程跑通；确认没问题后再切 hfss（需先启动 ANSYS EDT 并连接）或 openEMS（免费开源）跑真机。",
    en: "Pick the fake channel first: results in seconds, no license needed — use it to walk through the flow. Then switch to hfss (start and connect ANSYS EDT first) or openEMS (free, open source) for real solves.",
  },
  "tune.help_need": {
    zh: "开始前准备两件事：配方里已定义 objectives（什么算\"好\"的判据），且 optimization.params 写了每个参数的搜索范围。缺哪样，去「配方编辑」页补齐再回来。",
    en: "Two things to prepare: the recipe defines objectives (what counts as \"good\") and optimization.params lists a search range for every parameter. Fill any gap on the Recipes page first.",
  },
  "tune.help_read": {
    zh: "跑完看「结果」卡：best 参数表就是推荐的一组值；trial 表和曲线是逐轮成绩，best-so-far 曲线走低=在进步。下一步点「查看 run 详情」看曲线，或回「配方编辑」把参数写回去做真机验证。",
    en: "When it finishes, read the Result card: the best-params table is the recommended set; the trial table and curve show per-round scores (best-so-far trending down = improving). Next: open the run detail for curves, or apply the params back in the recipe editor for a real-solver check.",
  },
  "tune.help_multi": {
    zh: "多保真（可选）：先用 fake 大量粗筛，再把少量候选放到高保真通道精算，省时数倍；结论以高保真复核为准。",
    en: "Multi-fidelity (optional): screen widely with fake first, then refine a few candidates on a high-fidelity solver — hours saved; trust the high-fidelity recheck.",
  },
  "tune.label_recipe": { zh: "配方: ", en: "Recipe: " },
  "tune.label_adapter": { zh: "仿真通道: ", en: "Channel: " },
  "tune.label_trials": { zh: "试验次数: ", en: "Trials: " },
  "tune.label_sampler": { zh: "采样器: ", en: "Sampler: " },
  "tune.label_multi": { zh: "多保真: ", en: "Multi-fidelity: " },
  "tune.start": { zh: "启动", en: "Start" },
  "tune.start_busy": { zh: "启动中…", en: "Starting…" },
  "tune.result_title": { zh: "结果", en: "Result" },
  "tune.trials_title": {
    zh: "实时进度：每轮一行，曲线是\"目前为止最好成绩\"（越低越好）",
    en: "Live progress: one row per trial; the curve is the best score so far (lower is better)",
  },
  "tune.trials_mech": {
    zh: "刷新方式（技术细节）：SSE 进度流可达时推送刷新，否则每 3 秒轮询。",
    en: "Refresh mechanism (technical): pushed via the SSE progress stream when available, else polled every 3 s.",
  },
  "tune.th_params": { zh: "参数", en: "Params" },
  "tune.th_metrics": { zh: "指标", en: "Metrics" },
  "tune.th_value": { zh: "最优值", en: "Best value" },
  "tune.th_unit": { zh: "单位", en: "Unit" },

  /* ── reports.*（新页壳层：help 块分段 8 + 标题/清单题 2 + 表头 3 +
     对比面板 4；动态数据面当时不迁，残量由发布令 S3 批迁清（见下））── */
  "reports.title": { zh: "报告中心", en: "Reports" },
  "reports.help_1": {
    zh: "汇总 runs/ 下所有报告：单次 run 报告（report.md）、夜间回归报告（sim_ci_report.md）、校准报告（calibration/report.md）。",
    en: "Collects every report under runs/: per-run reports (report.md), nightly regression (sim_ci_report.md), calibration (calibration/report.md).",
  },
  "reports.help_2_lead": {
    zh: "点行在右侧渲染；长报告（&gt;3 个 h2/h3 节）自动出",
    en: "Click a row to render it on the right; long reports (&gt;3 h2/h3 sections) get a ",
  },
  "reports.help_2_core": { zh: "左侧目录", en: "left TOC" },
  "reports.help_2_tail": {
    zh: "，点击跳转、滚动高亮当前节。",
    en: " automatically — click to jump, scrolling highlights the current section.",
  },
  "reports.help_3_core": { zh: "双 run 对比", en: "Two-run diff" },
  "reports.help_3_tail": {
    zh: "（页底）：选 A/B 两个 run 出参数递归 diff、指标 Δ 与 S 参数叠图；跨模型对比会显式警示「口径不同」。",
    en: " (page bottom): pick runs A/B for a recursive parameter diff, metric Δ and an S-parameter overlay; cross-model comparisons warn explicitly about the mismatched basis.",
  },
  "reports.help_4": {
    zh: "打印/存 PDF：浏览器「打印 → 另存为 PDF」，导航/工具条/按钮自动隐藏、强制白底。",
    en: "Print/save PDF: use the browser's Print → Save as PDF; nav/toolbars/buttons hide automatically and the background is forced white.",
  },
  "reports.help_5": {
    zh: "原文可折叠展开。报告是产物，中心只读不写。",
    en: "Raw text can be collapsed/expanded. Reports are artifacts — this center is read-only.",
  },
  "reports.list_title": { zh: "报告清单", en: "Report list" },
  "reports.th_kind": { zh: "类型", en: "Kind" },
  "reports.th_model": { zh: "模型", en: "Model" },
  "reports.th_size": { zh: "大小", en: "Size" },
  "reports.pick_hint": { zh: "选择左侧报告查看", en: "Pick a report on the left" },
  "reports.diff_title": {
    zh: "双 run 对比（只读 diff + S 参数叠图）",
    en: "Two-run diff (read-only diff + S-parameter overlay)",
  },
  "reports.diff_go": { zh: "对比", en: "Compare" },
  "reports.diff_hint": {
    zh: "选择两个 run 后点「对比」",
    en: "Pick two runs, then click Compare",
  },

  /* ── recipe.*（新页壳层：help 块分段 7 + 标题/面板题 9 + 工具条 3 +
     表头 4 + 通道选项 3；动态数据面当时不迁，残量由发布令 S3 批迁清（见下））── */
  "recipe.title": { zh: "配方编辑", en: "Recipes" },
  "recipe.help_1_core": { zh: "配方目录", en: "Recipe catalog" },
  "recipe.help_1_tail": {
    zh: "：recipes/ 下全部配方，点选加载。每个配方 = 一次仿真的完整定义：模型、参数、目标、优化设置。工作副本单独分组并标注「工作副本」——原件受保护，保存的改动会写到 runs/recipe_workcopy/，人工审阅后才能写回原件。",
    en: ": all recipes under recipes/, click to load. A recipe is the complete definition of one simulation: model, parameters, objectives, optimizer settings. Work copies are grouped and badged separately — originals are protected; saved changes land in runs/recipe_workcopy/ and reach the original only after human review.",
  },
  "recipe.help_2_core": { zh: "参数表", en: "Parameter table" },
  "recipe.help_2_tail": {
    zh: "：改值即时刷新 3D 预览；「优化范围」是调参时允许搜索的区间。",
    en: ": edits refresh the 3D preview instantly; \"optimization range\" is the interval the tuner may search.",
  },
  "recipe.help_3_core": { zh: "保存并运行", en: "Save & run" },
  "recipe.help_3_tail": {
    zh: "：单次仿真——fake 秒级演示 / openEMS 真跑 / HFSS 真机。",
    en: ": a single simulation — fake (seconds) / openEMS (real FDTD) / HFSS (real solver).",
  },
  "recipe.help_4": {
    zh: "各字段含义见页面底部「配方要素说明」。",
    en: "Field meanings are explained in \"Recipe elements\" at the bottom of the page.",
  },
  "recipe.catalog_title": { zh: "配方目录（点选加载）", en: "Recipe catalog (click to load)" },
  "recipe.loading": { zh: "加载中...", en: "Loading..." },
  "recipe.label_path": { zh: "路径:", en: "Path:" },
  "recipe.load": { zh: "加载", en: "Load" },
  "recipe.label_model": { zh: "模型: ", en: "Model: " },
  "recipe.params_title": { zh: "参数（可改值；保存后生效）", en: "Parameters (editable; takes effect on save)" },
  "recipe.th_name": { zh: "名称", en: "Name" },
  "recipe.th_value": { zh: "值", en: "Value" },
  "recipe.th_unit": { zh: "单位", en: "Unit" },
  "recipe.th_bounds": { zh: "优化范围", en: "Opt. range" },
  "recipe.save": { zh: "保存配方", en: "Save recipe" },
  "recipe.run_once": { zh: "运行一次", en: "Run once" },
  "recipe.opt_fake": { zh: "fake（秒级演示）", en: "fake (seconds, demo)" },
  "recipe.opt_openems": { zh: "openEMS（FDTD 真跑）", en: "openEMS (real FDTD)" },
  "recipe.opt_hfss": { zh: "HFSS（真机）", en: "HFSS (real solver)" },
  "recipe.preview_title": { zh: "3D 预览（随表单值实时渲染）", en: "3D preview (re-rendered live from form values)" },
  "recipe.setup_title": { zh: "扫频 / 仿真设置 (setup) — 表单化", en: "Sweep / simulation settings (setup) — form" },
  "recipe.setup_advanced": {
    zh: "高级：完整 setup JSON（表单改不到的字段在这改）",
    en: "Advanced: full setup JSON (fields the form cannot reach are edited here)",
  },
  "recipe.opt_title": { zh: "优化设置 (optimization + objectives)", en: "Optimization settings (optimization + objectives)" },
  "recipe.opt_advanced": {
    zh: "高级：objectives JSON（目标判定，表单改不到）",
    en: "Advanced: objectives JSON (the objective judge; not in the form)",
  },
  "recipe.help_title": { zh: "配方要素说明", en: "Recipe elements" },

  /* ── campaign.*（新页壳层：help 块分段 8 + 标题/副标题 2 + 工具条 2；
     动态数据面当时不迁，残量由发布令 S3 批迁清（见下））── */
  "campaign.title": { zh: "战役仪表盘", en: "Campaigns" },
  "campaign.subtitle": {
    zh: "trial 状态 · 成本热图 · trial 清单",
    en: "Trial status · cost heatmap · trial list",
  },
  "campaign.help_1_lead": {
    zh: "战役 = 带完整 trial 记录的调参/优化 run；",
    en: "A campaign = a tuning/optimization run with full trial records; ",
  },
  "campaign.help_1_core": { zh: "trial 状态表", en: "the trial status table" },
  "campaign.help_1_tail": {
    zh: "把 trial 按有效性分三类：PASS 已计入统计 / SKIP 已剔除（cost 无效或缺参数） / FAIL 读取出错。",
    en: " sorts trials three ways by validity: PASS counted / SKIP dropped (invalid cost or missing params) / FAIL read error.",
  },
  "campaign.help_2_core": { zh: "成本热图", en: "The cost heatmap" },
  "campaign.help_2_tail": {
    zh: "对所选两参数等宽分箱：格色=平均 cost，格内数字=样本数。",
    en: " bins the two selected parameters into equal-width cells: cell color = mean cost, cell number = sample count.",
  },
  "campaign.help_3_core": { zh: "trial 清单", en: "The trial list" },
  "campaign.help_3_tail": {
    zh: "只画屏幕内的行，几千行也滚动流畅；选中 run 后有进度事件就自动刷新，跑完自动停；没有事件流时不自动刷新，用「刷新」按钮手动刷。",
    en: " renders only the rows on screen, so thousands still scroll smoothly; after picking a run it refreshes on progress events and stops when the run finishes; without an event stream it does not auto-refresh — use Refresh.",
  },
  "campaign.help_4": {
    zh: "所有数字来自优化器落盘的 trial 记录，页面只负责显示。",
    en: "All numbers come from the trial records written by the optimizer; the page only renders.",
  },
  "campaign.label_grid": { zh: "网格", en: "Grid" },
  "campaign.reload": { zh: "刷新", en: "Refresh" },

  /* ── campaign.* 残量清（aurora_h 发布令 S3：动态容器 t() 烘焙——run 下拉
     空态/座位表头与三行语义/进度行/best 行/列表 meta/热图 aria 与 title/
     虚拟列表空态；zh 逐字节+en 新增；数据插值仍在词表外 esc）── */
  "campaign.no_runs_opt": { zh: "（没有带 trial 记录的 run）", en: "(no runs with trial records)" },
  "campaign.no_runs_hint": {
    zh: "先跑一次调参——trial 记录会随 run 落盘",
    en: "Run a tuning job first — trial records are saved with the run",
  },
  "campaign.th_seat": { zh: "trial 状态", en: "Trial status" },
  "campaign.th_n": { zh: "数量", en: "Count" },
  "campaign.th_sem": { zh: "含义", en: "Meaning" },
  "campaign.prog_lead": { zh: "进度 ", en: "Progress " },
  "campaign.prog_pct": { zh: "%（", en: "% (" },
  "campaign.prog_src": { zh: "）· 参数源=", en: ") · params=" },
  "campaign.seat_pass": {
    zh: "trial 已评分且 cost 有效，计入热图/表格/最优",
    en: "Evaluated with a valid cost — counted in heatmap/table/best",
  },
  "campaign.seat_skip": {
    zh: "cost 无效或参数缺失，已剔除不计",
    en: "Invalid cost or missing params — dropped",
  },
  "campaign.seat_fail": {
    zh: "读取出错时整表显示此行（正常为 0）",
    en: "The whole table becomes this row when reading fails (normally 0)",
  },
  "campaign.best_lead": { zh: "最优 trial #", en: "Best trial #" },
  "campaign.best_mid": { zh: "（", en: " (" },
  "campaign.best_tail": { zh: "） · 平均 cost=", en: ") · mean cost=" },
  "campaign.rows_suffix": { zh: " 行", en: " rows" },
  "campaign.truncated": { zh: "（已截断）", en: " (truncated)" },
  "campaign.heat_aria_lead": { zh: "图表：成本热图（", en: "Chart: cost heatmap (" },
  "campaign.heat_aria_mid": { zh: "，", en: ", " },
  "campaign.heat_aria_cells": {
    zh: " 格，格色=格内平均 cost 绿低红高，格内数字=样本数）",
    en: " cells; cell color = mean cost in cell (green low, red high); cell number = sample count)",
  },
  "campaign.heat_title": {
    zh: "格色=格内平均 cost（绿低红高），格内数字=样本数；悬停看格详情",
    en: "Cell color = mean cost in cell (green low, red high); cell number = sample count; hover for cell details",
  },
  "campaign.no_trial_rows": { zh: "无 trial 行", en: "No trial rows" },

  /* ── reports.* 残量清（aurora_h 发布令 S3：TOC aria/对比面（选取提示/
     进行中/失败缺省/跨模型警示分段/两表题头列与空态/叠图题/无产物空态）/
     清单面（计数后缀/三类 kind 徽标/行开 aria/空态/图缺失占位分段）；
     zh 逐字节+en 新增；kind 协议值（sim_ci/calibration）留码侧不变）── */
  "reports.toc_aria": { zh: "报告目录", en: "Report table of contents" },
  "reports.diff_pick_two": { zh: "选两个不同的 run", en: "Pick two different runs" },
  "reports.diff_running": { zh: " 对比中...", en: " Comparing..." },
  "reports.diff_failed": { zh: "对比失败", en: "Diff failed" },
  "reports.warn_lead": { zh: "⚠ 口径不同：模型 a=", en: "⚠ Different calibration: model a=" },
  "reports.warn_mid": { zh: "，通道 a=", en: ", adapter a=" },
  "reports.warn_tail": {
    zh: "——指标与曲线不可直接比较，仅作形态参考。",
    en: " — metrics and curves are not directly comparable; shape reference only.",
  },
  "reports.th_delta_title": { zh: "指标 Δ（b − a）", en: "Metric Δ (b − a)" },
  "reports.col_metric": { zh: "指标", en: "Metric" },
  "reports.no_metrics": { zh: "两侧均无指标", en: "No metrics on either side" },
  "reports.diff_count_lead": {
    zh: "配方快照递归 diff（",
    en: "Recipe snapshot recursive diff (",
  },
  "reports.diff_count_tail": { zh: " 处）", en: " entries)" },
  "reports.col_path": { zh: "路径", en: "Path" },
  "reports.col_kind": { zh: "类型", en: "Kind" },
  "reports.no_diff": { zh: "快照无差异", en: "No snapshot differences" },
  "reports.sparam_overlay": {
    zh: "S 参数叠图（a 前 5 色蓝系 / b 橙系，dB）",
    en: "S-parameter overlay (a: first 5 in blue / b: orange, dB)",
  },
  "reports.no_touchstone": {
    zh: "两侧均无 Touchstone 产物（fake 通道无曲线可叠）",
    en: "No Touchstone artifacts on either side (fake channel has no curves to overlay)",
  },
  "reports.count_suffix": { zh: " 份", en: " reports" },
  "reports.kind_sim_ci": { zh: "夜间回归", en: "Nightly regression" },
  "reports.kind_calibration": { zh: "校准", en: "Calibration" },
  "reports.kind_run": { zh: "run 报告", en: "Run report" },
  "reports.row_open_aria": { zh: "查看报告：", en: "View report: " },
  "reports.empty_hint": {
    zh: "暂无报告——先跑一次 run，报告会汇总在这里",
    en: "No reports yet — run once first; reports aggregate here",
  },
  "reports.img_missing_lead": { zh: "该 run 无此图：", en: "This run has no such figure: " },
  "reports.img_missing_tail": { zh: "（未生成或已清理）", en: " (not generated or cleaned up)" },

  /* ── recipe.* 残量清（aurora_h 发布令 S3：目录行（开行 aria/工作副本徽标/
     参数·目标·频段段/原件与工作副本分组题/审阅入库提示分段）/模型行（模板
     括段/无兜底/工作副本尾注）/参数行 aria 分段/setup 表单六标签/优化表
     （空态/表头/上下界 aria/提示段）/保存与运行 toast；zh 逐字节+en 新增；
     表单字段键（solver/f0/…）为协议键留码侧不变）── */
  "recipe.row_open_aria": { zh: "加载配方：", en: "Load recipe: " },
  "recipe.workcopy_badge": { zh: "工作副本", en: "Working copy" },
  "recipe.row_params_sep": { zh: " 参数 · ", en: " params · " },
  "recipe.row_obj_band": { zh: " 目标 · 频段 ", en: " objectives · band " },
  "recipe.orig_head": { zh: "原件（recipes/）", en: "Originals (recipes/)" },
  "recipe.count_suffix": { zh: " 个", en: " items" },
  "recipe.workcopy_head": {
    zh: "工作副本（runs/recipe_workcopy/）",
    en: "Working copies (runs/recipe_workcopy/)",
  },
  "recipe.review_lead": {
    zh: "写入原件需人工审阅：先与原件 diff 确认改动，再走 ",
    en: "Reaching the original needs human review: confirm the changes via a diff with the original, then go through the ",
  },
  "recipe.review_mid": {
    zh: " 审批收件箱批准；也可以显式写回原件后 git commit 留痕。",
    en: " approval inbox; alternatively write back to the original explicitly and git commit for the record.",
  },
  "recipe.tpl_lead": { zh: "（模板: ", en: " (template: " },
  "recipe.no_template": { zh: "无", en: "none" },
  "recipe.tpl_tail": { zh: "）", en: ")" },
  "recipe.workcopy_suffix": { zh: " · 工作副本", en: " · working copy" },
  "recipe.param_aria_lead": { zh: "参数 ", en: "Parameter " },
  "recipe.param_aria_tail": { zh: " 的值", en: " value" },
  "recipe.f_solver": { zh: "求解器", en: "Solver" },
  "recipe.f_f0": { zh: "扫频起 (GHz)", en: "Sweep start (GHz)" },
  "recipe.f_f1": { zh: "扫频止 (GHz)", en: "Sweep end (GHz)" },
  "recipe.f_points": { zh: "频点数", en: "Points" },
  "recipe.f_conv": { zh: "收敛 Δ", en: "Convergence Δ" },
  "recipe.f_radbox": { zh: "辐射边界", en: "Radiation box" },
  "recipe.no_opt_params": {
    zh: "配方未定义 optimization.params（搜索空间）",
    en: "Recipe defines no optimization.params (search space)",
  },
  "recipe.th_tune_var": { zh: "调参变量", en: "Variable" },
  "recipe.opt_low_aria": { zh: " 搜索下界 low", en: " search lower bound low" },
  "recipe.opt_high_aria": { zh: " 搜索上界 high", en: " search upper bound high" },
  "recipe.opt_hint": {
    zh: "调整搜索空间（low/high）；目标 objectives 在右侧「高级」折叠框里。",
    en: "Adjust the search space (low/high); objectives live in the Advanced panel on the right.",
  },
  "recipe.load_first": { zh: "先加载配方", en: "Load a recipe first" },
  "recipe.setup_bad_json": { zh: "setup 不是合法 JSON", en: "setup is not valid JSON" },
  "recipe.opt_bad_json": {
    zh: "optimization/objectives 不是合法 JSON",
    en: "optimization/objectives is not valid JSON",
  },
  "recipe.save_rejected": { zh: "保存被拒: ", en: "Save rejected: " },
  "recipe.saved_workcopy": { zh: "已另存工作副本: ", en: "Saved as working copy: " },
  "recipe.saved": { zh: "配方已保存", en: "Recipe saved" },
  "recipe.run_done": { zh: "运行完成: cost=", en: "Run finished: cost=" },
  "recipe.run_failed": { zh: "运行失败: ", en: "Run failed: " },

  /* ── tune.* 残量清（aurora_h 发布令 S3：配方信息行分段/启动 toast/运行态
     spin/结果错误前缀/终态读屏公告两串/空态两件式/trial 信息行分段/收敛图
     aria；zh 逐字节+en 新增；结果 JSON 体为纯数据面不迁）── */
  "tune.sel_lead": { zh: "已选配方：", en: "Selected recipe: " },
  "tune.sel_sep": { zh: "，", en: ", " },
  "tune.sel_params": { zh: " 个参数，", en: " params, " },
  "tune.sel_obj": { zh: " 个目标，频段 ", en: " objectives, band " },
  "tune.sel_tail": {
    zh: "。要素含义见「配方编辑」页底部说明。",
    en: ". See the element notes at the bottom of the Recipes page.",
  },
  "tune.path_not_in_catalog": {
    zh: "配方路径未在目录中找到，加载后仍可运行。",
    en: "Recipe path not found in the catalog; you can still run after loading.",
  },
  "tune.started": { zh: "调参已启动，状态轮询中...", en: "Tuning started; polling status..." },
  "tune.running": { zh: " 运行中", en: " Running" },
  "tune.announce_error": { zh: "调参已结束：出错", en: "Tuning ended: error" },
  "tune.announce_done": { zh: "调参已完成", en: "Tuning completed" },
  "tune.empty_hint": {
    zh: "暂无 trial 数据（启动调参后这里实时出点）",
    en: "No trial data yet (points appear here live once tuning starts)",
  },
  "tune.start_action": { zh: "启动调参", en: "Start tuning" },
  "tune.trials_done": { zh: " · 已完成 ", en: " · " },
  "tune.trials_count": { zh: " trials", en: " trials completed" },
  "tune.in_progress": { zh: " 进行中", en: " in progress" },
  "tune.chart_aria": {
    zh: "图表：cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
    en: "Chart: cost, y-axis cost, x-axis trial (with best-so-far step)",
  },
  /* ── tune.* 人性化批（UI 人性化席 R1 2026-10-19）：通道预检卡/错误卡/
     结构化结果卡——错误原文是 API 数据由视图 esc，词表值零 HTML 纪律不变；
     内部函数名（connect()/open_or_create_project()）只出现在视图侧识别
     正则里，词表值全部动作指引白话。 ── */
  "tune.adapter_hint": {
    zh: "想打真机：切 hfss / openEMS（需先启动对应软件并连接）",
    en: "For real solves: switch to hfss / openEMS (start and connect the software first)",
  },
  "tune.opt_fake": {
    zh: "fake —— 先跑通流程（秒级，不用 license）",
    en: "fake — rehearse first (seconds, no license)",
  },
  "tune.opt_hfss": {
    zh: "hfss —— 真机（需先启动 ANSYS EDT 并连接）",
    en: "hfss — real solver (start & connect ANSYS EDT first)",
  },
  "tune.opt_openems": {
    zh: "openEMS —— 真机 FDTD（免费，不占 license）",
    en: "openEMS — real FDTD (free, no license)",
  },
  "tune.pre_hfss_title": {
    zh: "真机通道：先确认 HFSS 已连接",
    en: "Real solver: confirm HFSS is connected first",
  },
  "tune.pre_hfss_body": {
    zh: "hfss 需要 ANSYS EDT 已启动并完成会话连接；还没连接就点「启动」会立刻失败。",
    en: "hfss needs a started, connected ANSYS EDT session; without it, Start fails immediately.",
  },
  "tune.pre_hfss_hint": {
    zh: "还没准备好？先把通道切回 fake 跑通流程。",
    en: "Not ready yet? Switch back to fake and walk through the flow first.",
  },
  "tune.pre_openems_body": {
    zh: "openEMS 是免费开源的 FDTD 引擎（本机已装），不占 license；速度介于 fake 和 hfss 之间。",
    en: "openEMS is a free open-source FDTD engine (installed locally), no license seat; speed sits between fake and hfss.",
  },
  "tune.err_title": { zh: "调参没跑起来", en: "Tuning failed to run" },
  "tune.err_hfss_title": { zh: "HFSS 未连接", en: "HFSS is not connected" },
  "tune.err_hfss_hint": {
    zh: "请先启动 ANSYS EDT 并完成会话连接；或先把通道切回 fake 跑通流程，再回真机。",
    en: "Start ANSYS EDT and connect the session first; or switch back to fake to validate the flow, then return to the real solver.",
  },
  "tune.err_generic_hint": {
    zh: "可以先自查：配方路径是否存在、objectives 是否已定义；或先用 fake 通道试跑一轮。",
    en: "Quick self-checks: does the recipe path exist, are the objectives defined; or try one fake run first.",
  },
  "tune.err_switch_fake": { zh: "切回 fake 通道", en: "Switch to fake" },
  "tune.err_raw_label": {
    zh: "展开原始报错（排障用）",
    en: "Raw error (for debugging)",
  },
  "tune.res_title": { zh: "调参完成", en: "Tuning finished" },
  "tune.res_best_lead": {
    zh: "推荐工作点（best 参数）",
    en: "Recommended operating point (best params)",
  },
  "tune.res_cost_tpl": {
    zh: "最优评分 cost={v}（越小越好）",
    en: "Best score cost={v} (lower is better)",
  },
  "tune.res_stats_tpl": {
    zh: "完成 {done} 轮（{pruned} 轮提前终止）· 用时 {secs} 秒",
    en: "{done} trials done ({pruned} stopped early) · {secs} s",
  },
  "tune.res_metrics_lead": {
    zh: "最优点上的其他指标：",
    en: "Other metrics at the best point:",
  },
  "tune.res_next_runs": { zh: "查看 run 详情", en: "Open run detail" },
  "tune.res_next_recipe": { zh: "回配方编辑", en: "Back to recipe editor" },
  "tune.res_next_hint": {
    zh: "下一步：把这组参数写回配方做真机验证（「配方编辑」页可直接改值）。",
    en: "Next: write these params back into the recipe and verify on a real solver (editable on the Recipes page).",
  },
  "tune.res_details_label": {
    zh: "展开原始结果 JSON",
    en: "Raw result JSON",
  },
  "tune.res_multi_note": {
    zh: "多目标模式：结果是一组各有取舍的 Pareto 前沿点，原始数据见折叠区与 run 详情。",
    en: "Multi-objective mode: the result is a Pareto front of trade-offs; see the folded section and run detail.",
  },
  /* ── S4 发布令批（九页残量清偿）：runs/sparams/gallery/timeline 动态文案
     + 壳面兜底 t() 烘焙（zh 逐字节+en 新增；help 块富 HTML 分段跨段标点归
     前段键尾同 dashboard 先例；view_tools 协议组名豁免口径不变见其头注；
     runs.open_detail_aria 为 dashboard/runs 两页复用键，归属键域页=runs）── */
  "runs.help_1": {
    zh: "每一行 = 一次仿真（run）。点击行进入详情：S 参数曲线（可切分量）、3D 模型、产物、配方快照。",
    en: "Each row = one simulation (run). Click a row for detail: S-parameter curves (per-component switching), 3D model, artifacts, recipe snapshot.",
  },
  "runs.help_2": {
    zh: "顶部筛选：按 run_id 文本、通道、S11 阈值过滤（如只看 -20dB 以下的）。",
    en: "Top filters: run_id text, adapter channel, S11 threshold (e.g. only below -20dB).",
  },
  "runs.caption": {
    zh: "Run 历史：点行打开详情，点表头排序，上方筛选条即时过滤",
    en: "Run History: click a row for detail, click a header to sort, toolbar filters apply instantly",
  },
  "runs.open_detail_aria": { zh: "打开 run 详情：", en: "Open run detail: " },
  "sparams.help_1": {
    zh: "选一个 run，交互查看全部 S 参数曲线：图例点选隐藏/显示、滚轮+滑块缩放、悬停读数。",
    en: "Pick a run to explore all S-parameter curves interactively: click legend to hide/show, wheel+slider zoom, hover readout.",
  },
  "sparams.help_2": {
    zh: "dB 模式看匹配/损耗谷位；相位模式（解缠绕）看电长度/谐振行为。",
    en: "dB mode for matching/loss valleys; phase mode (unwrapped) for electrical length/resonance behavior.",
  },
  "sparams.help_3": {
    zh: "「+外部 .sNp」= 导入本机 Touchstone 文件与 run 产物叠加对比；导入只读，不改 run 产物。相位模式下叠加会清空，避免量纲混淆。",
    en: "\"+ External .sNp\" imports a local Touchstone file and overlays it on the run's curves; imports are read-only. Overlays are cleared in phase mode to avoid mixing units.",
  },
  "sparams.help_4": {
    zh: "「Smith」= 各端口反射系数 S_ii 的 Smith 圆图：恒 r 圆/恒 x 弧是几何网格线，悬停读频率与 Z=Z0(1+Γ)/(1−Γ)；|Γ|→1 时阻抗读数显示 N/A。",
    en: "\"Smith\" plots per-port reflection S_ii on a Smith chart: the constant-r circles / constant-x arcs are grid lines; hover reads frequency and Z=Z0(1+Γ)/(1−Γ); the impedance readout shows N/A as |Γ|→1.",
  },
  "sparams.help_5": {
    zh: "数据源 = run 产物 Touchstone；fake 通道无 Touchstone 时到「Run 详情」看 PNG 曲线。",
    en: "Data source = run artifact Touchstone; for fake runs without Touchstone, see the PNG curves under \"Run Detail\".",
  },
  "sparams.partial_fail": { zh: "部分文件解析失败: ", en: "Some files failed to parse: " },
  "sparams.import_failed": { zh: "导入失败", en: "Import failed" },
  "sparams.already_overlay": { zh: "该文件已叠加", en: "File already overlaid" },
  "sparams.overlayed": { zh: "已叠加: ", en: "Overlaid: " },
  /* ── gallery.*（R2 人性化席续：顶栏人话重写 + 详情抽屉三段 + 参数
     白话兜底 + 72 模板一句话说明；去"显式白名单/规则 7"内部指称，
     详见 view_gallery.js 头注）── */
  "gallery.help_1": {
    zh: "这一页是内置模板库：每张卡点「详情」，看它是什么器件、每个参数是什么意思、数值怎么来的。",
    en: "This page is the built-in template library: click Details on any card to see what the device is, what each parameter means, and where the values come from.",
  },
  "gallery.help_2": {
    zh: "几何预览目前支持 siw/slotline 两族（卡角有「闭式预览」小标记），其余模板看参数详情即可。",
    en: "Live geometry preview currently covers the siw/slotline families only (small corner badge); other templates show parameter details instead.",
  },
  "gallery.help_3": {
    zh: "预览数字由闭式公式即时算出，不做电磁求解；参数初值是内置名义设计值，都能在配方里修改。",
    en: "Preview numbers come from closed-form formulas instantly — no EM solving; initial values are built-in nominal design values, all editable in recipes.",
  },
  "gallery.no_sliders": {
    zh: "本通道无可调滑块（固定参数直算）",
    en: "No adjustable sliders in this channel (fixed params, direct compute)",
  },
  "gallery.computing": { zh: "计算中...", en: "Computing..." },
  /* 详情抽屉三段（说明/参数表/预览）与参数白话兜底（R2） */
  "gallery.drawer_topology": { zh: "结构", en: "Structure" },
  "gallery.drawer_params": {
    zh: "参数表（含义与数值来源）",
    en: "Parameters (meaning & value source)",
  },
  "gallery.th_param": { zh: "参数", en: "Parameter" },
  "gallery.th_mean": { zh: "含义", en: "Meaning" },
  "gallery.th_value": { zh: "当前名义值", en: "Nominal value" },
  "gallery.th_origin": { zh: "数值怎么来的", en: "Where it comes from" },
  "gallery.origin_nominal": {
    zh: "名义设计值——内置缺省（多数按中心频率由闭式综合解出），配方里可改",
    en: "Nominal design value — built-in default (mostly closed-form synthesis at f0); editable in recipes",
  },
  "gallery.origin_substrate": {
    zh: "基板材料常量（与模板文档 substrate 同源）",
    en: "Substrate material constant (same source as the template doc)",
  },
  "gallery.origin_f0": { zh: "设计中心频率", en: "Design center frequency" },
  "gallery.origin_tunable": {
    zh: "名义设计值——可在下方预览拖动滑块即时试算",
    en: "Nominal design value — drag the preview slider below to try values instantly",
  },
  "gallery.origin_other": {
    zh: "模板附加设计参数（与模板文档同源）",
    en: "Extra design parameter (same source as the template doc)",
  },
  "gallery.sem_missing": {
    zh: "（说明未登记——详见模板文档）",
    en: "(no registered description — see the template doc)",
  },
  "gallery.desc_missing": {
    zh: "（该模板说明待补——看下方参数表与结构）",
    en: "(blurb pending — see the parameter table and structure below)",
  },
  "gallery.drawer_preview": {
    zh: "闭式预览（拖动滑块后点「计算」，不做电磁求解）",
    en: "Closed-form preview (drag sliders, then Compute; no EM solving)",
  },
  "gallery.preview_uncovered": {
    zh: "几何预览暂未覆盖此模板（仅 siw/slotline 线分析族支持）——参数含义与数值来源见上表",
    en: "Geometry preview does not cover this template yet (only the siw/slotline line-analysis families) — see the table above for meanings and value sources",
  },
  "gallery.close": { zh: "关闭", en: "Close" },
  "gallery.ports_tpl": { zh: "{n} 端口", en: "{n} ports" },
  /* 参数白话兜底（nominal_params 附加键——语义段未覆盖时显示；键尾=键名） */
  "gallery.gloss_er": { zh: "基板相对介电常数 εr", en: "Substrate relative permittivity" },
  "gallery.gloss_tan_d": { zh: "基板损耗角正切（介质损耗大小）", en: "Substrate loss tangent (dielectric loss)" },
  "gallery.gloss_h_mm": { zh: "基板厚度", en: "Substrate thickness" },
  "gallery.gloss_h_sub_mm": { zh: "基板厚度", en: "Substrate thickness" },
  "gallery.gloss_f0_ghz": { zh: "设计中心频率", en: "Design center frequency" },
  "gallery.gloss_load_r_ohm": { zh: "端接负载电阻", en: "Terminating load resistance" },
  "gallery.gloss_r_ring_mm": { zh: "环体半径（环形结构主几何）", en: "Ring radius (main ring geometry)" },
  /* 72 模板一句话人话说明（键尾=模板名小写化——键命名契约禁大写，
     ms_array_NxN→nxn；view_gallery DESC_KEYS 字面表同名引用） */
  "gallery.desc_atten_pi": {
    zh: "π 型电阻衰减器：三个电阻组成 π 网络，把信号衰减设定的 dB 数，两端仍保持匹配。",
    en: "Pi resistive attenuator: three resistors in a pi network pad the signal by a set number of dB while keeping both ports matched.",
  },
  "gallery.desc_atten_t": {
    zh: "T 型电阻衰减器：三个电阻组成 T 网络，按设定的 dB 数衰减信号并保持匹配。",
    en: "T resistive attenuator: three resistors in a T network pad the signal by a set number of dB while staying matched.",
  },
  "gallery.desc_bend": {
    zh: "微带直角弯折：50Ω 走线拐 90° 直角，用来观察拐弯带来的反射。",
    en: "Microstrip right-angle bend: a 50Ω line turning 90°, used to observe the reflection the corner causes.",
  },
  "gallery.desc_branchline": {
    zh: "Branchline 正交耦合器：方形环四臂各 λ/4，把输入按 3dB 分给直通与耦合两路输出并彼此隔离。",
    en: "Branchline quadrature coupler: a square ring of quarter-wave arms splits the input 3 dB into through and coupled outputs with isolation.",
  },
  "gallery.desc_branchline_2sect": {
    zh: "两节 Branchline 耦合器：多一节分支臂展宽频带的 3dB 正交功分器。",
    en: "Two-section branchline coupler: a 3 dB quadrature splitter with an extra branch section for a wider band.",
  },
  "gallery.desc_cline_coupler": {
    zh: "耦合线定向耦合器：两条 λ/4 平行线靠缝耦合，按设定耦合度分出一路采样信号。",
    en: "Coupled-line directional coupler: two parallel quarter-wave lines couple through a gap to tap a set fraction of the signal.",
  },
  "gallery.desc_coax_waveguide_transition": {
    zh: "波导-同轴过渡：探针从同轴经底壁伸入矩形波导，把两种传输线连接起来。",
    en: "Coax-to-waveguide transition: a probe reaches from the coax through the wall into a rectangular waveguide, joining the two line types.",
  },
  "gallery.desc_coil_nfc": {
    zh: "NFC 平面线圈：方螺旋线圈做 13.56MHz 近场耦合天线（NFC 标签/无线充电类）。",
    en: "Planar NFC coil: a square spiral coil acting as a 13.56 MHz near-field antenna (NFC tags / wireless power).",
  },
  "gallery.desc_combline": {
    zh: "梳状带通滤波器：N 根一端接地、一端加载电容的谐振棒，靠缝耦合选出通带。",
    en: "Combline bandpass filter: resonator rods grounded at one end with loading capacitors at the other, gap-coupled to form the passband.",
  },
  "gallery.desc_coupled_bpf": {
    zh: "平行耦合带通滤波器：N 个半波谐振器错位平行排列，靠边缘缝耦合出通带。",
    en: "Parallel-coupled bandpass filter: half-wave resonators staggered side by side, edge-coupled through gaps.",
  },
  "gallery.desc_coupled_line": {
    zh: "耦合线段：两条平行线靠近摆放，用于观察线间耦合强度。",
    en: "Coupled-line section: two parallel lines placed close together to observe coupling between them.",
  },
  "gallery.desc_cps": {
    zh: "共面带状线 CPS：两条等宽带并行、中央开缝、没有地板的平衡传输线。",
    en: "Coplanar stripline (CPS): two parallel strips with a slot between them and no ground plane — a balanced line.",
  },
  "gallery.desc_cpw": {
    zh: "共面波导 CPW：中心导电带加两侧同层地板，微波集成电路常用走线。",
    en: "Coplanar waveguide: a center strip with ground on both sides in the same layer, common in microwave ICs.",
  },
  "gallery.desc_diplexer": {
    zh: "双工器：一个输入口接低通+高通两条支路，两个频段各走一个输出口。",
    en: "Diplexer: one input feeds low-pass and high-pass branches, so each band exits at its own port.",
  },
  "gallery.desc_dipole": {
    zh: "半波偶极子天线：中央馈电的两根臂，最经典的线天线。",
    en: "Half-wave dipole: two arms fed at a center gap — the classic wire antenna.",
  },
  "gallery.desc_embedded_ms": {
    zh: "嵌入式微带：走线埋进介质内部（上下都有介质），观察埋入对阻抗的影响。",
    en: "Embedded microstrip: the trace buried inside dielectric (covered above and below), to see how burial shifts impedance.",
  },
  "gallery.desc_fgcpw": {
    zh: "有限地共面波导：CPW 但两侧地板是有限宽度，更接近真实版图。",
    en: "Finite-ground CPW: like CPW but with finite-width side grounds, closer to real layouts.",
  },
  "gallery.desc_gysel": {
    zh: "Gysel 功分器：Wilkinson 的变体，用外接端接电阻吸收不平衡功率，耐功率更高。",
    en: "Gysel divider: a Wilkinson variant that dumps imbalance power into external terminations for higher power handling.",
  },
  "gallery.desc_hairpin": {
    zh: "发夹线带通滤波器：半波谐振器折成 U 形并排，省面积的经典平面滤波器。",
    en: "Hairpin bandpass filter: half-wave resonators folded into U shapes side by side — a compact classic.",
  },
  "gallery.desc_hairpin_alt": {
    zh: "交替取向发夹滤波器：U 形谐振器上下翻转交替排列，抑制同向耦合的变体。",
    en: "Alternating hairpin filter: U resonators flipped up and down alternately, a variant that cancels same-direction coupling.",
  },
  "gallery.desc_helix": {
    zh: "螺旋天线：导线绕成方螺旋（法向模），用于紧凑型小天线。",
    en: "Helix antenna: a wire wound into a square spiral (normal mode), for compact small antennas.",
  },
  "gallery.desc_hmsiw": {
    zh: "半模 SIW：把基片集成波导沿中线切一半，尺寸减半的变体。",
    en: "Half-mode SIW: a substrate-integrated waveguide cut in half along its centerline, at half the size.",
  },
  "gallery.desc_ifa": {
    zh: "倒 F 天线（IFA）：一条臂加短路板和馈针，手机等设备常见的紧凑天线。",
    en: "Inverted-F antenna (IFA): an arm with a shorting plate and a feed pin — the common compact antenna in phones.",
  },
  "gallery.desc_interdigital": {
    zh: "交指带通滤波器：N 根 λ/4 谐振棒交错接地排列，缝耦合选频、结构紧凑。",
    en: "Interdigital bandpass filter: quarter-wave rods grounded at alternating ends, gap-coupled and compact.",
  },
  "gallery.desc_inverted_ms": {
    zh: "倒置微带：导带悬在介质下方（与常规微带相反），空气占比高、辐射损耗低。",
    en: "Inverted microstrip: the strip hangs below the substrate (flipped microstrip), lower loss thanks to more air.",
  },
  "gallery.desc_isl_shielded": {
    zh: "屏蔽悬置线：悬置带线再加过孔屏蔽墙，接近全屏蔽的基准传输线。",
    en: "Shielded suspended line: a suspended stripline with via-fence walls, close to a fully shielded reference line.",
  },
  "gallery.desc_lange": {
    zh: "Lange 电桥：四条指状线交指耦合，宽带 3dB 正交功分。",
    en: "Lange coupler: four interleaved finger lines giving a wideband 3 dB quadrature split.",
  },
  "gallery.desc_loop": {
    zh: "环形天线：方环在底边断口处馈电的小型谐振环天线。",
    en: "Loop antenna: a small square ring fed at a gap in one side.",
  },
  "gallery.desc_marchand_balun": {
    zh: "Marchand 巴伦：耦合槽线段把不平衡口转成平衡口（平衡馈电用）。",
    en: "Marchand balun: coupled slotline sections converting an unbalanced port into a balanced one.",
  },
  "gallery.desc_mline": {
    zh: "均匀微带线：一段 50Ω 直走线，校准与引擎仲裁用的基准传输线。",
    en: "Uniform microstrip line: a straight 50Ω run — the reference line for calibration and solver arbitration.",
  },
  "gallery.desc_mmwave_series_array": {
    zh: "毫米波串馈贴片阵：N 个贴片串成一行行波馈电（78GHz 等毫米波频段）。",
    en: "mmWave series-fed patch array: patches chained in a row fed by a traveling wave (78 GHz class bands).",
  },
  "gallery.desc_monopole": {
    zh: "单极子天线：地板上竖起 λ/4 导线，相当于偶极子借地面成像的一半。",
    en: "Monopole: a quarter-wave wire standing on a ground plane — half a dipole mirrored by the ground.",
  },
  "gallery.desc_ms_array_nxn": {
    zh: "反射阵列：N×N 贴片单元平铺，逐单元调相位把入射波反射聚束。",
    en: "Reflectarray: an N-by-N tile of patch cells, each tuning its reflection phase to focus the beam.",
  },
  "gallery.desc_ms_cross": {
    zh: "十字 FSS 单元：十字偶极子组成频率选择表面，对特定极化呈带阻。",
    en: "Cross FSS cell: cross-dipole cells forming a frequency-selective surface, band-reject for one polarization.",
  },
  "gallery.desc_ms_jcross": {
    zh: "耶路撒冷十字 FSS：端加载十字缝单元组成的带通频率选择表面。",
    en: "Jerusalem-cross FSS: end-loaded cross-slot cells forming a band-pass selective surface.",
  },
  "gallery.desc_ms_mushroom": {
    zh: "蘑菇 EBG 单元：贴片+过孔+邻缝电容构成人工磁导体（抑制表面波）。",
    en: "Mushroom EBG cell: patch + via + gap capacitance forming an artificial magnetic conductor (surface-wave suppression).",
  },
  "gallery.desc_ms_patch": {
    zh: "方贴片反射阵单元：反射阵最简单的单元，看贴片尺寸如何调反射相位。",
    en: "Square-patch reflectarray cell: the simplest reflectarray cell — shows how patch size tunes reflection phase.",
  },
  "gallery.desc_ms_ring_patch": {
    zh: "方环+贴片双谐振单元：环与中心贴片两个谐振，扩宽反射相位范围。",
    en: "Ring and patch dual-resonance cell: a square ring plus a center patch widen the reflection-phase range.",
  },
  "gallery.desc_msl_cpw": {
    zh: "微带-CPW 过渡：阶梯渐变段把微带与接地共面波导连接起来。",
    en: "Microstrip-to-CPW transition: a stepped taper joins microstrip and grounded CPW.",
  },
  "gallery.desc_msl_siw_taper": {
    zh: "微带-SIW 过渡：锥形阻抗变换把 50Ω 微带馈进基片集成波导。",
    en: "Microstrip-to-SIW transition: a taper matches 50Ω microstrip into substrate-integrated waveguide.",
  },
  "gallery.desc_msl_slot_transition": {
    zh: "微带-槽线过渡：地板开槽、微带跨槽，把上下两层传输线耦合起来。",
    en: "Microstrip-to-slotline transition: a ground slot crossed by microstrip couples the two layers.",
  },
  "gallery.desc_nway_wilkinson": {
    zh: "N 路 Wilkinson 功分器：树形 T 叉把一路输入分成四路等幅输出。",
    en: "N-way Wilkinson divider: a tree of T junctions splitting one input into four equal outputs.",
  },
  "gallery.desc_patch": {
    zh: "矩形贴片天线：最常见的微带贴片，底部探针馈电在 λ/2 谐振上。",
    en: "Rectangular patch antenna: the standard microstrip patch, probe-fed from below at its half-wave resonance.",
  },
  "gallery.desc_patch_array_1x4": {
    zh: "1×4 贴片阵：四个贴片等距排成一行，并联馈电网络换取更高增益。",
    en: "1-by-4 patch array: four patches in a row fed by a corporate network for higher gain.",
  },
  "gallery.desc_patch_array_2x2": {
    zh: "2×2 贴片阵：四元平面阵，λ/4 变换段做阻抗匹配。",
    en: "2-by-2 patch array: a four-element planar array with quarter-wave transformer matching.",
  },
  "gallery.desc_patch_array_series": {
    zh: "串馈贴片阵：三个贴片用半波互联线串成一行，馈电网络最简。",
    en: "Series-fed patch array: three patches chained by half-wave lines — the simplest feed network.",
  },
  "gallery.desc_patch_eep_1x4": {
    zh: "1×4 独立馈电阵（EEP）：每个单元独立端口，可逐元控制幅相。",
    en: "1-by-4 element-level patch array: each element has its own port for per-element amplitude/phase control.",
  },
  "gallery.desc_patch_eep_2x2": {
    zh: "2×2 独立馈电阵（EEP）：四个单元各接一个端口，波束赋形研究用。",
    en: "2-by-2 element-level patch array: four individually ported elements for beamforming studies.",
  },
  "gallery.desc_pifa": {
    zh: "PIFA 天线：贴片一边短路接地，体积更小的内置天线方案。",
    en: "PIFA: a patch shorted to ground along one edge — a compact internal antenna.",
  },
  "gallery.desc_pyramid_horn": {
    zh: "角锥喇叭天线：波导加四壁张口的喇叭，标准增益天线或馈源。",
    en: "Pyramidal horn: a waveguide flared on four walls — the standard-gain antenna or feed.",
  },
  "gallery.desc_qwt_multisection": {
    zh: "多节 λ/4 阻抗变换器：几节 λ/4 线级联，把两个不同阻抗在带内匹配。",
    en: "Multisection quarter-wave transformer: cascaded quarter-wave lines matching two impedances across a band.",
  },
  "gallery.desc_ratrace": {
    zh: "环形电桥（rat-race）：1.5λ 周长的环，提供 0°/180° 两路功分加隔离。",
    en: "Rat-race hybrid: a 1.5-wavelength ring giving 0°/180° power splits with isolation.",
  },
  "gallery.desc_ridged_wg": {
    zh: "脊波导：矩形波导顶壁加脊，压低截止频率（小尺寸传低频）。",
    en: "Ridged waveguide: a ridge on the top wall lowers the cutoff frequency for compact low-frequency use.",
  },
  "gallery.desc_ring_resonator": {
    zh: "微带环谐振器：闭环环带靠两条缝耦合，介质材料/介电常数测量常用。",
    en: "Microstrip ring resonator: a closed ring coupled through two gaps, common for material/permittivity measurement.",
  },
  "gallery.desc_schiffman": {
    zh: "Schiffman 移相器：耦合 U 形段产生约 90° 定差相移，馈电网络相位补偿用。",
    en: "Schiffman phase shifter: a coupled U-section producing a near-constant 90° differential phase for feed networks.",
  },
  "gallery.desc_sicl": {
    zh: "基片集成同轴（SICL）：上下地板加两列过孔围成矩形同轴腔，屏蔽性好。",
    en: "SICL: via walls plus top and bottom grounds forming a rectangular coax — well shielded.",
  },
  "gallery.desc_sir_bpf": {
    zh: "阶梯阻抗谐振（SIR）带通：高低阻抗段拼接的谐振棒，比均匀棒更紧凑。",
    en: "SIR bandpass filter: rods built from high/low impedance sections, more compact than uniform rods.",
  },
  "gallery.desc_siw": {
    zh: "基片集成波导（SIW）：基板里两排金属过孔围成波导，性能介于微带与波导之间。",
    en: "SIW: two rows of metal vias in the substrate forming a waveguide — between microstrip and waveguide.",
  },
  "gallery.desc_slot": {
    zh: "缝隙天线：地板开缝、微带跨槽馈电，是贴片天线的互补结构。",
    en: "Slot antenna: a slot cut in the ground fed by microstrip crossing it — the complement of a patch.",
  },
  "gallery.desc_slotline": {
    zh: "槽线：单面金属开缝构成的传输线（本模板两端用波导端口馈电）。",
    en: "Slotline: a transmission line formed by a slot in a single metal layer (waveguide ports here).",
  },
  "gallery.desc_slotline_lumped": {
    zh: "槽线（集总端口版）：同一种槽线，改用跨槽集总端口馈电的范式版本。",
    en: "Slotline (lumped-port variant): the same slotline fed by a lumped port bridging the slot.",
  },
  "gallery.desc_sma_launcher": {
    zh: "SMA 边缘弹射座：板边同轴转微带，实测夹具的标准输入接口。",
    en: "SMA end-launcher: an edge coax-to-microstrip connector, the standard fixture interface.",
  },
  "gallery.desc_stepped_impedance": {
    zh: "阶梯阻抗滤波器：高/低阻抗段交替级联，靠线宽变化实现滤波。",
    en: "Stepped-impedance filter: alternating high/low impedance sections filtering through width changes.",
  },
  "gallery.desc_stripline": {
    zh: "带状线：中心导带夹在上下两层地板之间，全屏蔽平面传输线。",
    en: "Stripline: a center strip sandwiched between two ground planes — fully shielded.",
  },
  "gallery.desc_suspended_stripline": {
    zh: "悬置带线：基板悬在腔中、导带位于腔的中面，空气占比高损耗低。",
    en: "Suspended stripline: the substrate floats in a cavity with the strip at mid-height — low loss from high air share.",
  },
  "gallery.desc_tjunc": {
    zh: "微带 T 接头：主线中点分出支臂，最基础的功分不连续结构。",
    en: "Microstrip T-junction: a branch splitting off the main line — the basic power-split discontinuity.",
  },
  "gallery.desc_varactor_bpf": {
    zh: "变容管调谐滤波器：发夹滤波器加载变容电容，调偏压即可改中心频率。",
    en: "Varactor-tuned bandpass: a hairpin filter loaded with varactor capacitance — bias voltage tunes the center frequency.",
  },
  "gallery.desc_via": {
    zh: "过孔过渡：金属化孔把上下两层的走线连接起来（层间垂直互连）。",
    en: "Via transition: a metalized barrel connecting traces on the two layers (vertical interconnect).",
  },
  "gallery.desc_vivaldi_tsa": {
    zh: "Vivaldi 天线：地板上指数张口的槽，端射行波天线（宽带毫米波常用）。",
    en: "Vivaldi antenna: an exponentially flared slot in the ground — a broadband end-fire traveling-wave antenna.",
  },
  "gallery.desc_wilkinson": {
    zh: "Wilkinson 功分器：T 型分叉加两段 λ/4 臂和隔离电阻，把一路分成两路等幅输出。",
    en: "Wilkinson divider: a T split with two quarter-wave arms and an isolation resistor — one input, two equal outputs.",
  },
  "gallery.desc_wstep": {
    zh: "微带宽度阶跃：走线宽度在中点突变，观察阶跃反射的基本不连续。",
    en: "Microstrip width step: a sudden width change at mid-line — the basic step discontinuity.",
  },
  "gallery.desc_xcheb_bpf4": {
    zh: "交叉耦合滤波器：四个开路环 2×2 排布并加交叉耦合，做出准椭圆响应。",
    en: "Cross-coupled filter: four open-loop rings in a 2-by-2 layout with a cross coupling for a quasi-elliptic response.",
  },
  "timeline.help_1": {
    zh: "上图：每个 run 的目标成本按时间排列（按配方目标重算，越低越好）——调参/战役是否在进步一目了然，颜色按 adapter 区分。",
    en: "Top: per-run objective cost over time (recomputed from the recipe objectives; lower is better) — progress at a glance, colored by adapter.",
  },
  "timeline.help_2": {
    zh: "下图：最近一次调参 run 的 trial 级 cost 收敛曲线（数据来自 trials 产物）。",
    en: "Bottom: trial-level cost convergence of the latest tuning run (from trials artifacts).",
  },
  "timeline.help_3": {
    zh: "无配方快照或无指标的 run 不画点（计数见状态行）。",
    en: "Runs without a recipe snapshot or metrics are not plotted (see the status line for counts).",
  },

  /* ── optstack.*（发布前置 i18n 软编码批 S2：优化洞察页全清——壳/help/
     画布文字/悬停 title/aria/状态行/空态；API 字符串数据（参数名/来源/
     目标名）照旧模板外拼不进词表值；数字与格式化数值可作 params）── */
  "optstack.title": { zh: "优化洞察", en: "Optimization Insights" },
  "optstack.subtitle": { zh: "Pareto 前沿 · 可行性热图", en: "Pareto front · feasibility heatmap" },
  "optstack.help_1": {
    zh: "Pareto 前沿：nsga2 优化 run 直读落盘的前沿文件 results/pareto_front.json；旧 run 或 TPE 调参 run 由服务端从 trial 记录现算——可行解支配不可行解，同为不可行时总违约量小者胜。",
    en: "Pareto front: nsga2 runs read the stored front file (results/pareto_front.json) directly; for older runs or TPE runs the backend recomputes it from the trial records — feasible solutions dominate infeasible ones, and among infeasible ones the smaller total violation wins.",
  },
  "optstack.help_2": {
    zh: "可行性热图：按 trial 记录里的约束值分格（≤0 视为可行），对所选两参数等宽分箱——格色=可行率、格内数字=样本数、悬停看平均总违约量；无约束的 run 如实显示「不可算」。",
    en: "Feasibility heatmap: bins the two selected parameters into equal-width cells using the constraint values recorded per trial (≤0 = feasible) — cell color = feasible rate, cell number = sample count, hover for the mean total violation; runs without constraints honestly show \"not computable\".",
  },
  "optstack.help_3": {
    zh: "所有数字由本地计算内核算出，页面只负责显示。",
    en: "All numbers come from the local compute kernel; the page only renders.",
  },
  "optstack.reload": { zh: "刷新", en: "Reload" },
  "optstack.x_param": { zh: "x 参数", en: "x param" },
  "optstack.y_param": { zh: "y 参数", en: "y param" },
  "optstack.grid": { zh: "网格", en: "Grid" },
  "optstack.heat_btn": { zh: "可行性热图", en: "Feasibility heatmap" },
  "optstack.no_runs": { zh: "（无 run）", en: "(no runs)" },
  "optstack.src_hint": {
    zh: "先跑一次 tune --multi（nsga2）或带 optimization.constraints 的 tune",
    en: "Run tune --multi (nsga2) or a tune with optimization.constraints first",
  },
  "optstack.tier_front": { zh: "有 Pareto 前沿（pareto_front.json）", en: "Has Pareto front (pareto_front.json)" },
  "optstack.tier_trials": { zh: "有调参轨迹（可由 trials 现算前沿）", en: "Has tuning trajectory (front computable from trials)" },
  "optstack.tier_single": { zh: "单点仿真（无优化轨迹）", en: "Single-point simulation (no optimization trajectory)" },
  "optstack.single_suffix": { zh: " · 单点", en: " · single" },
  "optstack.no_run_selected": { zh: "（先选一个优化 run）", en: "(select an optimization run first)" },
  "optstack.empty_single": {
    zh: "该 run 是单点仿真，没有优化轨迹——请在下拉里选择带 pareto_front.json 的优化 run（或带 trials 的调参 run，可由 trials 现算前沿）。",
    en: "This run is a single-point simulation with no optimization trajectory — pick an optimization run with pareto_front.json in the dropdown (or a tuning run with trials; the front can be computed from trials).",
  },
  "optstack.empty_no_front": {
    zh: "该 run 暂无可画的 Pareto 前沿。",
    en: "This run has no drawable Pareto front yet.",
  },
  "optstack.src_lead": { zh: "来源 ", en: "source " },
  "optstack.src_points_tpl": { zh: "{n} 点", en: "{n} points" },
  "optstack.constraints_lead": { zh: " · 约束 ", en: " · constraints: " },
  "optstack.front_empty": { zh: "前沿为空或目标数不足 2", en: "Front is empty or fewer than 2 objectives" },
  "optstack.series_front": { zh: "前沿", en: "Front" },
  "optstack.series_front_feas": { zh: "前沿（可行）", en: "Front (feasible)" },
  "optstack.series_infeasible": { zh: "不可行", en: "Infeasible" },
  "optstack.violation_axis_suffix": { zh: " 违约量", en: " violation" },
  "optstack.hv_dims_lead": { zh: "目标 {n} 维，散点取前两维（", en: "{n} objectives; the scatter plots the first two (" },
  "optstack.hv_dims_tail": { zh: " 未画）。", en: " not drawn)." },
  "optstack.hv_conv_tpl": { zh: " 超体积收敛：{n} 代，{a} → {b}", en: " hypervolume convergence: {n} generations, {a} → {b}" },
  "optstack.hv_archive_tpl": { zh: "（精英存档{v}）", en: " (elite archive {v})" },
  "optstack.hv_mono_ok": { zh: "弱单调 ✓", en: "weakly monotonic ✓" },
  "optstack.hv_mono_bad": { zh: "非单调 ✗", en: "non-monotonic ✗" },
  "optstack.legend_feas_1": { zh: "可行率 1", en: "feasible rate 1" },
  "optstack.heat_aria_lead": { zh: "图表：可行性热图（", en: "Chart: feasibility heatmap (" },
  "optstack.heat_aria_tail": {
    zh: "，格色=可行率 红（0）→黄（0.5）→绿（1），灰=无样本，格内数字=样本数）",
    en: "; cell color = feasible rate red (0) → yellow (0.5) → green (1), gray = no samples, cell number = sample count)",
  },
  "optstack.heat_info_a_tpl": { zh: "{used}/{total} 条 trial 参与分箱 · 可行 {feas} · ", en: "{used}/{total} trials binned · feasible {feas} · " },
  "optstack.heat_info_b_tpl": { zh: "{cells}/{total} 格有样本（格内数字=样本数；灰=无样本）", en: "{cells}/{total} cells have samples (cell number = sample count; gray = no samples)" },
  "optstack.hover_cell_tpl": { zh: "n={n} 可行 {feas} 可行率 {rate}% 平均总违约 {viol}", en: "n={n} feasible {feas} feasibility {rate}% mean total violation {viol}" },
  "optstack.hover_empty": { zh: "（无样本）", en: "(no samples)" },

  /* ── solvers.*（发布前置 i18n 软编码批 S2：求解器页全清——表数据列
     （type/class）为 API 数据照旧 esc 不迁）── */
  "solvers.title": { zh: "求解器", en: "Solvers" },
  "solvers.help_1_core": { zh: "求解器", en: "Solver" },
  "solvers.help_1_tail": {
    zh: " = 实际执行电磁仿真的引擎。openEMS：免费开源 FDTD（当前可用）；Palace：有限元（未装则不可用）。",
    en: " = the engine that actually runs the EM simulation. openEMS: free open-source FDTD (currently available); Palace: FEM (unavailable if not installed).",
  },
  "solvers.help_2": {
    zh: "HFSS 走商业 license，版本以实装为准（工程导入页留空=服务端缺省）；在「配方编辑」运行按钮旁或「优化调参」的 adapter 下拉中选择。",
    en: "HFSS uses a commercial license; the version is whatever is installed (leave blank on the Import page = server default). Pick it next to the run button in Recipes or in the adapter dropdown under Tuning.",
  },
  "solvers.help_3": {
    zh: "「可视化 N 个」= 该求解器能产出的补充视图数量。",
    en: "\"N visualizations\" = how many supplementary views the solver can produce.",
  },
  "solvers.reg_title": { zh: "注册状态", en: "Registration status" },
  "solvers.loading": { zh: "加载中...", en: "Loading..." },
  "solvers.th_type": { zh: "类型", en: "Type" },
  "solvers.th_class": { zh: "类", en: "Class" },
  "solvers.th_available": { zh: "可用", en: "Available" },
  "solvers.th_viz": { zh: "可视化", en: "Visualizations" },
  "solvers.badge_available": { zh: "可用", en: "Available" },
  "solvers.badge_unavailable": { zh: "不可用", en: "Unavailable" },

  /* ── profile.*（发布前置 i18n 软编码批 S2：剖析页全清——采样结果行的
     产物路径/fmt 为 API 数据照旧模板外拼，textContent 直写零转义需求）── */
  "profile.title": { zh: "剖析", en: "Profiler" },
  "profile.subtitle": { zh: "py-spy 火焰图", en: "py-spy flame graphs" },
  "profile.help_1_lead": { zh: "封装 ", en: "Wraps " },
  "profile.help_1_tail": {
    zh: "：对运行中的进程（按 pid）或新起的命令采样，产物存到 runs/profile/——火焰图 .svg 浏览器直接打开，speedscope .json 可交互探索。",
    en: ": samples a running process (by pid) or a freshly started command; artifacts land in runs/profile/ — the flamegraph .svg opens directly in the browser, the speedscope .json is interactive.",
  },
  "profile.help_2_lead": { zh: "py-spy 缺装时本页如实降级：", en: "If py-spy is missing this page degrades honestly: " },
  "profile.help_2_tail": { zh: " 后刷新即可。", en: " then reload." },
  "profile.help_3": {
    zh: "剖析是开发用工具：只读采样，不影响正在跑的任务；Windows 下附着其他用户的进程需要管理员权限。",
    en: "Profiling is a developer tool: read-only sampling that never disturbs running jobs; attaching to another user's process on Windows needs admin rights.",
  },
  "profile.env_title": { zh: "环境", en: "Environment" },
  "profile.detecting": { zh: "检测中...", en: "Detecting..." },
  "profile.sampling_title": { zh: "采样", en: "Sampling" },
  "profile.target_label": { zh: "目标", en: "Target" },
  "profile.target_pid": { zh: "附着进程 pid", en: "Attach to process pid" },
  "profile.target_cmd": { zh: "新起命令", en: "New command" },
  "profile.cmd_placeholder": { zh: "python scripts/x.py --flag（空格分词）", en: "python scripts/x.py --flag (space-separated)" },
  "profile.dur_label": { zh: "时长 s", en: "Duration s" },
  "profile.rate_label": { zh: "频率 Hz", en: "Rate Hz" },
  "profile.fmt_label": { zh: "格式", en: "Format" },
  "profile.run": { zh: "开始采样", en: "Start sampling" },
  "profile.status_ok_lead": { zh: "py-spy 可用（", en: "py-spy available (" },
  "profile.status_ok_tail": { zh: "）", en: ")" },
  "profile.status_missing": { zh: "py-spy 未安装", en: "py-spy not installed" },
  "profile.sampling_msg": {
    zh: "采样中（页面可切走，采样在服务端）...",
    en: "Sampling in progress (you can leave the page; sampling runs server-side)...",
  },
  "profile.result_lead": { zh: "✓ 产物：", en: "✓ Artifact: " },
  "profile.result_tail": {
    zh: "——runs/ 静态挂载开启时可直接在浏览器打开",
    en: " — open directly in the browser when the runs/ static mount is enabled",
  },

  /* ── playground.*（发布前置 i18n 软编码批 S2：代理 Playground 页全清——
     run 清单选项/滑条标签/曲线名为 API 数据照旧 esc/直拼不迁）── */
  "playground.title": { zh: "代理 Playground", en: "Surrogate Playground" },
  "playground.help_1": {
    zh: "选一个已校准 run（有 calibration 产物），拖动参数滑条实时看代理预测指标。",
    en: "Pick a calibrated run (one with calibration artifacts) and drag the parameter sliders to watch surrogate predictions update in real time.",
  },
  "playground.help_2_core": { zh: "诚实呈现", en: "Honest presentation" },
  "playground.help_2_mid": { zh: "：预测来自校准样本拟合的代理模型，", en: ": predictions come from a surrogate fitted on calibration samples, " },
  "playground.help_2_core2": { zh: "非真值", en: "not ground truth" },
  "playground.help_2_tail": {
    zh: "——旁边列出交叉验证精度 ρ、样本量与最近样本真值对照；要精算以 openEMS/HFSS 求解为准。",
    en: " — cross-validation accuracy ρ, sample size and the nearest-sample truth are listed alongside; high-fidelity numbers come from openEMS/HFSS solves.",
  },
  "playground.help_3": {
    zh: "缺省值=参数界中点；越界滑条值会被裁剪到边界并在状态行提示。",
    en: "Defaults = midpoint of the parameter bounds; out-of-range slider values are clamped to the bounds with a note on the status line.",
  },
  "playground.help_4_lead": {
    zh: "下方探索器沿单轴做参数扫描切片，画后验 mean 曲线并叠加 ",
    en: "The explorer below sweeps one axis at a time, plotting the posterior mean curve with a ",
  },
  "playground.help_4_core": { zh: "±1σ 方差带", en: "±1σ variance band" },
  "playground.help_4_tail": {
    zh: "（面积阴影；仅 smt 族代理有原生逐点 σ，其余如实只画 mean）。",
    en: " (area shading; only smt-family surrogates have native per-point σ, the rest honestly plot the mean only).",
  },
  "playground.compare_title": { zh: "代理预测 vs 最近样本真值", en: "Surrogate prediction vs nearest-sample truth" },
  "playground.auto_predict": { zh: "选择 run 后自动预测", en: "Auto-predicts after a run is selected" },
  "playground.explore_title": { zh: "参数扫描探索（explore：后验 mean±std）", en: "Parameter sweep explorer (explore: posterior mean±std)" },
  "playground.sweep_axis": { zh: "扫参轴", en: "Sweep axis" },
  "playground.n_points": { zh: "点数", en: "Points" },
  "playground.metric": { zh: "指标", en: "Metric" },
  "playground.no_native_std": { zh: "mean（无原生 σ）", en: "mean (no native σ)" },
  "playground.clamped_lead": { zh: "越界裁剪: ", en: "Out-of-bounds clamped: " },
  "playground.th_metric": { zh: "指标", en: "Metric" },
  "playground.th_pred": { zh: "代理预测", en: "Surrogate prediction" },
  "playground.th_nearest_tpl": { zh: "最近样本真值（归一化距离 {d}）", en: "Nearest-sample truth (normalized distance {d})" },
  "playground.no_runs": {
    zh: "暂无有校准产物的 run（先跑校准战役）",
    en: "No runs with calibration artifacts (run a calibration campaign first)",
  },

  /* ── queue.* 残量清（发布前置 i18n 软编码批 S2：help 块/详情面板/状态段；
     表头 model/verdict/remote=协议标识符豁免；战役名/决策日志条目=API 数据
     照旧 esc 不迁）── */
  "queue.help_1_lead": { zh: "战役队列 = runs/ 下已保存的 campaign.plan.json（拆解好的阶段计划）；", en: "Campaign queue = campaign.plan.json files saved under runs/ (stage plans already expanded); " },
  "queue.help_1_core": { zh: "决策日志", en: "decision log" },
  "queue.help_1_tail": { zh: "记录调度器怎么排的：派发顺序、时长预测依据、拒绝了哪些任务。", en: "records how the scheduler decided: dispatch order, duration-prediction sources, and what got rejected." },
  "queue.help_2_core": { zh: "远程机器", en: "Remote machines" },
  "queue.help_2_tail": {
    zh: "（可选）：填机器名后按战役显示 HFSS 阶段的远程配置差异，只读展示、不会真连；mTLS 视服务器配置而定。",
    en: " (optional): enter a machine name to show, per campaign, the remote-attach config delta for HFSS stages — display only, never a live connection; mTLS depends on the server setup.",
  },
  "queue.help_3": { zh: "所有数字由后端算好，页面只负责显示。", en: "All numbers are computed by the backend; the page only renders." },
  "queue.detail_title_suffix": { zh: " — 阶段与决策日志", en: " — stages and decision log" },
  "queue.th_decision": { zh: "决策", en: "Decision" },
  "queue.no_decision_log": {
    zh: "该战役无决策日志（调度前置步未产出或旧计划）",
    en: "No decision log for this campaign (pre-step produced none, or an older plan)",
  },
  "queue.mtls_status_lead": { zh: "mTLS 状态：", en: "mTLS status: " },
  "queue.remote_no_config": { zh: "无配置（本地零变化）", en: "No config (local unchanged)" },
  "queue.dead_tpl": { zh: "（失败/中止 {n}）", en: "({n} failed/aborted)" },
  "queue.jobs_tpl": { zh: "✓ {n} 作业", en: "✓ {n} jobs" },
  "queue.open_log_aria_tpl": { zh: "查看决策日志（{n} 条）", en: "View decision log ({n} entries)" },
  "queue.entries_tpl": { zh: "{n} 条", en: "{n}" },

  /* ── detail.* 残量清（发布前置 i18n 软编码批 S2：曲线图 aria 前缀——
     文件名为 API 数据照旧模板外拼）── */
  "detail.fig_zoom_lead": { zh: "放大查看曲线图：", en: "Zoom curve figure: " },

  /* ═══ 发布前置 i18n 软编码批 S1 扩面（+135 键）════════════════════════
     fieldviz/calibration/import 三页全清接线（本席独占三页；view_fieldviz
     承 farfield/field 双页共壳，fieldviz.* 单域覆盖远场极坐标/Smith 圆图/
     场切片/等值面/远场 3D 五管线）。zh 值=既有字面同笔迁入（渲染逐字节
     不变），en 新增（射频术语口径：衰减=attenuation、扫参=sweep、方向性=
     directivity、半功率波瓣宽度=HPBW、移动立方体=marching cubes）；help
     富文本=分段 t()（结构留模板、纯文本段进词表，dashboard 先例）；拼接
     数据段（run_id/引擎名/警告串）照旧 esc 后拼模板，词表值零 HTML。 */

  /* ── fieldviz.*（远场极坐标 + Smith 圆图 + 场可视化 3D，view_fieldviz）── */
  "fieldviz.ff_help_1": {
    zh: "看什么：openEMS 真跑 run 的远场产物——方向图切面与 3D 数据、增益/效率指标、SAR 表。",
    en: "What you are looking at: far-field artifacts of a real openEMS run — pattern cuts and 3D data, gain/efficiency metrics, SAR tables.",
  },
  "fieldviz.ff_help_2": {
    zh: "极坐标切面：φ=0°（xz 面）与 φ=90°（yz 面），θ −180..180°，dB 相对峰值归一。",
    en: "Polar cuts: φ=0° (xz plane) and φ=90° (yz plane), θ −180..180°, dB normalized to peak.",
  },
  "fieldviz.ff_help_3": {
    zh: "指标口径按官方 nf2ff 教程：Dmax=方向性 dBi，η=辐射效率 Prad/P_acc，G=η·D，HPBW=半功率波瓣宽度；功率闭合=|P_acc−Prad|/P_acc，注入 SAR 时即组织吸收占比。",
    en: "Metrics follow the official nf2ff tutorial: Dmax = directivity (dBi), η = radiation efficiency Prad/P_acc, G = η·D, HPBW = half-power beamwidth; power closure = |P_acc−Prad|/P_acc, i.e. tissue absorption when SAR is injected.",
  },
  "fieldviz.ff_help_4": {
    zh: "SAR（官方 Dipole SAR 教程）：IEEE_62704 1g 平均，含 1W 接受功率归一值。",
    en: "SAR (official Dipole SAR tutorial): IEEE_62704 1 g averaging, including the value normalized to 1 W accepted power.",
  },
  "fieldviz.ff_title": { zh: "远场方向图", en: "Far-Field Pattern" },
  "fieldviz.ff_subtitle": {
    zh: "nf2ff · 方向图/增益/效率 · SAR",
    en: "nf2ff · pattern/gain/efficiency · SAR",
  },
  "fieldviz.ff_empty_opt": { zh: "（无远场产物 run）", en: "(no far-field runs)" },
  "fieldviz.ff_empty_info": {
    zh: "先用 openEMS 通道以 far_field=True 渲染并真跑 patch/dipole 模板",
    en: "render patch/dipole templates with far_field=True on the openEMS adapter and run them for real first",
  },
  "fieldviz.tpl_label": { zh: "模板 ", en: "template " },
  "fieldviz.m_dmax": { zh: "方向性 ", en: "Directivity " },
  "fieldviz.m_gain": { zh: "峰值增益 ", en: "Peak gain " },
  "fieldviz.m_eff": { zh: "辐射效率 ", en: "Radiation efficiency " },
  "fieldviz.m_closure": { zh: "功率闭合 ", en: "Power closure " },
  "fieldviz.m_eta_gate": { zh: "η 门 ", en: "η gate " },
  "fieldviz.m_sar_acc": { zh: " @1W接受", en: " @1W accepted" },
  "fieldviz.m_absorbed": { zh: "吸收占比 ", en: "Absorbed fraction " },
  "fieldviz.cut_label": { zh: " 切面", en: " cut" },
  "fieldviz.cut_hpbw_pre": { zh: "（HPBW ", en: " (HPBW " },
  "fieldviz.paren_close": { zh: "）", en: ")" },
  "fieldviz.aria_chart": { zh: "图表：", en: "Chart: " },
  "fieldviz.polar_aria_mid": {
    zh: " 远场方向图切面（θ −180..180°，dB 相对峰值归一，HPBW ",
    en: " far-field pattern cut (θ −180..180°, dB rel. peak, HPBW ",
  },
  "fieldviz.sar_note_lead": {
    zh: "SAR：IEEE_62704 1g 平均",
    en: "SAR: IEEE_62704 1 g average",
  },
  "fieldviz.sar_f_pre": { zh: "（f_res=", en: " (f_res=" },
  "fieldviz.sar_note_raw_lead": { zh: "原始值 ", en: "raw " },
  "fieldviz.sar_note_tail": {
    zh: "；归一值按 1W 端口接受功率折算）",
    en: "; normalized to 1 W accepted port power)",
  },
  "fieldviz.smith_aria_lead": { zh: "Smith 圆图：", en: "Smith chart: " },
  "fieldviz.smith_aria_none": { zh: "无轨迹", en: "no traces" },
  "fieldviz.smith_note_grid": { zh: "网格 r=", en: "grid r=" },
  "fieldviz.smith_note_mid": { zh: "、±x 同档 · ", en: ", ±x arcs matched · " },
  "fieldviz.smith_note_trace": {
    zh: "轨迹点 = 各频点 Γ（起点=首频）",
    en: "trace points = Γ per frequency (start = first freq)",
  },
  "fieldviz.slice_aria_mid": { zh: " 场切片热图（", en: " field-slice heatmap (" },
  "fieldviz.slice_aria_tail": {
    zh: "，|E| dB 相对体峰值）",
    en: ", |E| dB rel. volume peak)",
  },
  "fieldviz.iso_legend_lead": { zh: "等值面 ", en: "Isosurfaces " },
  "fieldviz.iso_legend_mid": { zh: " dB（相对峰值）· ", en: " dB (rel. peak) · " },
  "fieldviz.iso_legend_verts": { zh: " 顶点 / ", en: " vertices / " },
  "fieldviz.iso_legend_faces": {
    zh: " 三角 · 顶点色=dB（蓝低→红高）· 拖动旋转 / 滚轮缩放",
    en: " triangles · vertex color = dB (blue low → red high) · drag to rotate / wheel to zoom",
  },
  "fieldviz.pattern_aria": {
    zh: "图表：远场 3D 方向图 θ×φ 热图（dB 相对峰值）",
    en: "Chart: far-field 3D pattern θ×φ heatmap (dB rel. peak)",
  },
  "fieldviz.help_1": {
    zh: "数据源 = openEMS 真跑 run 的场 dump 文件：nf2ff 盒六面存时域包络 max|E(t)|，SAR_raw.h5 存频域 |E(f0)|，SAR_1g.h5 存 1g 平均 SAR 体。",
    en: "Data source: field dumps of a real openEMS run — the six nf2ff-box faces hold the time-domain envelope max|E(t)|, SAR_raw.h5 the frequency-domain |E(f0)|, SAR_1g.h5 the 1 g-averaged SAR volume.",
  },
  "fieldviz.help_2": {
    zh: "切片 = 三轴中面的 |E| 热图，dB 相对体峰值、格子按真实 mm 网格画；拖滑块换切片，等值线 −3/−10/−20 dB 可改。",
    en: "Slices are mid-plane |E| heatmaps on the three axes, dB relative to the volume peak, drawn on the true mm grid; drag the slider to change the slice, contour levels −3/−10/−20 dB are editable.",
  },
  "fieldviz.help_3_lead": {
    zh: "等值面：安装 extras ",
    en: "Isosurfaces: install the extras ",
  },
  "fieldviz.help_3_tail": {
    zh: "（PyVista/VTK）后得到三角网 3D 等值面；未安装时自动降级为切片等值线（看引擎标签）。",
    en: " (PyVista/VTK) to get 3D isosurface meshes; without it the page falls back to slice contours (see the engine label).",
  },
  "fieldviz.help_4": {
    zh: "远场 3D 图读 farfield_3d.h5（θ×φ 热图），与 farfield_meta.json 的远场指标联动；「→ 远场极坐标页」跳到同一 run 的极坐标切面。",
    en: "The far-field 3D plot reads farfield_3d.h5 (θ×φ heatmap) and links with the metrics in farfield_meta.json; “→ Far-field polar page” jumps to the polar cuts of the same run.",
  },
  "fieldviz.title": { zh: "场可视化 3D", en: "3D Fields" },
  "fieldviz.subtitle": {
    zh: "DumpHDF5 切片 / 等值面 / 远场 3D",
    en: "DumpHDF5 slices / isosurfaces / far-field 3D",
  },
  "fieldviz.levels_label": { zh: "等值线 dB", en: "Contours dB" },
  "fieldviz.reload": { zh: "刷新", en: "Reload" },
  "fieldviz.goto_polar": { zh: "→ 远场极坐标页", en: "→ Far-field polar page" },
  "fieldviz.empty_opt": { zh: "（无场 dump run）", en: "(no field-dump runs)" },
  "fieldviz.empty_info": {
    zh: "先用 openEMS 通道以 far_field=True / sar=True 真跑 patch/dipole 模板（nf2ff 盒面 dump 即可）",
    en: "render patch/dipole templates with far_field=True / sar=True on the openEMS adapter and run them for real first (box-face dumps suffice for nf2ff)",
  },
  "fieldviz.opt_pre": { zh: "（", en: " (" },
  "fieldviz.opt_farfield": { zh: " · 远场3D", en: " · far-field 3D" },
  "fieldviz.info_steps": { zh: " 步包络", en: "-step envelope" },
  "fieldviz.info_peak": { zh: " · 峰值 ", en: " · peak " },
  "fieldviz.info_engine": { zh: "引擎 ", en: "engine " },
  "fieldviz.info_noviz3d": {
    zh: "（PyVista 未装，等值面降级为等值线）",
    en: " (PyVista not installed — isosurfaces degraded to contours)",
  },
  "fieldviz.m_mirror": { zh: "镜像修正 ", en: "Mirror correction " },
  "fieldviz.no_farfield_meta": {
    zh: "（无 farfield_meta.json：远场指标不可用）",
    en: "(no farfield_meta.json: far-field metrics unavailable)",
  },
  "fieldviz.slice_head_mid": { zh: " 切面（", en: " slice (" },
  "fieldviz.slice_head_idx": { zh: "，索引 ", en: ", index " },
  "fieldviz.iso_head": {
    zh: "等值面（PyVista/VTK marching cubes）",
    en: "Isosurfaces (PyVista/VTK marching cubes)",
  },
  "fieldviz.iso_degrade_engine": { zh: "等值面引擎 ", en: "Isosurface engine " },
  "fieldviz.iso_degrade_levels": { zh: "：电平 ", en: ": levels " },
  "fieldviz.iso_degrade_body": {
    zh: " 已作为等值线叠加在切片热图上（白/黄/橙 = 低→高电平）。安装 ",
    en: " overlaid on the slice heatmaps as contours (white/yellow/orange = low→high). Install ",
  },
  "fieldviz.iso_degrade_tail": {
    zh: " 可得三角网 3D 等值面。",
    en: " for a 3D triangle-mesh isosurface.",
  },
  "fieldviz.iso_fail": { zh: "等值面失败：", en: "Isosurface failed: " },
  "fieldviz.pattern_head_lead": {
    zh: "远场 3D 方向图（",
    en: "Far-field 3D pattern (",
  },
  "fieldviz.no_pattern": {
    zh: "（无 farfield_3d.h5/nf2ff.h5：远场 3D 图不可用）",
    en: "(no farfield_3d.h5/nf2ff.h5: far-field 3D plot unavailable)",
  },

  /* ── calibration.*（校准工作台，view_calibration）── */
  "calibration.help_1": {
    zh: "校准产物一览：每次校准/增广的门判定、交叉验证精度 ρ、样本量与网格档。",
    en: "Calibration artifacts at a glance: per calibrate/augment — gate verdict, cross-validation accuracy ρ, sample count and mesh grade.",
  },
  "calibration.help_2": {
    zh: "点击行看详情：参数空间散点（cost 着色）、验证点偏差、报告全文。",
    en: "Click a row for detail: parameter-space scatter (cost-colored), validation-point deltas, and the full report.",
  },
  "calibration.help_3": {
    zh: "演化图：ρ 随样本量的收敛轨迹 + 跨保真门历史——校准数据是资产，每做一次增广就多一个点。",
    en: "Evolution plot: ρ convergence vs sample count plus cross-fidelity gate history — calibration data is an asset; each augmentation adds a point.",
  },
  "calibration.title": { zh: "校准工作台", en: "Calibration Workbench" },
  "calibration.run_label": { zh: "校准 run", en: "Calibration runs" },
  "calibration.count_unit": { zh: " 个", en: " total" },
  "calibration.caption": {
    zh: "校准 run 清单：点行打开校准详情，点表头排序",
    en: "Calibration run list: click a row for detail, click a header to sort",
  },
  "calibration.th_model": { zh: "模型", en: "Model" },
  "calibration.th_verdict": { zh: "判定", en: "Verdict" },
  "calibration.th_samples": { zh: "样本", en: "Samples" },
  "calibration.th_surrogate": { zh: "代理", en: "Surrogate" },
  "calibration.evo_title": {
    zh: "ρ 演化（样本量 ↔ 代理/跨保真 gate）",
    en: "ρ evolution (samples ↔ surrogate/cross-fidelity gates)",
  },
  "calibration.open_detail_aria": {
    zh: "查看校准详情：",
    en: "View calibration detail: ",
  },
  "calibration.empty": {
    zh: "暂无校准 run——先跑一次校准/增广（校准数据是资产，每做一次增广就多一个点）",
    en: "No calibration runs yet — run a calibrate/augment first (calibration data is an asset; each augmentation adds a point)",
  },
  "calibration.series_sur": { zh: "代理 LOOCV ρ", en: "surrogate LOOCV ρ" },
  "calibration.series_cross": { zh: "跨保真门 ρ", en: "cross-fidelity gate ρ" },
  "calibration.xlabel": { zh: "样本量", en: "samples" },
  "calibration.no_cross": {
    zh: "暂无跨保真门记录",
    en: "No cross-fidelity gate records",
  },
  "calibration.series_points": { zh: "样本点", en: "sample points" },
  "calibration.val_fail": { zh: "验证点失败: ", en: "validation point failed: " },
  "calibration.no_report": { zh: "无报告", en: "no report" },
  "calibration.detail_title": { zh: "校准详情", en: "Calibration detail" },
  "calibration.sum_samples": { zh: "样本 ", en: "samples " },
  "calibration.sum_seed_pre": { zh: "（种子 ", en: " (seed " },
  "calibration.sum_seed_suf": { zh: "）", en: ")" },
  "calibration.param_space": { zh: "参数空间（", en: "Parameter space (" },
  "calibration.param_space_tail": {
    zh: "，颜色=cost 好→差）",
    en: ", color = cost good→bad)",
  },
  "calibration.val_title": {
    zh: "验证点偏差（预测 vs 实际）",
    en: "Validation deltas (predicted vs actual)",
  },
  "calibration.th_param": { zh: "参数", en: "Parameter" },
  "calibration.th_delta": { zh: "|Δ| 指标", en: "|Δ| metric" },
  "calibration.none": { zh: "无", en: "none" },
  "calibration.report_summary": { zh: "校准报告全文", en: "Full calibration report" },

  /* ── import.*（工程导入，view_import；__custom__ 协议哨兵值与示例路径
     placeholder 等 ASCII 协议面不迁）── */
  "import.help_1_core": { zh: "工程文件", en: "Project file" },
  "import.help_1_tail": {
    zh: "：点「浏览」选 .aedt（也可手输路径）；版本留空=跟随服务端缺省（以实装版本为准）。",
    en: ": click Browse to pick a .aedt (or type the path); leave version empty to follow the server default (per the installed version).",
  },
  "import.help_2_tail": {
    zh: " 后列出设计变量：勾选哪些进优化空间、编辑 low/high（默认取 HFSS Optimetrics 扫参范围，没有则 ±20%）。",
    en: " then lists the design variables: pick which enter the optimization space and edit low/high (defaults from the HFSS Optimetrics sweep range, else ±20%).",
  },
  "import.help_3_tail": {
    zh: " 后到「配方编辑」页补目标（objectives），再进「优化调参」。",
    en: " then open the Recipes page to add objectives, and head to Tuning.",
  },
  "import.help_4": {
    zh: "依赖变量（表达式引用其它变量）与非数值变量自动排除。",
    en: "Dependent variables (expressions referencing other variables) and non-numeric variables are excluded automatically.",
  },
  "import.title": { zh: "工程导入", en: "Import Project" },
  "import.subtitle": {
    zh: "HFSS .aedt → 设计规格 → 配方草稿",
    en: "HFSS .aedt → design spec → recipe draft",
  },
  "import.project_label": { zh: "工程文件: ", en: "Project file: " },
  "import.browse": { zh: "浏览…", en: "Browse…" },
  "import.design_label": { zh: "设计名: ", en: "Design name: " },
  "import.design_ph": { zh: "留空取第一个", en: "empty = first design" },
  "import.version_label": { zh: "版本: ", en: "Version: " },
  "import.ver_default": { zh: "服务端缺省（2025.1）", en: "Server default (2025.1)" },
  "import.ver_custom": { zh: "自定义…", en: "Custom…" },
  "import.ver_custom_ph": { zh: "如 2025.2", en: "e.g. 2025.2" },
  "import.read": { zh: "读取工程", en: "Read project" },
  "import.msg_hint": {
    zh: "首次启动 AEDT 需约 30 秒；读取前请确认工程未被其它 AEDT 窗口占用（残留 .lock 会导致失败）。",
    en: "The first AEDT launch takes ~30 s; before reading, make sure the project is not held open by another AEDT window (a stale .lock causes failures).",
  },
  "import.reading": {
    zh: "读取中...（首次启动 AEDT 需 ~30s）",
    en: "Reading... (first AEDT launch takes ~30 s)",
  },
  "import.range_sweep": { zh: "扫参范围", en: "sweep range" },
  "import.spec_title": { zh: "设计规格 — ", en: "Design spec — " },
  "import.spec_vars_pre": { zh: "（", en: " (" },
  "import.spec_vars_mid": { zh: " 个变量，", en: " variables, " },
  "import.spec_range_mid": { zh: " 个已有扫参范围）", en: " with sweep ranges)" },
  "import.th_variable": { zh: "变量", en: "Variable" },
  "import.th_expression": { zh: "表达式", en: "Expression" },
  "import.th_source": { zh: "来源", en: "Source" },
  "import.ports_title": { zh: "端口 / Setup", en: "Ports / Setup" },
  "import.no_ports": { zh: "无端口边界", en: "No port boundaries" },
  "import.none": { zh: "无", en: "none" },
  "import.recipe_title": { zh: "生成配方", en: "Generate recipe" },
  "import.out_label": { zh: "目标文件: ", en: "Target file: " },
  "import.save": { zh: "保存配方草稿", en: "Save recipe draft" },
  "import.save_hint": {
    zh: "保存后到「配方编辑」页加载它，补 objectives（什么算\"好\"）再调参。",
    en: "After saving, load it on the Recipes page and fill in objectives (what counts as \"good\"), then tune.",
  },
  "import.fail_lead": { zh: "导入失败: ", en: "Import failed: " },
  "import.saved_badge": { zh: "已保存", en: "Saved" },
  "import.saved_msg": { zh: "配方草稿已生成", en: "Recipe draft generated" },

  /* ═══ UI 人性化批 R4（交互细节与公共组件）append-only 增量 ═══════════
     ①公共错误卡（kit.js kitApiErrorHtml/showApiError 消费；common.* 三键
     为壳面引用集——kit.js t() 烘焙即计入，test_ui_i18n 死键互证同口径）；
     ②统一 busy 态缺省钮面（common.busy，kitBtnBusy 缺省值）；
     ③空态三件式补齐（runs 零记录引导/datasets 空库与筛选零命中动作化/
     anchors 空注册表/uq 资产跳转钮）；
     ④导入覆盖确认（import.save_confirm_* 三段：正文含动态路径，路径段
     由视图 esc 外拼——词表值零 HTML 纪律不变）。 */
  "common.error_title": { zh: "操作失败", en: "Action failed" },
  "common.error_generic": {
    zh: "操作未成功（服务未就绪或请求异常），可稍后重试",
    en: "The operation did not succeed (service not ready or request error) — try again later",
  },
  "common.error_hint": {
    zh: "若持续失败，请查看服务端日志，或刷新页面重试",
    en: "If this persists, check the server logs or reload the page",
  },
  "common.busy": { zh: "运行中…", en: "Running…" },
  "runs.empty_no_runs": {
    zh: "还没有仿真记录。到「优化调参」页跑一轮，或用命令行先来一发：",
    en: "No simulation runs yet. Start one on the Tuning page, or fire one from the command line: ",
  },
  "runs.goto_tune": { zh: "去优化调参", en: "Go to Tuning" },
  "datasets.empty_none": {
    zh: "还没有数据集（runs/datasets 注册表为空）",
    en: "No datasets yet (the runs/datasets registry is empty)",
  },
  "datasets.empty_none_next": {
    zh: "先跑几轮仿真/校准，再用 rfauto datasets materialize 物化——路线见「使用指南」",
    en: "Run some simulations/calibrations first, then materialize via rfauto datasets materialize — see the Guide",
  },
  "datasets.goto_guide": { zh: "去使用指南", en: "Go to Guide" },
  "datasets.clear_filter": { zh: "清除筛选", en: "Clear filters" },
  "anchors.empty": {
    zh: "注册表为空（knowledge/anchors.yaml 无锚登记）",
    en: "Registry is empty (no anchors in knowledge/anchors.yaml)",
  },
  "uq.goto_calibration": { zh: "去校准工作台", en: "Go to Calibration" },
  "import.save_confirm_title": { zh: "保存配方草稿", en: "Save recipe draft" },
  "import.save_confirm_body_pre": { zh: "将写入 ", en: "This writes " },
  "import.save_confirm_body_tail": {
    zh: " ，同名文件会被覆盖。确定继续？",
    en: " — an existing file at that path will be overwritten. Continue?",
  },
};

/* ═══ 语言档判定：localStorage 显式档 > <html lang> 跟随 > zh 缺省 ═══ */
let _locale = null;

function _detectLocale() {
  try {
    const v = localStorage.getItem(LOCALE_KEY);
    if (LOCALE_MODES.includes(v)) return v;
  } catch { /* 隐私模式等（node 无 localStorage 同此路） */ }
  try {
    const lang = typeof document !== "undefined" &&
      document.documentElement.getAttribute("lang");
    if (lang && String(lang).toLowerCase().indexOf("en") === 0) return "en";
  } catch { /* DOM 缺席（node 行为钉环境） */ }
  return "zh";
}

/* 当前语言档（懒判定+记忆；setLocale 写档后更新）。 */
export function getLocale() {
  if (!LOCALE_MODES.includes(_locale)) _locale = _detectLocale();
  return _locale;
}

/* 切换语言档：写 localStorage + 同步 html lang + 全壳重扫（applyI18nRoot）。
   非法档拒绝返回 false（不抛，#105）。node（无 DOM）只更新记忆与存储语义。 */
export function setLocale(loc) {
  if (!LOCALE_MODES.includes(loc)) return false;
  _locale = loc;
  try { localStorage.setItem(LOCALE_KEY, loc); } catch { /* 隐私模式等 */ }
  try {
    if (typeof document !== "undefined")
      document.documentElement.setAttribute("lang", loc);
  } catch { /* best-effort */ }
  try {
    if (typeof document !== "undefined") applyI18nRoot(document);
  } catch { /* DOM 缺席（node 行为钉环境）静默 */ }
  return true;
}

/* ═══ 词表查询：缺键→键名直返 + console.warn（#105 best-effort，可见诊断
   不炸渲染）；当前档缺值→zh fallback；{name} 占位插值（params 值同为
   开发侧可信串，与字面同信任级——禁止把 API 数据当 params 拼进壳文案）。 */
export function t(key, params) {
  const ent = LOCALES[key];
  const loc = getLocale();
  let s = ent ? (ent[loc] != null ? ent[loc] : ent.zh) : null;
  if (typeof s !== "string") {
    try { console.warn("[i18n] 缺键: " + key); } catch { /* 极旧引擎静默 */ }
    return String(key);
  }
  if (params) {
    for (const k of Object.keys(params))
      s = s.split("{" + k + "}").join(String(params[k]));
  }
  return s;
}

/* ═══ 壳扫描装配：root 内三注入口全量应用（幂等，可重复扫）——
   [data-i18n]→textContent、[data-i18n-ph]→placeholder、
   [data-i18n-aria]→aria-label。返回应用条数（测试/调试消费）。
   纪律：只放静态、永不带动态状态的元素挂 data-i18n（textContent 重扫会
   覆写；内容随数据重建的容器一律用 t() 渲染期烘焙）。 */
export function applyI18nRoot(root) {
  if (!root || typeof root.querySelectorAll !== "function") return 0;
  let n = 0;
  for (const el of root.querySelectorAll("[data-i18n]")) {
    el.textContent = t(el.getAttribute("data-i18n"));
    n++;
  }
  for (const el of root.querySelectorAll("[data-i18n-ph]")) {
    el.setAttribute("placeholder", t(el.getAttribute("data-i18n-ph")));
    n++;
  }
  for (const el of root.querySelectorAll("[data-i18n-aria]")) {
    el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
    n++;
  }
  return n;
}
