// 四选一练习引擎——N2语法/词汇页面的"练习"tab专用，跟 listening-page.js
// 里的単语テスト（.quiz-*，"一个词自动衍生4种打字题"）是完全独立的两套
// 引擎：数据模型不一样（这里是教材原版固定选项+标准答案+中文解析，不是
// 从一个词现算出4种题型），不共用任何状态或函数，但沿用同一套retry-
// until-correct哲学（错的题重新排到队尾，直到这一轮全部答对）和同一套
// .quiz-app/.quiz-card/.quiz-category-bar外壳类名，视觉上是一家人。
//
// 数据来源：页面里 <script type="application/json" id="mcq-quiz-data">，
// 一个JSON数组，每条：
//   {
//     id: 数字，全站围绕这个id记录进度/错题，同一页面内必须唯一,
//     category: 分类文字（比如"第1单元"），用于分类筛选条，跟単语テスト
//       同一套"全部+按第一次出现顺序排列"逻辑,
//     stemTokens: [{text,kana?,blank?}, ...]——题干的token列表，
//       跟build_page.py的tokenize_ja()输出同一种形状，blank:true的
//       token渲染成下划线占位、不注音（答案不能提前泄露在题干里）,
//     options: [{idx: 1, tokens: [...]}, ...]——选项，idx跟教材原版编号
//       一致（1~4，不一定从1连续，取决于是不是问题2语序题这种直接把
//       候选词列出来的形式）,
//     answer: 正确选项的idx（不是数组下标）,
//     explanationZh: 中文解析（可选，没有就不显示这块）
//   }
(function () {
  var dataEl = document.getElementById("mcq-quiz-data");
  if (!dataEl) return;
  var ITEMS = JSON.parse(dataEl.textContent);
  if (!ITEMS.length) return;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // 跟 exam-page.js 的 renderTokensHtml() 同一套渲染规则（token 是
  // build_page.py 的 tokenize_ja() 现场算好的，不需要兼容编辑模式）——
  // 两个文件不共用同一个作用域，各自保留一份是这个项目一贯的做法
  // （没有模块系统，跨IIFE共享函数没有比复制粘贴更简单的办法）。
  function renderTokensHtml(tokens) {
    var parts = [];
    (tokens || []).forEach(function (tok) {
      if (tok.text === "\n") { parts.push("<br>"); return; }
      var text = esc(tok.text);
      if (tok.blank) {
        parts.push('<span class="mcq-blank">' + text + "</span>");
        return;
      }
      parts.push(tok.kana && tok.kana !== tok.text
        ? "<ruby>" + text + "<rt>" + esc(tok.kana) + "</rt></ruby>" : text);
    });
    return parts.join("");
  }

  var SLUG = location.pathname;
  var CATEGORY_KEY = "n2mcq-category:" + SLUG;
  var SCOPE_KEY = "n2mcq-scope:" + SLUG;
  var ERROR_KEY_PREFIX = "n2mcq-errors:" + SLUG;
  var PROGRESS_KEY_PREFIX = "n2mcq-progress:" + SLUG;
  var DELAY_KEY = "n2listen-quiz-delay"; // 全站共用的"答完自动跳下一题"秒数偏好

  // ---- 分类（按第一次出现顺序，跟 listening-page.js 単语テスト同一条规则）----
  var presentCategories = {};
  var categoryOrder = [];
  ITEMS.forEach(function (it) {
    var c = it.category || "全部";
    if (!presentCategories[c]) { presentCategories[c] = true; categoryOrder.push(c); }
  });
  var availableCategories = [{ key: "all", label: "全部" }]
    .concat(categoryOrder.map(function (k) { return { key: k, label: k }; }));
  var category = localStorage.getItem(CATEGORY_KEY) || "all";
  if (category !== "all" && !presentCategories[category]) category = "all";

  function categoryItems() {
    if (category === "all") return ITEMS;
    return ITEMS.filter(function (it) { return (it.category || "全部") === category; });
  }

  // ---- 错题/进度状态，按分类各自独立记（跟単语テスト同一个道理：
  // "第1单元"跟"第2单元"是两套独立的做题记录）----
  function stateKeys() {
    var suffix = ":" + category;
    return { error: ERROR_KEY_PREFIX + suffix, progress: PROGRESS_KEY_PREFIX + suffix };
  }
  var errors = {};
  var completed = {};
  function loadCategoryState() {
    try { errors = JSON.parse(localStorage.getItem(stateKeys().error) || "{}"); } catch (e) { errors = {}; }
    try { completed = JSON.parse(localStorage.getItem(stateKeys().progress) || "{}"); } catch (e) { completed = {}; }
  }
  loadCategoryState();
  function getErr(id) { return errors[id] || 0; }
  function bumpErr(id) {
    errors[id] = getErr(id) + 1;
    localStorage.setItem(stateKeys().error, JSON.stringify(errors));
  }
  function markDone(it) {
    completed[it.id] = true;
    localStorage.setItem(stateKeys().progress, JSON.stringify(completed));
  }
  function totalErrorCount() {
    return Object.keys(errors).reduce(function (sum, k) { return sum + errors[k]; }, 0);
  }

  // ---- 出题范围：全部/仅错题——同一套 localStorage key 前缀跟単语テスト
  // 不共用（各自独立），但用户心智模型是一致的（设置面板里同一个位置）。
  var scope = localStorage.getItem(SCOPE_KEY) || "all";

  function scopedAllItems() {
    return categoryItems().filter(function (it) {
      return !(scope === "wrong" && getErr(it.id) <= 0);
    });
  }

  var TOTAL_THIS_ROUND = 0;
  var queue = [];
  var qi = 0;
  var resolved = false;
  var countedWrong = false;
  var autoAdvanceTimer = null;
  var advanceDelay = parseInt(localStorage.getItem(DELAY_KEY) || "3", 10);

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  function buildQueue() {
    var all = scopedAllItems();
    var q = all.length ? all.filter(function (it) { return !completed[it.id]; }) : [];
    if (all.length && !q.length) {
      completed = {};
      localStorage.setItem(stateKeys().progress, JSON.stringify(completed));
      q = all.slice();
    }
    shuffle(q);
    q.sort(function (a, b) { return getErr(b.id) - getErr(a.id); });
    TOTAL_THIS_ROUND = all.length;
    return q;
  }
  queue = buildQueue();

  function doneCountThisRound() {
    var n = 0;
    scopedAllItems().forEach(function (it) { if (completed[it.id]) n++; });
    return n;
  }

  // ---- DOM ----
  var root = document.getElementById("mcqApp");
  if (!root) return;
  var progressEl = document.getElementById("mcqProgress");
  var cardEl = document.getElementById("mcqCard");
  var doneEl = document.getElementById("mcqDone");
  var stemEl = document.getElementById("mcqStem");
  var optionsEl = document.getElementById("mcqOptions");
  var statusEl = document.getElementById("mcqStatus");
  var explanationEl = document.getElementById("mcqExplanation");
  var resetBtn = document.getElementById("mcqResetErrors");

  function progressHtml(current) {
    return current + " / " + TOTAL_THIS_ROUND +
      '<span class="quiz-progress-err">(' + totalErrorCount() + ')</span>';
  }
  function refreshProgress() {
    progressEl.innerHTML = progressHtml(Math.min(doneCountThisRound() + 1, TOTAL_THIS_ROUND));
  }

  function render() {
    while (qi < queue.length && completed[queue[qi].id]) qi++;

    if (TOTAL_THIS_ROUND === 0) {
      cardEl.style.display = "none";
      doneEl.style.display = "block";
      doneEl.textContent = "还没有错题，切换到「全部题目」先做一遍积累错题吧";
      progressEl.innerHTML = "0 / 0";
      return;
    }
    if (qi >= queue.length) {
      cardEl.style.display = "none";
      doneEl.style.display = "block";
      doneEl.textContent = "🎉 本轮全部完成！";
      progressEl.innerHTML = progressHtml(TOTAL_THIS_ROUND);
      return;
    }
    cardEl.style.display = "";
    doneEl.style.display = "none";
    progressEl.innerHTML = progressHtml(Math.min(doneCountThisRound() + 1, TOTAL_THIS_ROUND));

    if (autoAdvanceTimer) { clearTimeout(autoAdvanceTimer); autoAdvanceTimer = null; }

    var it = queue[qi];
    resolved = false;
    countedWrong = false;
    statusEl.textContent = "";
    statusEl.className = "quiz-status";
    explanationEl.className = "mcq-explanation";
    explanationEl.innerHTML = "";

    stemEl.innerHTML = renderTokensHtml(it.stemTokens);
    optionsEl.innerHTML = it.options.map(function (opt) {
      return '<div class="mcq-option" data-idx="' + opt.idx + '">' +
        '<span class="mcq-option-num">' + opt.idx + "</span>" +
        '<span class="mcq-option-text">' + renderTokensHtml(opt.tokens) + "</span></div>";
    }).join("");
  }

  function selectOption(idx, it) {
    if (resolved) return;
    resolved = true;
    var ok = String(idx) === String(it.answer);
    if (ok) {
      markDone(it);
    } else {
      queue.push(it);
    }
    if (!ok && !countedWrong) { bumpErr(it.id); countedWrong = true; refreshProgress(); }

    Array.prototype.forEach.call(optionsEl.querySelectorAll(".mcq-option"), function (el) {
      el.classList.add("disabled");
      var oIdx = el.getAttribute("data-idx");
      if (String(oIdx) === String(it.answer)) el.classList.add("correct");
      else if (String(oIdx) === String(idx)) el.classList.add("wrong");
    });
    statusEl.textContent = ok ? "✓ 正解！" : "✗ 不正解";
    statusEl.className = "quiz-status " + (ok ? "ok" : "rev");
    if (it.explanationZh) {
      explanationEl.textContent = it.explanationZh;
      explanationEl.className = "mcq-explanation show";
    }

    autoAdvanceTimer = setTimeout(function () {
      autoAdvanceTimer = null;
      qi++;
      render();
    }, advanceDelay * 1000);
  }

  optionsEl.addEventListener("click", function (e) {
    var opt = e.target.closest(".mcq-option");
    if (!opt || resolved) return;
    selectOption(opt.getAttribute("data-idx"), queue[qi]);
  });

  resetBtn.addEventListener("click", function () {
    errors = {};
    localStorage.setItem(stateKeys().error, JSON.stringify(errors));
    completed = {};
    localStorage.setItem(stateKeys().progress, JSON.stringify(completed));
    queue = buildQueue();
    qi = 0;
    render();
  });

  if (availableCategories.length > 1) {
    var categoryBar = document.createElement("div");
    categoryBar.className = "quiz-category-bar";
    categoryBar.innerHTML = availableCategories.map(function (c) {
      return '<button type="button" class="quiz-category-btn" data-category="' + c.key + '">' +
        c.label + "</button>";
    }).join("");
    root.insertBefore(categoryBar, root.firstChild);
    var categoryBtns = Array.prototype.slice.call(categoryBar.querySelectorAll(".quiz-category-btn"));
    categoryBtns.forEach(function (b) {
      b.classList.toggle("active", b.dataset.category === category);
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        if (b.dataset.category === category) return;
        category = b.dataset.category;
        localStorage.setItem(CATEGORY_KEY, category);
        categoryBtns.forEach(function (x) { x.classList.toggle("active", x === b); });
        loadCategoryState();
        queue = buildQueue();
        qi = 0;
        render();
      });
    });
  }

  render();
})();
