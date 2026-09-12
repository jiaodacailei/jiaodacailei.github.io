// 四选一练习引擎——N2语法/词汇页面的"练习"tab专用，跟 listening-page.js
// 里的単语テスト（.quiz-*，"一个词自动衍生4种打字题"）是完全独立的两套
// 引擎：数据模型不一样（这里是教材原版固定选项+标准答案+中文解析，不是
// 从一个词现算出4种题型），不共用任何状态或函数。视觉上沿用同一套
// .quiz-app/.quiz-card/.quiz-category-bar外壳类名，是一家人，但答题流程
// 故意跟単语テスト不一样：**题目顺序固定按原书顺序，不随机、不按错误
// 次数重排，答错也不会被塞回队尾重考；提交答案后不自动跳下一题，靠
// "前へ/次へ"手动翻页，可以自由往回看**——真实反馈"题目顺序保持原书
// 即可，不要随机""用户提交后不要自动跳到下一步""同时可以返回上一题，
// 这样可以方便在原书上对比"：这个tab是配合纸质教材使用的练习册，用户
// 想要的是"跟书上题号对得上、自己控制翻页节奏"，不是"打字游戏"那种
// 追求速度的做法（単语テスト那套retry-until-correct+自动倒计时跳题
// 的设计初衷是刷生词卡片，跟这里的使用场景不一样，两边故意分道扬镳，
// 不是疏忽忘了同步）。
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
//     answer: 正确选项的idx（不是数组下标），也可以是idx数组——真实案例
//       （N2语法01"パートI問題2"词库选择题，13/20两题参考答案标的是
//       "F/H"，两个语法点在那个语境下都讲得通）：判分/揭晓正确答案时
//       统一用"idx是否在accepted数组里"判断，单个数字会先被[].concat()
//       包成单元素数组，跟数组形式走同一条判断逻辑，不用分两套代码,
//     kind: 可选，"complete"表示这题没有options/answer（教材原版这题就是
//       "无选项、自己写一句续完"的主观题，只有参考例句，没有唯一标准
//       答案），此时不读options/answer，改读referenceJa；"passage"表示
//       这题是"一段短文挖好几个空，每空四选一，全部答完一起交卷"（真实
//       反馈"不能分拆成好几道题，应该按照原资料，几道题同时展示出来，
//       一起答"），此时不读options/answer，改读blanks；不传这个字段
//       就是默认的单空四选一题,
//     referenceJa: kind:"complete"专用，书上给的参考例句（点"查看参考
//       答案"后显示，不参与自动判分——由用户自己点"我答对了/答错了"
//       自评，跟四选一共用同一套markDone()/bumpErr()错题记录）,
//     blanks: kind:"passage"专用，[{label, options:[{idx,tokens}], answer}, ...]
//       ——stemTokens里每个blank:true的token依次对应blanks数组里的一项
//       （靠出现顺序对应，不是靠字段关联），token的text就是label（比如
//       "18"，原书题号，不是"____"占位符），前端渲染成一个个小圆点数字，
//       底下分别列出各自的options，全部选完点"確認"一次性判分，只要有
//       一个空错了，整段（不是错的那一个空）重新排到队尾重考，跟原书
//       "这几道题共享同一篇短文"的出题精神一致,
//     explanationZh: 中文解析（可选，没有就不显示这块，三种kind都能用；
//       kind:"passage"时这是构建脚本自动拼接好的"每个空各自的解析"）
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
  // 有顶部"单元选择"下拉框的页面（page-renderer.js 里 DATA.titleDictate
  // 判断出来的 has-title-dictate）——"生词"/"语法点"tab 和这个练习tab共用
  // 同一份"当前选中单元"状态，key 名字必须跟 page-renderer.js 里那份完全
  // 一致（"n2-unit:"+pathname），不能各用各的（不然两边各记各的，选了
  // 单元只有一边跟着换，另一边还是老样子）。没有下拉框的场景（假设以后
  // mcq-quiz.js 被别的、没有 titleDictate 的页面复用）退回到旧的独立
  // key，行为等价于以前。
  var HAS_UNIT_SELECT = document.body.classList.contains("has-title-dictate");
  var CATEGORY_KEY = HAS_UNIT_SELECT ? ("n2-unit:" + SLUG) : ("n2mcq-category:" + SLUG);
  var SCOPE_KEY = "n2mcq-scope:" + SLUG;
  var ERROR_KEY_PREFIX = "n2mcq-errors:" + SLUG;
  var PROGRESS_KEY_PREFIX = "n2mcq-progress:" + SLUG;

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

  // 固定按原书顺序（items本来就是build_mcq_items()按MCQ_UNITS原始顺序
  // 展开出来的）——不shuffle、不按错误次数重排、不过滤掉已完成的题，
  // "仅错题"范围下筛出来的子集也保持它们在原书里的相对顺序，不重新排序。
  function buildQueue() {
    var all = scopedAllItems();
    TOTAL_THIS_ROUND = all.length;
    return all;
  }
  queue = buildQueue();

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
  var prevBtn = document.getElementById("mcqPrevBtn");
  var nextBtn = document.getElementById("mcqNextBtn");
  // kind:"complete"（自由续写）专用的几个元素——没有这几个id的旧版
  // page-renderer.js（还没升级）渲染出来的页面上不存在，用变量本身是否
  // 为null判断要不要走这条分支，不强制要求存在。
  var completeRowEl = document.getElementById("mcqCompleteRow");
  var completeInputEl = document.getElementById("mcqCompleteInput");
  var completeShowBtn = document.getElementById("mcqCompleteShowBtn");
  var completeRevealEl = document.getElementById("mcqCompleteReveal");
  var completeRefEl = document.getElementById("mcqCompleteRef");
  var completeCorrectBtn = document.getElementById("mcqCompleteCorrectBtn");
  var completeWrongBtn = document.getElementById("mcqCompleteWrongBtn");
  // kind:"passage"（一段短文挖好几个空，一起作答）专用——同样按id是否
  // 为null判断旧版page-renderer.js页面要不要走这条分支。
  var passageBlanksEl = document.getElementById("mcqPassageBlanks");
  var passageActionsEl = document.getElementById("mcqPassageActions");
  var passageCheckBtn = document.getElementById("mcqPassageCheckBtn");
  var passageSelections = {}; // blankIdx(字符串) -> 选中的idx，每次render()重置

  // 进度显示"当前位置 / 总题数(累计错误次数)"——current直接是qi+1（你正在
  // 看第几题），不再是"已经答对几题"，因为不按错误次数重排/答错不再重考，
  // "已完成数"这个概念本身不适用了，翻到哪一题就是哪一题。
  function progressHtml(current) {
    return current + " / " + TOTAL_THIS_ROUND +
      '<span class="quiz-progress-err">(' + totalErrorCount() + ')</span>';
  }
  function refreshProgress() {
    progressEl.innerHTML = progressHtml(qi + 1);
  }

  function render() {
    if (TOTAL_THIS_ROUND === 0) {
      cardEl.style.display = "none";
      doneEl.style.display = "block";
      doneEl.textContent = "还没有错题，切换到「全部题目」先做一遍积累错题吧";
      progressEl.innerHTML = "0 / 0";
      return;
    }
    // 分类/单元切换、清除记录之后queue可能变短，qi要夹回合法范围，不然会
    // 指向一个已经不存在的下标。
    qi = Math.max(0, Math.min(qi, queue.length - 1));
    cardEl.style.display = "";
    doneEl.style.display = "none";
    progressEl.innerHTML = progressHtml(qi + 1);
    if (prevBtn) prevBtn.disabled = qi <= 0;
    if (nextBtn) nextBtn.disabled = qi >= queue.length - 1;

    var it = queue[qi];
    resolved = false;
    countedWrong = false;
    statusEl.textContent = "";
    statusEl.className = "quiz-status";
    explanationEl.className = "mcq-explanation";
    explanationEl.innerHTML = "";

    stemEl.innerHTML = renderTokensHtml(it.stemTokens);

    optionsEl.style.display = "none";
    if (completeRowEl) completeRowEl.style.display = "none";
    if (passageBlanksEl) { passageBlanksEl.style.display = "none"; passageActionsEl.style.display = "none"; }

    if (it.kind === "complete") {
      if (completeRowEl) {
        completeRowEl.style.display = "";
        completeRevealEl.style.display = "none";
        completeInputEl.value = "";
        completeInputEl.disabled = false;
        completeShowBtn.disabled = false;
      }
    } else if (it.kind === "passage") {
      if (passageBlanksEl) {
        passageSelections = {};
        passageBlanksEl.style.display = "";
        passageActionsEl.style.display = "";
        passageCheckBtn.disabled = true;
        passageBlanksEl.innerHTML = it.blanks.map(function (b, bi) {
          return '<div class="mcq-passage-blank-group" data-blank-idx="' + bi + '">' +
            '<div class="mcq-passage-blank-label">' + esc(b.label) + "</div>" +
            '<div class="mcq-options">' + b.options.map(function (opt) {
              return '<div class="mcq-option" data-blank-idx="' + bi + '" data-idx="' + opt.idx + '">' +
                '<span class="mcq-option-num">' + opt.idx + "</span>" +
                '<span class="mcq-option-text">' + renderTokensHtml(opt.tokens) + "</span></div>";
            }).join("") + "</div></div>";
        }).join("");
      }
    } else {
      optionsEl.style.display = "";
      // 词库选择题（比如N2语法01"パートI問題2"，从A~J共10项里选）原书是
      // 一次性印出整份词库当参考表格（4列网格），不是"1/2/3/4"那种竖排
      // 四选一列表——真实反馈"part1问题2也需要和原资料一样"。这里不用
      // 额外的内容字段判断，选项数超过4个（超出常规单句四选一的范围）
      // 就自动按网格布局渲染，常规4选1题不受影响。
      optionsEl.classList.toggle("mcq-options-grid", it.options.length > 4);
      optionsEl.innerHTML = it.options.map(function (opt) {
        return '<div class="mcq-option" data-idx="' + opt.idx + '">' +
          '<span class="mcq-option-num">' + opt.idx + "</span>" +
          '<span class="mcq-option-text">' + renderTokensHtml(opt.tokens) + "</span></div>";
      }).join("");
    }
  }

  // 判对/判错之后共用的收尾逻辑（记错题/进度、显示解析）——四选一
  // （selectOption）和自由续写自评（selectSelfReport）两条路径判"对/错"
  // 的方式完全不同，但收尾这部分是同一套，不重复写。答错不再塞回队尾
  // 重考（题目顺序固定跟原书一致），也不自动跳下一题——留在当前这题，
  // 让用户看完解析后自己点"次へ"翻页，也可以直接点"前へ/次へ"跳过看
  // 别的题，不强制答完当前题才能走。
  function finishQuestion(it, ok, statusText) {
    if (ok) markDone(it);
    if (!ok && !countedWrong) { bumpErr(it.id); countedWrong = true; refreshProgress(); }
    statusEl.textContent = statusText;
    statusEl.className = "quiz-status " + (ok ? "ok" : "rev");
    if (it.explanationZh) {
      explanationEl.textContent = it.explanationZh;
      explanationEl.className = "mcq-explanation show";
    }
  }

  function selectOption(idx, it) {
    if (resolved) return;
    resolved = true;
    // it.answer 通常是单个idx，[].concat()统一包成数组——13/20这类"两个
    // 选项都算对"的题answer本来就是数组，两种形状走同一条判断逻辑。
    var accepted = [].concat(it.answer);
    var ok = accepted.some(function (a) { return String(a) === String(idx); });

    Array.prototype.forEach.call(optionsEl.querySelectorAll(".mcq-option"), function (el) {
      el.classList.add("disabled");
      var oIdx = el.getAttribute("data-idx");
      if (accepted.some(function (a) { return String(a) === String(oIdx); })) el.classList.add("correct");
      else if (String(oIdx) === String(idx)) el.classList.add("wrong");
    });
    finishQuestion(it, ok, ok ? "✓ 正解！" : "✗ 不正解");
  }

  // kind:"complete"（自由续写）没有唯一标准答案，判分交给用户自己看完
  // 参考例句后点"我答对了/我答错了"——跟selectOption()共用finishQuestion()
  // 收尾，只是"ok"的来源从"点了哪个选项"变成"用户自评"。
  function selectSelfReport(ok, it) {
    if (resolved) return;
    resolved = true;
    completeInputEl.disabled = true;
    completeShowBtn.disabled = true;
    finishQuestion(it, ok, ok ? "✓ 正解！" : "✗ 不正解");
  }

  // kind:"passage"——点某个空的某个选项只是"选中"（可以改选），不立刻判分；
  // 全部空都选完了才能点"確認"一次性交卷。判分时逐个空对比，任何一个空
  // 错了整道题（不是那一个空）就重新塞回队尾重考，跟原书"这几道题共享
  // 同一篇短文"的出题精神一致——不按单个空拆分错题记录。
  function selectPassageOption(bi, idx) {
    if (resolved) return;
    passageSelections[bi] = idx;
    Array.prototype.forEach.call(
      passageBlanksEl.querySelectorAll('.mcq-passage-blank-group[data-blank-idx="' + bi + '"] .mcq-option'),
      function (el) { el.classList.toggle("selected", el.getAttribute("data-idx") === idx); }
    );
    passageCheckBtn.disabled = Object.keys(passageSelections).length < queue[qi].blanks.length;
  }

  function submitPassage(it) {
    if (resolved) return;
    resolved = true;
    var allOk = true;
    it.blanks.forEach(function (b, bi) {
      var chosen = passageSelections[bi];
      var ok = String(chosen) === String(b.answer);
      if (!ok) allOk = false;
      Array.prototype.forEach.call(
        passageBlanksEl.querySelectorAll('.mcq-passage-blank-group[data-blank-idx="' + bi + '"] .mcq-option'),
        function (el) {
          el.classList.add("disabled");
          var oIdx = el.getAttribute("data-idx");
          if (String(oIdx) === String(b.answer)) el.classList.add("correct");
          else if (String(oIdx) === String(chosen)) el.classList.add("wrong");
        }
      );
    });
    passageCheckBtn.disabled = true;
    finishQuestion(it, allOk, allOk ? "✓ 全部正解！" : "✗ 有不正确的地方");
  }

  optionsEl.addEventListener("click", function (e) {
    var opt = e.target.closest(".mcq-option");
    if (!opt || resolved) return;
    selectOption(opt.getAttribute("data-idx"), queue[qi]);
  });

  if (passageBlanksEl) {
    passageBlanksEl.addEventListener("click", function (e) {
      var opt = e.target.closest(".mcq-option");
      if (!opt || resolved) return;
      selectPassageOption(opt.getAttribute("data-blank-idx"), opt.getAttribute("data-idx"));
    });
    passageCheckBtn.addEventListener("click", function () { submitPassage(queue[qi]); });
  }

  if (completeShowBtn) {
    completeShowBtn.addEventListener("click", function () {
      var it = queue[qi];
      if (resolved) return;
      completeRevealEl.style.display = "";
      completeRefEl.textContent = it.referenceJa || "";
      completeInputEl.disabled = true;
      completeShowBtn.disabled = true;
    });
    completeCorrectBtn.addEventListener("click", function () { selectSelfReport(true, queue[qi]); });
    completeWrongBtn.addEventListener("click", function () { selectSelfReport(false, queue[qi]); });
  }

  resetBtn.addEventListener("click", function () {
    errors = {};
    localStorage.setItem(stateKeys().error, JSON.stringify(errors));
    completed = {};
    localStorage.setItem(stateKeys().progress, JSON.stringify(completed));
    queue = buildQueue();
    qi = 0;
    render();
  });

  // 手动翻页——不强制"答完当前题才能走"，跟原书对照着看的时候，用户
  // 可能只是想先翻页确认一下题号对不对，不一定每题都要在这里作答。
  if (prevBtn) prevBtn.addEventListener("click", function () { if (qi > 0) { qi--; render(); } });
  if (nextBtn) nextBtn.addEventListener("click", function () { if (qi < queue.length - 1) { qi++; render(); } });

  // 有顶部单元下拉框的页面不再重复渲染这一份分类条——两个UI选同一件事，
  // 留着反而让人搞不清"到底该点哪个"。下拉框换单元时靠下面的
  // window.addEventListener("n2unitchange", ...) 同步刷新这里的题目集合。
  if (availableCategories.length > 1 && !HAS_UNIT_SELECT) {
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

  // 顶部单元下拉框（page-renderer.js）换了单元——这个练习tab自己没有分类
  // 按钮时（HAS_UNIT_SELECT）靠这个事件同步刷新，题目集合、进度显示都要
  // 跟着换。事件的 detail 就是选中的单元原文（"all"或者"第N单元"），跟
  // category 期望的值格式完全一样，不用转换。
  if (HAS_UNIT_SELECT) {
    window.addEventListener("n2unitchange", function (e) {
      category = e.detail;
      loadCategoryState();
      queue = buildQueue();
      qi = 0;
      render();
    });
  }

  render();
})();
