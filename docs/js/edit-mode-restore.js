// 编辑模式（docs/js/edit-mode.js）暂存在 localStorage 里的修改，页面每次
// 加载时先合并进 window.LESSON_DATA 再渲染——保证回来继续编辑时能看到上次
// 的修改，也保证导出前刷新页面不会丢失已经应用的修改。
//
// 必须在 page-renderer.js 渲染之前跑完，所以这个文件**不能带 defer**，得
// 紧跟在 `<script src="data.js">` 后面（比 page-renderer.js 先执行）——不然
// 渲染器会拿着还没合并编辑的旧数据渲染出页面，暂存的修改要等下一次刷新才
// 会显示出来。
//
// 没有 window.LESSON_DATA（非 data-driven 页面）时整个不做事。
(function () {
  var DATA = window.LESSON_DATA;
  if (!DATA) return;

  var KEY = "n2listen-pending-edits:" + location.pathname;
  var pending;
  try {
    pending = JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch (e) {
    pending = {};
  }
  var ids = Object.keys(pending);
  if (!ids.length) return;

  var byId = {};
  (DATA.tabs || []).forEach(function (tab) {
    tab.questions.forEach(function (q) {
      q.sentences.forEach(function (s) {
        byId[s.id] = s;
      });
    });
  });

  ids.forEach(function (id) {
    var s = byId[id];
    // 这句在当前数据里已经不存在了（比如页面用新的 enriched.json 重新生成
    // 过、id 变了）——跳过，不强行套用到不相关的句子上。这份暂存记录留着，
    // 不在这里清掉：万一是加载时机问题或者临时性的数据缺失，下次还有机会
    // 重新匹配上；真的要清理无主记录，用编辑模式面板里的"清除暂存"按钮。
    if (!s) return;
    var edit = pending[id];
    ["speaker", "speakerKana", "tokens", "zh", "notes", "blanks"].forEach(function (k) {
      s[k] = edit[k];
    });
  });
})();
