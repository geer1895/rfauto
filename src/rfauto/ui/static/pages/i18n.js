/* rfauto UI i18n 骨架（架构批 W1-S2；规格=内部证据目录
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
   sparams 相位轴 + agent 对话浮窗静态面）+ W2-S1 批 4（架构批：
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
  /* ── gallery.*（试点页 2：模板画廊）── */
  "gallery.title": { zh: "模板画廊", en: "Template Gallery" },
  "gallery.subtitle": {
    zh: "交互卡 · 闭式即时预览（PR-5）",
    en: "Interactive cards · closed-form live preview",
  },
  "gallery.filter_placeholder": { zh: "按名称/拓扑过滤…", en: "Filter by name/topology…" },
  "gallery.loading": { zh: "加载中...", en: "Loading..." },
  "gallery.count_tpl": {
    zh: "{n} 模板 · {p} 配闭式预览通道",
    en: "{n} templates · {p} with closed-form preview",
  },
  "gallery.preview_badge": { zh: "闭式预览", en: "Closed-form preview" },
  "gallery.no_preview": { zh: "未配预览通道", en: "No preview channel" },
  "gallery.open_preview": { zh: "打开预览", en: "Open preview" },
  "gallery.preview_prefix": { zh: "闭式预览：", en: "Closed-form preview: " },
  "gallery.compute": { zh: "计算", en: "Compute" },
  "gallery.result_hint": { zh: "拖动滑块后点「计算」", en: "Drag sliders, then click Compute" },
  /* 三态收敛（架构批 W2-S5，R1 #8 批1）：过滤零命中空态（kitEmptyState 消费） */
  "gallery.empty_filter": {
    zh: "无匹配模板——调整过滤词再试",
    en: "No matching templates — adjust the filter",
  },
  /* ── queue.*（试点页 3：调度队列）── */
  "queue.title": { zh: "调度队列", en: "Queue" },
  "queue.subtitle": {
    zh: "战役计划 · G13 决策日志（PR-9）",
    en: "Campaign plans · G13 decision log (PR-9)",
  },
  "queue.runs_root": { zh: "runs 根", en: "runs root" },
  "queue.machine_label": { zh: "remote 机器", en: "Remote machine" },
  "queue.machine_placeholder": { zh: "（留空=不查 remote 面）", en: "(empty = skip remote panel)" },
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
    zh: "未指定 run——请从「Run 列表」或总览点选，或用 #/detail/〈run_id〉 深链直达。",
    en: "No run specified — pick one from Run History or Dashboard, or open #/detail/〈run_id〉 directly.",
  },
  "detail.goto_runs": { zh: "去 Run 列表", en: "Go to Run History" },
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
    zh: "Agent 沙箱草稿（agent 自主编辑先落沙箱；送审批走三层 Gate 进收件箱）",
    en: "Agent sandbox drafts (agent edits land in the sandbox first; sending for approval goes through the three-gate into the inbox)",
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

  /* ═══ W2-S1 i18n 批 4 扩面（+278 键，架构批）════════════════════════
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
    zh: "，并用 P0 门禁（排序一致性 recall≥80%）保证“粗筛挑出来的确实靠谱”。",
    en: " — with a P0 gate (ranking-consistency recall≥80%) guaranteeing “what the screen picks is actually reliable”.",
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
    zh: "fake 粗筛 + 高保真精算的两阶段流程；靠 P0 gate 保证排序一致性。",
    en: "The two-stage flow of fake screening + high-fidelity refinement; the P0 gate keeps rankings consistent.",
  },
  "guide.gl_p0_d": {
    zh: "可信度验收：fake 与高保真对同一批参数的排名 Spearman ρ≥0.8 且 top-5 命中≥80%。",
    en: "Credibility acceptance: fake vs high-fidelity rankings over the same parameters need Spearman ρ≥0.8 and top-5 hit≥80%.",
  },
  "guide.gl_gate_t": { zh: "Agent 三层 Gate", en: "Agent three-layer gate" },
  "guide.gl_gate_d": {
    zh: "LLM 提参数 → L1/L2 自动校验 → 生成 token → 你在收件箱批准才执行。",
    en: "LLM proposes parameters → L1/L2 automatic checks → token issued → runs only after you approve in the inbox.",
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
  "guide.next_1_tail": { zh: " 与 。", en: " and the ." },
  "guide.next_2": {
    zh: "想看某个页面怎么用：每个页面顶部都有「❓ 本页说明」。",
    en: "To learn a specific page: every page has a “❓ Page guide” at the top.",
  },

  /* ── datasets.*（数据集页：runs/datasets 注册表，只读）── */
  "datasets.help_1_lead": {
    zh: "数据集 = 多次 run 的点级数据物化（Parquet/HDF5），是调参/校准/公开集的输入资产；本页",
    en: "Datasets = point-level materializations of many runs (Parquet/HDF5), the input assets for tuning/calibration/public sets; this page is ",
  },
  "datasets.help_1_core": { zh: "只读", en: "read-only" },
  "datasets.help_1_tail": { zh: "。", en: "." },
  "datasets.help_2_lead": {
    zh: "点数据集行 → 行级预览（抽样前 N 行）。",
    en: "Click a point-dataset row for a row-level preview (first N sampled rows). ",
  },
  "datasets.help_2_core": {
    zh: "n_rows 是抽样返回行数，不是全量计数",
    en: "n_rows is the sampled row count, not the full count",
  },
  "datasets.help_2_tail": { zh: "；全量看「点数」列。", en: "; see the Points column for the full count." },
  "datasets.help_3": {
    zh: "「模板族」来自 manifest 登记的 per_family_rows / ground_truth.per_model 键集；旧 manifest 未登记时如实显示“未登记”，不臆测。",
    en: "“Template family” comes from the manifest's per_family_rows / ground_truth.per_model keys; older manifests honestly show “unregistered” rather than guessing.",
  },
  "datasets.title": { zh: "数据集", en: "Datasets" },
  "datasets.subtitle": { zh: "runs/datasets · 只读", en: "runs/datasets · read-only" },
  "datasets.filter_ph": { zh: "按名称/模板族过滤…", en: "filter by name/family…" },
  "datasets.reload": { zh: "刷新", en: "Reload" },
  "datasets.loading": { zh: "加载中...", en: "Loading..." },
  "datasets.all_families": { zh: "全部模板族", en: "All template families" },
  "datasets.count_tpl": { zh: "{n} / {total} 个数据集", en: "{n} / {total} datasets" },
  "datasets.empty_filter": {
    zh: "无匹配数据集（runs/datasets 下先物化）",
    en: "No matching datasets (materialize under runs/datasets first)",
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
    zh: "锚 = (模板族 × 引擎对 × 域) → (常量|曲线|公式|指针) 的物理标定单源（knowledge/anchors.yaml），运行时只读；修订不改历史，新证据登记 -vN+1。指针锚=双引擎分歧双值登记（不产常数、不就地求值）。",
    en: "Anchors = the physical-calibration single source of (template family × engine pair × domain) → (constant|curve|formula|pointer) (knowledge/anchors.yaml), read-only at runtime; revisions never rewrite history, new evidence lands as -vN+1. Pointer anchors register both values on engine disagreement (no constant produced, no in-place evaluation).",
  },
  "anchors.help_2_core": { zh: "状态", en: "Status" },
  "anchors.help_2_tail": {
    zh: "即注册表裁决：active 健在 / stale 已过期 / experimental 实验指针（双值分歧待归因） / awaiting_data 骨架待回填 / retired 退役。无 last_verified 的锚新鲜度如实显示 UNKNOWN（不虚构判定）。",
    en: " is the registry verdict: active / stale / experimental (pointer with disagreed dual values) / awaiting_data (skeleton) / retired. Anchors without last_verified honestly show UNKNOWN freshness (never fabricated).",
  },
  "anchors.help_3": {
    zh: "点锚行看全量记录（provenance / uncertainty / consumers）。",
    en: "Click an anchor row for the full record (provenance / uncertainty / consumers).",
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
    zh: "UQ = 代理蒙特卡洛公差分析：给定校准样本集 + 逐参数公差 σ，免费评估良率 / 指标分布 / 参数敏感性——不跑真机。",
    en: "UQ = surrogate Monte-Carlo tolerance analysis: given a calibration sample set + per-parameter tolerances σ, evaluate yield / metric distributions / parameter sensitivity for free — no solver runs.",
  },
  "uq.help_2_lead": {
    zh: "数值全部由确定性内核（uq_service.surrogate_yield）产出，前端只渲染；",
    en: "All numbers come from the deterministic kernel (uq_service.surrogate_yield); the UI only renders. ",
  },
  "uq.help_2_core": {
    zh: "无样本集/无公差时如实空态，不 mock",
    en: "honest empty states when no sample set/tolerances — never mocked",
  },
  "uq.help_2_tail": { zh: "。", en: "." },
  "uq.help_3": {
    zh: "敏感性 = 单参数 ±1σ 扰动的指标响应幅值合计（|Δmetric| 求和），越大越该优先收公差。",
    en: "Sensitivity = total metric response to a ±1σ perturbation of one parameter (sum of |Δmetric|); larger = tighten that tolerance first.",
  },
  "uq.title": { zh: "UQ 不确定度", en: "UQ" },
  "uq.subtitle": { zh: "代理蒙特卡洛 · 良率 / 分布 / 敏感性", en: "Surrogate Monte-Carlo · yield / distributions / sensitivity" },
  "uq.panel_assets": {
    zh: "① 校准样本集（runs/ 下 samples 资产，点选填入）",
    en: "① Calibration sample sets (samples assets under runs/, click to fill in)",
  },
  "uq.loading": { zh: "加载中...", en: "Loading..." },
  "uq.panel_run": { zh: "② 运行（确定性内核，万点级秒回）", en: "② Run (deterministic kernel, 10k points in seconds)" },
  "uq.label_samples": { zh: "样本集: ", en: "Samples: " },
  "uq.label_kind": { zh: "代理: ", en: "Surrogate: " },
  "uq.label_draws": { zh: "抽样: ", en: "Draws: " },
  "uq.run": { zh: "运行 UQ", en: "Run UQ" },
  "uq.tol_hint": {
    zh: "选中样本集后这里列出逐参数公差 σ（留空=该参数不扰动）",
    en: "After picking a sample set, per-parameter tolerances σ are listed here (empty = parameter not perturbed)",
  },
  "uq.empty_assets": {
    zh: "runs/ 下未发现校准样本集（samples.json 族）——先跑校准或战役，本页如实空态",
    en: "No calibration sample sets (samples.json family) found under runs/ — run a calibration or campaign first; honest empty state",
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
    zh: "该样本集无 bounds 参数清单，σ 需按参数名手填内核参数（或换样本集）",
    en: "This sample set has no bounds parameter list — σ must be filled by parameter name for the kernel (or pick another set)",
  },
  "uq.err_sigma_tpl": { zh: "参数 {p} 的 σ 不是数值", en: "σ of parameter {p} is not a number" },
  "uq.err_sigma_empty": {
    zh: "至少填一个参数公差 σ（内核要求 {param: σ} 非空）",
    en: "Fill at least one parameter tolerance σ (kernel requires non-empty {param: σ})",
  },
  "uq.err_lead": { zh: "UQ 未出结果（如实）：", en: "UQ produced no result (honest): " },
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
  "uq.done_msg": { zh: "UQ 完成（确定性内核）", en: "UQ done (deterministic kernel)" },

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
    zh: "同一 service 也开放在 CLI（rfauto calc）与 MCP（run_calculator）——三壳一个内核；深链 ",
    en: "The same service is exposed on the CLI (rfauto calc) and MCP (run_calculator) — three shells, one kernel; deep link ",
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
    zh: "（逐点串行调 /api/calculators/run，点数 ≤101）",
    en: " (serial per-point calls to /api/calculators/run, ≤101 points)",
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

  /* ═══ 架构批 W4-S1 扩面（+155 键）══════════════════════════════════
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
    zh: "：agent 的工具大多是只读的；唯一会写盘的是「参数提案」——只写 recipes/ 下的提案文件，且必须走三层 Gate + 你在收件箱批准（diff 形式展示改了什么）才生效。",
    en: ": most agent tools are read-only; the only disk-writing one is the parameter proposal — it only writes proposal files under recipes/, and takes effect only after the three-gate plus your approval in the inbox (shown as a diff of what changed). ",
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
    zh: "promote 只放行 params 差异，其余节差异会被 Gate 拒绝",
    en: "promote only passes params differences; other section diffs are rejected by the gate",
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
    zh: "自治环步骤可视 + 暂停/接管（CLI 批处理 + GUI 观察）",
    en: "Autonomous-loop step visualization + pause/take-over (CLI batch + GUI observe)",
  },
  "loopboard.help_1_lead": {
    zh: "自验证环（propose→verify→fix + 由易到难里程碑）以批处理方式在 service 层跑，本页",
    en: "The self-verification loop (propose→verify→fix + easy-to-hard milestones) runs as a batch in the service layer; this page ",
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
    zh: "的：环只在步骤边界响应，不打断进行中的仿真；暂停超时自动续跑（批处理不被无限期挂死）。",
    en: ": the loop only responds at step boundaries and never interrupts a running simulation; a paused loop auto-resumes after timeout (the batch cannot hang forever).",
  },
  "loopboard.help_3_core": { zh: "接管", en: "Take-over" },
  "loopboard.help_3_tail": {
    zh: "：环如实停止（verdict=TAKEN_OVER），best-so-far 参数已落沙箱草稿，去「Agent 助手」promote 走三层 Gate 继续生效。",
    en: ": the loop stops honestly (verdict=TAKEN_OVER), best-so-far params land in the sandbox drafts — go to Agent to promote them through the three-gate.",
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

  /* ── tune.*（新页壳层：help 块分段 7 + 标题/副标题 2 + 工具条 3 +
     面板题 2 + 表头 2；动态数据面当时不迁，残量由发布令 S3 批迁清（见下））── */
  "tune.title": { zh: "优化调参", en: "Tuning" },
  "tune.subtitle": {
    zh: "fake 粗筛 → 高保真精算（多保真）",
    en: "fake screening → high-fidelity refinement (multi-fidelity)",
  },
  "tune.help_1": {
    zh: "：调参用的仿真通道。fake=秒级解析模型（先验证流程）；hfss=真机（慢、耗 license）；openEMS=免费 FDTD。",
    en: ": the simulation channel for tuning. fake = second-scale analytic model (validate the flow first); hfss = real solver (slow, uses license); openEMS = free FDTD.",
  },
  "tune.help_2": {
    zh: "：试验次数——每 trial 仿真一次配方并按 objectives 打分，TPE 采样器会越猜越准。",
    en: ": number of trials — each trial runs the recipe once and scores it against the objectives; the TPE sampler guesses better over time.",
  },
  "tune.help_3_core": { zh: "多保真", en: "Multi-fidelity" },
  "tune.help_3_tail": {
    zh: "：先用 fake 粗筛出 Pareto 候选、再对 top-k 用高保真精算（省时数倍）。可信度看 P0 gate（recall≥80%）。",
    en: ": screen Pareto candidates with fake first, then high-fidelity-run the top-k (saves hours). Credibility via the P0 gate (recall≥80%).",
  },
  "tune.help_4_lead": { zh: "结果里的 ", en: "In the results, " },
  "tune.help_4_tail": {
    zh: "就是推荐工作点，可回「配方编辑」应用后真机验证。",
    en: " is the recommended operating point — apply it back in Recipes and verify on a real solver.",
  },
  "tune.help_5": {
    zh: "调参前确认配方的 objectives 与 optimization.params 范围已定义。",
    en: "Before tuning, make sure the recipe defines objectives and optimization.params ranges.",
  },
  "tune.label_recipe": { zh: "配方: ", en: "Recipe: " },
  "tune.label_multi": { zh: "多保真: ", en: "Multi-fidelity: " },
  "tune.start": { zh: "启动", en: "Start" },
  "tune.result_title": { zh: "结果", en: "Result" },
  "tune.trials_title": {
    zh: "Trial 实时监控（SSE 进度流可达时推送刷新，否则每 3 秒轮询；收敛曲线 = cost 随 trial 下降）",
    en: "Live trial monitor (pushed via SSE progress stream when available, else polled every 3 s; convergence curve = cost vs trial)",
  },
  "tune.th_params": { zh: "参数", en: "Params" },
  "tune.th_metrics": { zh: "指标", en: "Metrics" },

  /* ── reports.*（新页壳层：help 块分段 8 + 标题/清单题 2 + 表头 3 +
     对比面板 4；动态数据面当时不迁，残量由发布令 S3 批迁清（见下））── */
  "reports.title": { zh: "报告中心", en: "Reports" },
  "reports.help_1": {
    zh: "汇总 runs/ 下全部人读报告：run 五要素报告（report.md）、夜间回归（sim_ci_report.md）、校准报告（calibration/report.md）。",
    en: "Collects all human-readable reports under runs/: run five-part reports (report.md), nightly regression (sim_ci_report.md), calibration (calibration/report.md).",
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
    zh: "：recipes/ 下全部配方，点选加载。每个配方 = 一次仿真的完整定义（模型+参数+目标+优化设置）。工作副本（runs/recipe_workcopy/）单独分组显示并标注「工作副本」——保存对原件的改动会重定向到工作副本（原件受保护），人工审阅后经审批链（rfauto inbox）入库。",
    en: ": all recipes under recipes/, click to load. Each recipe = the complete definition of one simulation (model+params+objectives+optimizer settings). Work copies (runs/recipe_workcopy/) are grouped separately and badged — saving changes to a protected original redirects to a work copy; it lands in the original only after human review via the approval chain (rfauto inbox).",
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
    zh: "座位状态 · 成本热图 · trial 虚拟列表（PR-6）",
    en: "Seat status · cost heatmap · trial virtual list (PR-6)",
  },
  "campaign.help_1_lead": {
    zh: "战役 = 带 trials 审计的调参/优化 run；",
    en: "A campaign = a tuning/optimization run with a trials audit; ",
  },
  "campaign.help_1_core": { zh: "座位状态表", en: "the seat status table" },
  "campaign.help_1_tail": {
    zh: "按 cost 有效性三分（PASS 已评入盘 / SKIP 审计行剔除 / FAIL 端点错误态）。",
    en: " splits rows three ways by cost validity (PASS evaluated & counted / SKIP dropped by the audit / FAIL endpoint error state).",
  },
  "campaign.help_2_core": { zh: "成本热图", en: "The cost heatmap" },
  "campaign.help_2_tail": {
    zh: "对所选两参数确定性分箱（格色=平均 cost，格内数字=样本数）。",
    en: " bins the two selected parameters deterministically (cell color = mean cost, cell number = sample count).",
  },
  "campaign.help_3_core": { zh: "trial 虚拟列表", en: "The trial virtual list" },
  "campaign.help_3_tail": {
    zh: "只渲染可视窗口行（千行级滚动 60fps）；选中 run 后订阅 SSE 进度流，流中有事件即自动刷新（终态自动收束）；流不可用或该 run 无事件流（events.jsonl 缺席）时不会自动刷新，用「刷新」按钮手动刷新。",
    en: " renders only the visible window of rows (60fps at thousands of rows); after picking a run it subscribes to the SSE progress stream and auto-refreshes on events (auto-closes on the terminal frame); when the stream is unavailable or the run has none (no events.jsonl) it does not auto-refresh — use Refresh.",
  },
  "campaign.help_4": {
    zh: "数值全部出自 trials 审计文件（优化器落盘），前端只渲染。",
    en: "All numbers come from the trials audit files (written by the optimizer); the UI only renders.",
  },
  "campaign.label_grid": { zh: "网格", en: "Grid" },
  "campaign.reload": { zh: "刷新", en: "Refresh" },

  /* ── campaign.* 残量清（架构批 发布令 S3：动态容器 t() 烘焙——run 下拉
     空态/座位表头与三行语义/进度行/best 行/列表 meta/热图 aria 与 title/
     虚拟列表空态；zh 逐字节+en 新增；数据插值仍在词表外 esc）── */
  "campaign.no_runs_opt": { zh: "（无带 trials 的 run）", en: "(no runs with trials)" },
  "campaign.no_runs_hint": {
    zh: "先跑一次 tune（带 trials 审计的调参/优化 run）",
    en: "Run a tune first (a tuning/optimization run with a trials audit)",
  },
  "campaign.th_seat": { zh: "座位状态", en: "Seat" },
  "campaign.th_n": { zh: "数", en: "Count" },
  "campaign.th_sem": { zh: "语义", en: "Meaning" },
  "campaign.prog_lead": { zh: "座位进度 ", en: "Seat progress " },
  "campaign.prog_pct": { zh: "%（", en: "% (" },
  "campaign.prog_src": { zh: "）· 参数源=", en: ") · params=" },
  "campaign.seat_pass": {
    zh: "trial 已评且 cost 有限（入热图/表/best）",
    en: "Trial evaluated with finite cost (into heatmap/table/best)",
  },
  "campaign.seat_skip": {
    zh: "审计行被剔除（cost 非有限/参数缺失，service 端如实跳过）",
    en: "Audit rows excluded (non-finite cost / missing params; skipped as-is service-side)",
  },
  "campaign.seat_fail": {
    zh: "端点错误态（本载荷 ok=true，无 FAIL；出错时整表换 FAIL 行）",
    en: "Endpoint error state (this payload has ok=true with no FAIL; on error the whole table becomes a FAIL row)",
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

  /* ── reports.* 残量清（架构批 发布令 S3：TOC aria/对比面（选取提示/
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
    zh: "暂无报告——先跑一次 run（五要素报告/夜间回归/校准报告在此汇总）",
    en: "No reports yet — run once first (five-element / nightly regression / calibration reports aggregate here)",
  },
  "reports.img_missing_lead": { zh: "该 run 无此图：", en: "This run has no such figure: " },
  "reports.img_missing_tail": { zh: "（未生成或已清理）", en: " (not generated or cleaned up)" },

  /* ── recipe.* 残量清（架构批 发布令 S3：目录行（开行 aria/工作副本徽标/
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
    zh: "人工审阅后入库：与原件 diff 确认改动 → 经审批链（",
    en: "Promote after manual review: confirm changes via diff with the original → through the approval chain (",
  },
  "recipe.review_mid": {
    zh: " 审批收件箱，propose→approve→apply 三层 Gate）或显式写回原件后 git commit 留痕。",
    en: " approval inbox, propose→approve→apply three-layer Gate) or write back to the original explicitly, then git commit for the record.",
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

  /* ── tune.* 残量清（架构批 发布令 S3：配方信息行分段/启动 toast/运行态
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
  "tune.error_prefix": { zh: "错误: ", en: "Error: " },
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
    zh: "「+外部 .sNp」= 导入本机 Touchstone 文件与 run 产物叠加对比（WP0.3/E8，只读）；相位模式下叠加会清空以防量纲混淆。",
    en: "\"+ External .sNp\" imports local Touchstone files to overlay against run artifacts (WP0.3/E8, read-only); overlaying is cleared in phase mode to avoid mixing dimensions.",
  },
  "sparams.help_4": {
    zh: "「Smith」= 各端口反射系数 S_ii 的 Smith 圆图（G9）：恒 r 圆/恒 x 弧为纯几何网格，悬停读频率与 Z=Z0(1+Γ)/(1−Γ)；|Γ|→1 时阻抗读数置 N/A。",
    en: "\"Smith\" plots per-port reflection S_ii on a Smith chart (G9): constant-r circles / constant-x arcs are pure geometric grids; hover reads frequency and Z=Z0(1+Γ)/(1−Γ); impedance readout shows N/A as |Γ|→1.",
  },
  "sparams.help_5": {
    zh: "数据源 = run 产物 Touchstone；fake 通道无 Touchstone 时到「Run 详情」看 PNG 曲线。",
    en: "Data source = run artifact Touchstone; for fake runs without Touchstone, see the PNG curves under \"Run Detail\".",
  },
  "sparams.partial_fail": { zh: "部分文件解析失败: ", en: "Some files failed to parse: " },
  "sparams.import_failed": { zh: "导入失败", en: "Import failed" },
  "sparams.already_overlay": { zh: "该文件已叠加", en: "File already overlaid" },
  "sparams.overlayed": { zh: "已叠加: ", en: "Overlaid: " },
  "gallery.help_1_lead": {
    zh: "模板卡出自 TEMPLATE_META/TEMPLATE_NOMINAL（与 docs meta.yaml 同源）；",
    en: "Template cards come from TEMPLATE_META/TEMPLATE_NOMINAL (same source as docs meta.yaml); ",
  },
  "gallery.help_1_core": {
    zh: "滑块改值 → 闭式计算器即时预览",
    en: "drag a slider and the closed-form calculator previews instantly",
  },
  "gallery.help_1_tail": { zh: "（零 EM 求解）。", en: " (zero EM solving)." },
  "gallery.help_2_lead": { zh: "闭式预览通道是", en: "Closed-form preview channels are an " },
  "gallery.help_2_core": { zh: "显式白名单", en: "explicit whitelist" },
  "gallery.help_2_tail": {
    zh: "（当前 siw/slotline 线分析族）；未映射模板如实显示\"未配通道\"，不猜不硬凑。",
    en: " (currently the siw/slotline line-analysis family); unmapped templates honestly show \"no channel\" — no guessing, no forcing.",
  },
  "gallery.help_3": {
    zh: "数值只在确定性内核（规则 7）：本页零物理数字产生，滑块初值=注册表名义参数。",
    en: "Numbers only in the deterministic kernel (rule 7): this page produces zero physics numbers; slider initial values = registry nominal params.",
  },
  "gallery.no_sliders": {
    zh: "本通道无可调滑块（固定参数直算）",
    en: "No adjustable sliders in this channel (fixed params, direct compute)",
  },
  "gallery.computing": { zh: "计算中...", en: "Computing..." },
  "timeline.help_1": {
    zh: "上图：每个 run 的目标成本（快照 objectives 确定性重算，越低越好）按时间排列——战役/调参的整体进步一目了然，颜色按 adapter 分通道。",
    en: "Top: per-run objective cost (deterministic recompute from snapshot objectives, lower is better) over time — campaign/tuning progress at a glance, colored by adapter.",
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
  "optstack.subtitle": { zh: "Pareto 前沿 · 可行性热图（E9/E10）", en: "Pareto front · feasibility heatmap (E9/E10)" },
  "optstack.help_1": {
    zh: "Pareto 前沿：nsga2 run 直读 results/pareto_front.json（E9 起落盘，含逐代精英存档超体积 hv_convergence）；旧 run / TPE run 由服务层从 trials 审计现算约束 Pareto（Deb 可行优先支配：可行支配不可行、不可行间总违约量小者优）。",
    en: "Pareto front: nsga2 runs read results/pareto_front.json directly (written since E9, incl. per-generation elite-archive hypervolume hv_convergence); for older runs / TPE runs the service layer computes constrained Pareto live from the trials audit (Deb feasibility-first dominance: feasible dominates infeasible; among infeasible, smaller total violation wins).",
  },
  "optstack.help_2": {
    zh: "可行性热图：读 trials/*.json 的 params + constraint_values（≤0=可行），对所选两参数做确定性等宽分箱——格色=可行率、格内数字=样本数、悬停看平均总违约量；无约束 run 如实报\"不可算\"。",
    en: "Feasibility heatmap: reads params + constraint_values from trials/*.json (≤0 = feasible) and does deterministic equal-width binning over the two selected params — cell color = feasible rate, cell number = sample count, hover for mean total violation; unconstrained runs honestly report \"not computable\".",
  },
  "optstack.help_3": {
    zh: "数值全部出自确定性内核（SpecEvaluator 违约量 / pareto_tools），前端只渲染。",
    en: "All numbers come from the deterministic kernel (SpecEvaluator violations / pareto_tools); the frontend only renders.",
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
  "profile.subtitle": { zh: "py-spy 火焰图（PR-8）", en: "py-spy flame graphs (PR-8)" },
  "profile.help_1_lead": { zh: "封装 ", en: "Wraps " },
  "profile.help_1_tail": {
    zh: "（MIT）：对运行中进程（pid）或新起命令采样，产物落 runs/profile/（flamegraph .svg 浏览器直接看 / speedscope .json 可交互）。",
    en: " (MIT): samples a running process (pid) or a freshly started command; artifacts land in runs/profile/ (flamegraph .svg opens directly in the browser / speedscope .json is interactive).",
  },
  "profile.help_2_lead": { zh: "py-spy 缺装时本页如实降级：", en: "If py-spy is missing this page degrades honestly: " },
  "profile.help_2_tail": { zh: " 后刷新即可。", en: " then reload." },
  "profile.help_3": {
    zh: "剖析是开发面工具：只读采样不改业务状态；Windows 下附着其他用户进程需管理员。",
    en: "Profiling is a developer-facing tool: read-only sampling that never touches business state; attaching to other users' processes on Windows requires admin.",
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
    zh: "——LOOCV ρ/样本量与最近样本真值对照一并列出，精算以 openEMS/HFSS 求解为准。",
    en: " — LOOCV ρ / sample size and the nearest-sample truth are listed side by side; high-fidelity numbers come from openEMS/HFSS solves.",
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
  "queue.help_1_lead": { zh: "战役队列=runs/ 下已落盘的 campaign.plan.json（确定性拆解的阶段计划）；", en: "Campaign queue = campaign.plan.json files already persisted under runs/ (deterministically expanded stage plans); " },
  "queue.help_1_core": { zh: "决策日志", en: "decision log" },
  "queue.help_1_tail": { zh: "出自 G13 确定性调度前置步（派发顺序/预测时长来源/拒绝清单的审计事件）。", en: "comes from the G13 deterministic scheduling pre-step (audit events for dispatch order / predicted-duration sources / rejection list)." },
  "queue.help_2_core": { zh: "remote 面", en: "Remote panel" },
  "queue.help_2_tail": {
    zh: "（可选）：填机器名后按战役显示 HFSS 阶段的远端附着配置增量（只读组装，零真连）；mTLS 是条件项，按服务器接入说明口径如实登记。",
    en: " (optional): enter a machine name to show, per campaign, the remote-attach config delta for HFSS stages (read-only assembly, zero live connections); mTLS is conditional and honestly recorded per the server integration notes.",
  },
  "queue.help_3": { zh: "数据全部出自服务层既有函数，本页只渲染。", en: "All data comes from existing service-layer functions; this page only renders." },
  "queue.detail_title_suffix": { zh: " — 阶段与决策日志", en: " — stages and decision log" },
  "queue.th_decision": { zh: "决策", en: "Decision" },
  "queue.no_decision_log": {
    zh: "该战役无决策日志（调度前置步未产出或旧计划）",
    en: "No decision log for this campaign (pre-step produced none, or an older plan)",
  },
  "queue.mtls_status_lead": { zh: "mTLS 状态：", en: "mTLS status: " },
  "queue.remote_no_config": { zh: "无配置（本地零变化）", en: "No config (local unchanged)" },
  "queue.dead_tpl": { zh: "(死 {n})", en: "({n} dead)" },
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
    zh: "数据源 = openEMS 真跑 run 的 nf2ff 产物（模板 far_field/sar=True 渲染：farfield_cut/3d.csv + farfield_meta.json + sar.csv）。",
    en: "Data source = nf2ff artifacts of a real openEMS run (template rendered with far_field/sar=True: farfield_cut/3d.csv + farfield_meta.json + sar.csv).",
  },
  "fieldviz.ff_help_2": {
    zh: "极坐标切面：φ=0°（xz 面）与 φ=90°（yz 面），θ −180..180°，dB 相对峰值归一。",
    en: "Polar cuts: φ=0° (xz plane) and φ=90° (yz plane), θ −180..180°, dB normalized to peak.",
  },
  "fieldviz.ff_help_3": {
    zh: "指标口径（官方 nf2ff 教程）：Dmax=方向性（dBi），η=Prad/P_acc（辐射效率），G=η·D；HPBW=半功率波瓣宽度；功率闭合=|P_acc−Prad|/P_acc（SAR 注入时 P_acc−Prad=组织吸收）。",
    en: "Metric conventions (official nf2ff tutorial): Dmax = directivity (dBi), η = Prad/P_acc (radiation efficiency), G = η·D; HPBW = half-power beamwidth; power closure = |P_acc−Prad|/P_acc (with SAR injection, P_acc−Prad = tissue absorption).",
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
    zh: "数据源 = openEMS 真跑 run 的 DumpHDF5 产物：nf2ff 盒六面 nf2ff_E_*.h5（时域包络 max|E(t)|）、SAR_raw.h5（频域 |E(f0)|）、SAR_1g.h5（标量 SAR 体）。",
    en: "Data source = DumpHDF5 artifacts of a real openEMS run: six faces of the nf2ff box nf2ff_E_*.h5 (time-domain envelope max|E(t)|), SAR_raw.h5 (frequency-domain |E(f0)|), SAR_1g.h5 (scalar SAR volume).",
  },
  "fieldviz.help_2": {
    zh: "切片：三轴中面 |E| 热图（dB 相对体峰值，单元格按真实 mm 网格绘制），拖滑块改切片索引；等值线 −3/−10/−20 dB 叠加（可改）。",
    en: "Slices: mid-plane |E| heatmaps on the three axes (dB rel. volume peak, cells drawn on the true mm grid) — drag the slider to change the slice index; −3/−10/−20 dB contours overlaid (editable).",
  },
  "fieldviz.help_3_lead": {
    zh: "等值面：安装 extras ",
    en: "Isosurfaces: install the extras ",
  },
  "fieldviz.help_3_tail": {
    zh: "（PyVista/VTK）后为三角网 3D（three.js 渲染）；未安装时诚实降级为切片等值线（engine 标签可见）。",
    en: " (PyVista/VTK) to get a 3D triangle mesh (three.js rendering); without it, honest degradation to slice contours (see the engine label).",
  },
  "fieldviz.help_4": {
    zh: "远场 3D 图（farfield_3d.h5，θ×φ 热图）与 D4 指标（farfield_meta.json）联动；「→ 远场极坐标页」跳到同一 run 的极坐标切面。",
    en: "The far-field 3D plot (farfield_3d.h5, θ×φ heatmap) links with the D4 metrics (farfield_meta.json); “→ Far-field polar page” jumps to the polar cuts of the same run.",
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
    zh: "（无 farfield_meta.json：D4 指标不可用）",
    en: "(no farfield_meta.json: D4 metrics unavailable)",
  },
  "fieldviz.slice_head_mid": { zh: " 切面（", en: " slice (" },
  "fieldviz.slice_head_idx": { zh: "，索引 ", en: ", index " },
  "fieldviz.iso_head": {
    zh: "等值面（PyVista/VTK 移动立方体）",
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
    zh: "校准产物一览：每次 calibrate/augment 的 gate 判定、LOOCV ρ、样本量与网格档。",
    en: "Calibration artifact overview: gate verdicts, LOOCV ρ, sample counts and mesh grades of every calibrate/augment.",
  },
  "calibration.help_2": {
    zh: "点击行看详情：参数空间散点（cost 着色）、验证点偏差、报告全文。",
    en: "Click a row for detail: parameter-space scatter (cost-colored), validation-point deltas, and the full report.",
  },
  "calibration.help_3": {
    zh: "演化图：ρ 随样本量的收敛轨迹 + 跨保真 gate 历史——校准数据是资产，逐次增广都会点亮一个点。",
    en: "Evolution plot: ρ convergence vs sample count + cross-fidelity gate history — calibration data is an asset; every augmentation lights up another point.",
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
    zh: "暂无校准 run——先跑一次 calibrate/augment（校准数据是资产，逐次增广都会点亮一个点）",
    en: "No calibration runs yet — run a calibrate/augment first (calibration data is an asset; every augmentation lights up another point)",
  },
  "calibration.series_sur": { zh: "代理 LOOCV ρ", en: "surrogate LOOCV ρ" },
  "calibration.series_cross": { zh: "跨保真 gate ρ", en: "cross-fidelity gate ρ" },
  "calibration.xlabel": { zh: "样本量", en: "samples" },
  "calibration.no_cross": {
    zh: "暂无跨保真 gate 记录",
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
