/* rfauto 工作台可排序表格（aurora_d UI-R2 自 pages.js 拆出，aurora36
   W3-B 块逐字节搬移）：纯函数三件（columnIsNumeric/sortCellKey/
   sortCellCompare）+ DOM 胶水 makeSortable/mountSortableTables。 */

/* R1 P1-7（guide §12.3 核心交互，全站表格零排序）：通用可排序表格。
   纯函数三件（node 行为钉可测）+ DOM 胶水 makeSortable（对约定标
   data-sortable 的 table 装表头点击排序）。 */

/* 列数值性判别：全部非空单元格均可解析为有限数值且至少一个非空才按数值
   序；混合列回退字典序（不臆测——"3/5" 复合列、"done" 状态列均走字符串）。 */
export function columnIsNumeric(texts) {
  const ts = (texts || []).map((t) => String(t ?? "").trim());
  const ne = ts.filter((t) => t !== "");
  return ne.length > 0 && ne.every((t) => Number.isFinite(+t));
}

/* 单元格排序键：数值列空单元格 → -Infinity（升序恒排最前，"-" 占位的
   缺失值语义）；字符串列取 trim 原文。 */
export function sortCellKey(text, numeric) {
  const t = String(text ?? "").trim();
  if (!numeric) return t;
  const n = +t;
  return Number.isFinite(n) ? n : -Infinity; // ""/"-" 等缺失或非数值文本恒排最前
}

/* 升序比较器：字符串走 localeCompare（numeric collation——run_id 里嵌的
   数字按数值而非逐字符比）。 */
export function sortCellCompare(a, b, numeric) {
  if (numeric) return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/* 可排序表格挂载（幂等：同表重复调用零副作用，返回既有 API）。
   - 点击循环 升→降→还原；aria-sort 同步（ascending/descending，仅当前
     列持值，其余清除；还原即全清）；
   - 排序用行引用 appendChild 重排——行内 onclick/监听随节点走不丢
     （禁 innerHTML 重建，P1-2 行点击面零破坏）；
   - 自然顺序基线在首次排序前快照（快照行已不在 tbody=页面重渲染过 →
     自动重取）；还原即基线回放；
   - 返回 { refresh }：tbody 被页面重渲染（筛选/重进页）后重放当前排序，
     保持列头状态与行序一致。 */
export function makeSortable(table) {
  if (!table || !table.tHead || !table.tBodies.length) return null;
  if (table.dataset.sortableBound) return table._sortable || null;
  table.dataset.sortableBound = "1";
  const body = table.tBodies[0];
  let base = []; // 自然顺序行快照
  const natural = () => {
    if (!base.length || base.length !== body.rows.length ||
        base.some((tr) => tr.parentNode !== body))
      base = Array.from(body.rows);
    return base;
  };
  const ths = Array.from(table.tHead.rows[0] ? table.tHead.rows[0].cells : []);
  for (const th of ths) {
    th.style.cursor = "pointer";
    th.title = "点击排序（升 → 降 → 还原）";
  }
  const clearAria = (keep) => ths.forEach((th) => {
    if (th !== keep) th.removeAttribute("aria-sort");
  });
  function sortBy(th, dir) {
    const ci = ths.indexOf(th);
    const rows = natural().slice(); // 基线保持自然序，排序在副本上做
    const numeric = columnIsNumeric(rows.map((tr) => tr.cells[ci] && tr.cells[ci].textContent));
    const keys = new Map(rows.map((tr) => [tr, sortCellKey(tr.cells[ci] ? tr.cells[ci].textContent : "", numeric)]));
    const sorted = rows.sort((x, y) =>
      sortCellCompare(keys.get(x), keys.get(y), numeric) * (dir === "asc" ? 1 : -1));
    for (const tr of sorted) body.appendChild(tr); // 行引用重排
    th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    clearAria(th);
    th.dataset.sortDir = dir;
  }
  function onThClick(th) {
    const dir = th.dataset.sortDir;
    if (dir === "asc") sortBy(th, "desc");
    else if (dir === "desc") { // 还原：基线快照回放 + aria 清零
      for (const tr of natural()) body.appendChild(tr);
      th.removeAttribute("aria-sort");
      clearAria(null);
      delete th.dataset.sortDir;
    } else sortBy(th, "asc");
  }
  ths.forEach((th) => th.addEventListener("click", () => onThClick(th)));
  const api = {
    refresh() { // tbody 重渲染后重放当前排序（无排序态=零操作）
      const th = ths.find((t) => t.dataset.sortDir);
      if (th) sortBy(th, th.dataset.sortDir);
    },
  };
  table._sortable = api;
  return api;
}

/* 扫描挂载：对 root 下标了 data-sortable 的 table 逐个 makeSortable。
   页面重渲染重建 <table> 元素的场景（如 queue 页 innerHTML 换血）由调用方
   在每次渲染后重调本函数（makeSortable 幂等，同元素不重复绑）。 */
export function mountSortableTables(root) {
  if (!root || !root.querySelectorAll) return;
  for (const tb of root.querySelectorAll("table[data-sortable]")) makeSortable(tb);
}
/* ═══ aurora36 W3-B 块结束 ═══ */
