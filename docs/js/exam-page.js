// N2真题模考页面——独立于 listening-page.js 那套（那套是给"听录音跟读"场景
// 设计的），这里是"限时作答→交卷判分→逐题复习（含音频+解析）"这条新流程。
// 依赖页面上已经有 window.EXAM_DATA（build_exam_data.py 生成的 data.js）。
(function () {
  var DATA = window.EXAM_DATA;
  if (!DATA) return;

  var SLUG = location.pathname.replace(/\/+$/, "").split("/").pop() || "n2-exam";
  var STORAGE_KEY = "exam-answers-" + SLUG;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // 跟 tools/listening/build_page.py 的 ruby_html_from_tokens() 保持同一套渲染
  // 规则——这里的 token 都是 Python 端 tokenize_ja() 现场算好的，不需要像
  // page-renderer.js 那样兼容"浏览器里手填的合并kana覆盖"这个编辑模式场景
  // （这个页面没有编辑模式），所以不用移植 splitKanaSegments()，直接按
  // token 是否带 kana 简单包一层 <ruby> 即可。
  function renderTokensHtml(tokens) {
    var parts = [];
    (tokens || []).forEach(function (tok) {
      if (tok.text === "\n") { parts.push("<br>"); return; }
      var text = esc(tok.text);
      if (tok.blank) {
        // 交卷前的挖空/画线原文——即使这段文字本身含汉字（比如問題1画线的
        // 目标词"倒さない"），也绝对不能注音，注了音等于把读音答案写在题面
        // 上，这是这个token专门不走<ruby>分支、只加下划线样式的原因。
        parts.push('<span class="exam-blank">' + text + "</span>");
        return;
      }
      var inner = tok.kana && tok.kana !== tok.text
        ? "<ruby>" + text + "<rt>" + esc(tok.kana) + "</rt></ruby>"
        : text;
      parts.push(inner);
    });
    return parts.join("");
  }

  // ---- 播放器：单个共享 <audio>，同一时间只放一个 ----
  // 跟 listening-page.js 的 .seg-card.loading/.playing 同一套反馈规则：点击
  // 那一刻同步加 .loading（不等任何异步事件，保证点击必有反应），真正开始
  // 出声（playing事件）摘掉loading、加playing；暂停/播完/出错都摘掉两个
  // class 回到闲置态——不能只加 .playing 不管 loading，preload="none" 的
  // 音频第一次点到真出声之间有读取延迟，没有loading反馈会让人以为点击没
  // 生效（这个页面550条短音频都是这种情况，反馈更要明显）。
  var player = new Audio();
  var activeEl = null;
  var stallTimer = null;
  function clearStallTimer() {
    if (stallTimer) { clearTimeout(stallTimer); stallTimer = null; }
  }
  function clearActiveClasses() {
    if (activeEl) activeEl.classList.remove("playing", "loading");
  }
  function stopPlayback() {
    clearStallTimer();
    player.pause();
    clearActiveClasses();
    activeEl = null;
  }
  function playAudio(src, el) {
    if (activeEl === el) { stopPlayback(); return; }
    stopPlayback();
    player.src = src;
    activeEl = el;
    if (el) el.classList.add("loading");
    player.play().catch(function () {
      if (el) el.classList.remove("loading");
    });
    // 兜底：正常情况 loading 会在几百毫秒内被 playing/error 事件摘掉，网络卡顿
    // 也有 waiting 事件重新加回来——但如果音频资源本身有问题（编码坏掉、服务器
    // 挂了却没返回明确 error）导致 play() 的 promise 一直不 resolve/reject、
    // 也不触发 playing/error，loading 转圈会没有尽头地转下去，用户会以为点击
    // 还在等，实际上已经没救了。8秒还没真正出声就判定为播放失败，交回闲置态。
    clearStallTimer();
    stallTimer = setTimeout(function () {
      if (activeEl === el) stopPlayback();
    }, 8000);
  }
  // 不监听 pause 事件调用 stopPlayback——pause() 本身就是 stopPlayback()/
  // playAudio() 内部会调用的动作，监听 pause 再调回 stopPlayback 会在"停旧的
  // 播新的"这个动作中间形成事件时序上的重入（旧的 pause 事件可能在 activeEl
  // 已经切换到新目标之后才触发，误清掉新目标刚加上的状态）。ended/error 是
  // 真正需要响应的"播放自然结束/失败"信号，不存在这个重入问题。
  player.addEventListener("waiting", function () {
    if (activeEl) { activeEl.classList.add("loading"); activeEl.classList.remove("playing"); }
  });
  player.addEventListener("playing", function () {
    clearStallTimer();
    if (activeEl) { activeEl.classList.remove("loading"); activeEl.classList.add("playing"); }
  });
  player.addEventListener("ended", stopPlayback);
  player.addEventListener("error", stopPlayback);

  // ---- 作答状态：qid -> 选中的选项序号，本地持久化，刷新不丢 ----
  var answers = {};
  try {
    var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    if (saved && typeof saved === "object") answers = saved;
  } catch (e) { /* ignore */ }
  function saveAnswers() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(answers)); } catch (e) { /* ignore */ }
  }

  var submitted = false;
  // 单独交某一個大题——key是section的data-mondai-idx，跟"交整份卷子"的
  // submitted是两套独立状态，互不覆盖。
  var mondaiSubmitted = {};

  // ---- 渲染 ----
  var root = document.getElementById("examRoot");

  function passageSentenceRow(s) {
    var playBtn = s.audio
      ? '<button class="exam-inline-play" data-audio="' + esc(s.audio) + '" title="読み上げ">🔊</button>'
      : "";
    return '<div class="exam-passage-sentence">' + playBtn +
      '<span class="exam-passage-text">' + renderTokensHtml(s.tokens) + "</span></div>";
  }

  // 単一版本の文章（問題10〜14——原文本来就没有挖空，交卷前后都是同一份，
  // 不存在剧透问题，音频从一开始就能听）。
  function passageHtml(sentences) {
    if (!sentences || !sentences.length) return "";
    return '<div class="exam-passage">' + sentences.map(passageSentenceRow).join("") + "</div>";
  }

  function stemHtml(q) {
    if (q.stemWord) {
      var audioAttr = q.stemWord.audio ? ' data-audio="' + esc(q.stemWord.audio) + '"' : "";
      var playBtn = q.stemWord.audio ? '<button class="exam-play-btn"' + audioAttr + '>▶</button>' : "";
      return '<div class="exam-stem-row">' + playBtn +
        '<span class="exam-stem-word">' + renderTokensHtml(q.stemWord.tokens) + "</span></div>";
    }
    if (q.stemInstruction) {
      return '<div class="exam-stem-row"><span>' + esc(q.stemInstruction) + "</span></div>";
    }
    if (q.stemBlank) {
      // 题干（画线/挖空原文）交卷前后都保持出题时的样子，不切换成填好
      // 答案的完整句——真实反馈"显示答案时，题干不应该变化，保持出题时
      // 的样子即可"。正确答案靠交卷后选项本身变绿（.correct-answer）+
      // 下面的中文解析呈现，不需要额外把题干换掉；选项本身已经带
      // furigana，读音信息没有因为题干不变而丢失。q.stem（完整正确句+
      // 音频）这份数据仍然保留在DATA里，只是不再渲染。
      return '<div class="exam-stem-row"><span>' + renderTokensHtml(q.stemBlank.tokens) + "</span></div>";
    }
    return "";
  }

  function optionHtml(qid, opt) {
    var audio = null;
    var text;
    if (opt.sentences) {
      // 問題6：選項是完整句子，可能不止一句，播放列表按顺序放，展示用第一句audio
      audio = opt.sentences[0] ? opt.sentences[0].audio : null;
      text = opt.sentences.map(function (s) { return renderTokensHtml(s.tokens); }).join(" ");
    } else {
      audio = opt.audio;
      text = renderTokensHtml(opt.tokens);
    }
    var playBtn = audio
      ? '<button class="exam-option-play" data-audio="' + esc(audio) + '" title="読み上げ">🔊</button>'
      : "";
    return '<div class="exam-option" data-qid="' + qid + '" data-opt="' + opt.idx + '">' +
      '<span class="exam-option-num">' + opt.idx + "</span>" +
      '<span class="exam-option-text">' + text + "</span>" + playBtn + "</div>";
  }

  function questionHtml(q) {
    var optsHtml = q.options.map(function (o) { return optionHtml(q.id, o); }).join("");
    return '<div class="exam-question" id="q-' + q.id + '" data-qid="' + q.id + '" data-answer="' + q.answer + '">' +
      '<div><span class="exam-question-num">' + q.id + "番</span></div>" +
      stemHtml(q) +
      '<div class="exam-options">' + optsHtml + "</div>" +
      '<div class="exam-explanation">' + esc(q.explanationZh) + "</div>" +
      "</div>";
  }

  function blockHtml(block) {
    var qsHtml = block.questions.map(questionHtml).join("");
    // 問題9（4题共享一篇段落挖空文章）跟其它題型統一了同一条規則：
    // 交卷前后都只显示原始段落（48/49/50/51占位符原样保留），不切换
    // 成填好4个空的完整段落——block.passageSentencesBlank本来就没有
    // audio字段（没配过音，也不需要，交卷前后都用不上）。填好版数据
    // （block.passageSentences，带音频）还留在DATA里，只是不再渲染。
    var passage = block.is_mondai9
      ? passageHtml(block.passageSentencesBlank)
      : passageHtml(block.passageSentences);
    return '<div class="exam-block">' + passage + qsHtml + "</div>";
  }

  // 単独交这一個大题——跟底部整份卷子的"交卷"并存、互不影响：这个按钮
  // 只批改/展开当前 data-mondai-idx 对应的这几道题，其它問題tab不受影响；
  // 整份卷子的"交卷"逻辑（submitExam()）完全没改，还是一次性批改全部
  // 72题。真实反馈：用户想要"每个問題都支持交卷功能，仅对当前问题"。
  function mondaiSubmitBarHtml(sectionIdx) {
    return '<div class="exam-mondai-submit-bar">' +
      '<button class="exam-mondai-submit-btn" data-mondai-idx="' + sectionIdx + '">提交本大题</button>' +
      '<span class="exam-mondai-submit-score"></span></div>';
  }

  function mondaiSectionHtml(m, idx) {
    var sectionIdx = idx + 1;
    var blocksHtml = m.blocks.map(blockHtml).join("");
    return '<section class="exam-mondai-section" data-mondai-idx="' + sectionIdx + '"' +
      (idx === 0 ? "" : ' style="display:none"') + ">" +
      '<div class="exam-mondai-instruction">' + esc(m.instruction) + "</div>" +
      blocksHtml + mondaiSubmitBarHtml(sectionIdx) + "</section>";
  }

  // ---- 「生词」tab：仿照课文/教材页的生词tab——从問題1〜9（有明确目标词+
  //      官方解析的类型，読解問題10〜14不做，理由跟之前审视过一次的
  //      「重点词汇语法」一样：没有清晰的目标词标注，抽取要靠主观判断）
  //      抽出的51个目标词/语法点，按同样的.seg-card样式展示——单词+读音+
  //      中文释义+例句（挖空目标词加粗），例句复用 exam-page.js 已有的
  //      audio（options[answer-1].audio 或 stemWord.audio，都是已经存在
  //      的真实录音，没有新增音频）。
  //
  //      卡片HTML直接复用 window.PageRenderer.renderCard()（page-renderer.js
  //      新增的公开工具方法）——这样视觉上跟 l10~l18 那些教材课的生词tab
  //      完全一致，不是另起一套自定义样式。但**不**加载完整的
  //      listening-page.js（那个文件大量代码在页面顶层直接
  //      document.getElementById 一堆本页面根本没有的元素——miniPlayer/
  //      settingsPanel/quizApp等——碰到第一个null.addEventListener就会
  //      整个脚本崩掉，后面所有代码都不会跑，风险太大，不值得为了省下面
  //      这几十行代码去冒这个险）。默写/填空练习模式因此不支持，只做
  //      "跟读"这一种模式对应的效果：点卡片播放这个词的发音，例句常驻
  //      展示（不像教材页那样默写模式隐藏——这个tab本来就没有默写/填空
  //      模式）。
  var VOCAB_SECTION_IDX = DATA.mondaiList.length + 1;
  // 「生词测试」tab——直接复用 window.PageRenderer.renderQuizSection()
  // （page-renderer.js跟build_page.py的quiz_section_html()一一对应的
  // 那个函数，教材课単語テスト tab用的就是它），传DATA.vocabQuiz（跟
  // build_vocab_quiz_data.py生成的教材课quiz数据同一套字段：id/text/
  // kana/zh/sentence/sentence_zh/blank/category，见tools/listening/
  // build_exam_vocab.py）进去，"填空题/听音频写假名/中文写假名/日文写
  // 中文"四种题型的出题/判分逻辑一行代码都不用改，listening-page.js的
  // 単語テスト引擎本来就是靠<script id="vocab-quiz-data">这个约定接管
  // 渲染的，不关心页面是教材课还是这个exam页。
  var QUIZ_SECTION_IDX = VOCAB_SECTION_IDX + 1;

  // id="q-{VOCAB_SECTION_IDX}-{groupIdx}"/class="question-block"——
  // 跟 page-renderer.js 的 renderQuestionBlock() 同一套约定，
  // listening-page.js 的 highlightCurrentQuestion()/setCurrent() 找
  // "当前小题"靠的就是这个id格式，不遵守这个格式那两个函数直接找不到
  // 匹配项，静默不生效（不会报错，只是浮动目录高亮不准，不影响
  // 默写/填空/单词测试这些核心功能）。
  function vocabGroupsHtml() {
    var items = DATA.vocabItems || [];
    var groups = [];
    var groupIdx = 0;
    var lastMondai = null;
    var cardsHtml = "";
    items.forEach(function (it) {
      if (it.mondai !== lastMondai) {
        if (cardsHtml) groups.push(cardsHtml);
        groupIdx++;
        cardsHtml = '<div class="question-block" id="q-' + VOCAB_SECTION_IDX + "-" + groupIdx +
          '" data-scope="question"><h3>' + esc(it.mondaiLabel) + "</h3>";
        lastMondai = it.mondai;
      }
      cardsHtml += window.PageRenderer.renderCard(it, null);
    });
    if (cardsHtml) groups.push(cardsHtml + "</div>");
    return groups.join("");
  }

  // class="mondai-section" data-scope="mondai" id="m-{VOCAB_SECTION_IDX}"——
  // 跟 page-renderer.js 的 renderMondaiSection() 同一套标记，专门给
  // listening-page.js 的模式切换/默写/填空/単語テスト机制识别用（那边找
  // section 走的是 .mondai-section[data-scope="mondai"] + id="m-N" 解析
  // 出来的编号，不是这里的 data-mondai-idx——两套系统刻意保留各自的
  // 属性名，见 listening-page.js 里"Tab 切换"那段注释）。可见性还是只由
  // exam-page.js 自己的 style.display 控制（tab-btn 点击时对全部
  // .exam-mondai-section 一视同仁地设置），.mondai-section/.tab-active
  // 这个class只是listening-page.js内部用来判断"现在归哪个mondai管"，
  // 不会跟display互相打架。
  function vocabSectionHtml() {
    if (!DATA.vocabItems || !DATA.vocabItems.length) return "";
    // <h2>——page-renderer.js的renderMondaiSection()标准结构自带这个标签，
    // listening-page.js有一段"点h2整段连播这个mondai"的功能直接querySelector
    // "h2"、不判空就addEventListener，没有h2会在脚本顶层抛未捕获异常（同一个
    // <script>里排在后面的默写/填空/单词测试代码全部执行不到，这个坑跟
    // 前面mini-player那次是同一类问题）。
    return '<section class="exam-mondai-section mondai-section" data-scope="mondai" id="m-' + VOCAB_SECTION_IDX +
      '" data-mondai-idx="' + VOCAB_SECTION_IDX + '" style="display:none">' +
      "<h2>生词</h2>" +
      '<div class="exam-mondai-instruction">従問題1〜9挑出的目标词/语法点，点卡片播放发音，例句里挖空目标词已加粗，右下角设置里可以切换跟读/默写/填空模式。不计入作答/判分。</div>' +
      vocabGroupsHtml() + "</section>";
  }

  function tabBarHtml() {
    // 生词/生词测试放最前面（真实反馈"n2-exam的生词和生词测试放到最前
    // 面"）——只是按钮的视觉顺序变了，默认打开页面显示哪个大题由
    // mondaiSectionHtml() 里单独控制（第一个問題永远不带 style="display:
    // none"），不受这里按钮先后顺序影响，所以不会因为按钮挪到前面就变成
    // 默认打开生词页。
    var btns = [];
    if (DATA.vocabItems && DATA.vocabItems.length) {
      btns.push('<button class="tab-btn" data-mondai-idx="' + VOCAB_SECTION_IDX + '">生词</button>');
    }
    if (DATA.vocabQuiz && DATA.vocabQuiz.length) {
      btns.push('<button class="tab-btn" data-mondai-idx="' + QUIZ_SECTION_IDX + '">生词测试</button>');
    }
    btns = btns.concat(DATA.mondaiList.map(function (m, i) {
      return '<button class="tab-btn' + (i === 0 ? " active" : "") + '" data-mondai-idx="' + (i + 1) + '">' +
        esc(m.label) + "</button>";
    }));
    return btns.join("");
  }

  function render() {
    document.getElementById("examTitle").textContent = DATA.title;
    document.getElementById("examTabBar").innerHTML = tabBarHtml();
    var quizHtml = (DATA.vocabQuiz && DATA.vocabQuiz.length)
      ? window.PageRenderer.renderQuizSection(QUIZ_SECTION_IDX, DATA.vocabQuiz, false)
      : "";
    // section 的 DOM 顺序跟着 tab 顺序一起挪到最前面，保持"tab 顺序"跟
    // "文档阅读顺序"一致——各 section 的默认显示/隐藏由 mondaiSectionHtml()
    // /vocabSectionHtml() 各自内联的 style 控制，不依赖拼接顺序，这里挪动
    // 纯粹是为了阅读顺序整洁，不影响默认显示哪个 tab。
    root.innerHTML = vocabSectionHtml() + quizHtml + DATA.mondaiList.map(mondaiSectionHtml).join("");
    applyStoredAnswers();
    updateProgress();
  }

  function applyStoredAnswers() {
    Object.keys(answers).forEach(function (qid) {
      var sel = answers[qid];
      var el = root.querySelector('.exam-option[data-qid="' + qid + '"][data-opt="' + sel + '"]');
      if (el) el.classList.add("selected");
    });
  }

  function totalQuestions() {
    var n = 0;
    DATA.mondaiList.forEach(function (m) { m.blocks.forEach(function (b) { n += b.questions.length; }); });
    return n;
  }

  function updateProgress() {
    var total = totalQuestions();
    var done = Object.keys(answers).length;
    document.getElementById("examProgressText").textContent = done + " / " + total + " 已作答";
    document.getElementById("examSubmitBtn").disabled = submitted;
  }

  // ---- 事件委托 ----
  root.addEventListener("click", function (e) {
    var playBtn = e.target.closest(".exam-play-btn, .exam-option-play, .exam-inline-play");
    if (playBtn) {
      e.stopPropagation();
      var src = playBtn.getAttribute("data-audio");
      if (src) playAudio(src, playBtn);
      return;
    }
    // 「生词」tab的.seg-card点击播放**不**在这里处理——这段注释曾经写的
    // "没加载完整的listening-page.js"是第五轮（刚加生词tab、还没接跟读/
    // 默写/填空模式）时的状态，第六轮已经把listening-page.js完整加载进
    // 这个页面（见index.html），它自己就有一段全局的
    // `.seg-card`点击监听（在`.question-block`范围内联播），会跟这里
    // 重复绑定的处理器同时触发——真实反馈"选中某个单词播放时，有时会
    // 有回声（好像两次播放一前一后）"：两边各自维护一份完全独立的
    // audio（这里是`new Audio()`的`player`，listening-page.js放的是卡片
    // 自带的`<audio>`标签本身），同一次点击触发两条播放链，听起来就是
    // 一前一后的回声。这里不再重复处理，交给listening-page.js唯一负责。
    if (submitted) return;
    var mSubmitBtn = e.target.closest(".exam-mondai-submit-btn");
    if (mSubmitBtn) {
      submitMondai(mSubmitBtn.getAttribute("data-mondai-idx"));
      return;
    }
    var opt = e.target.closest(".exam-option");
    if (opt) {
      // 这道题所在的大题已经单独交过——答案/对错已经定了，不能再改选项
      // （跟整份卷子交卷后的規則一致，只是判断范围缩小到这一个大题）。
      var ownSection = opt.closest(".exam-mondai-section");
      if (ownSection && ownSection.classList.contains("mondai-submitted")) return;
      var qid = opt.getAttribute("data-qid");
      var idx = opt.getAttribute("data-opt");
      var qEl = document.getElementById("q-" + qid);
      qEl.querySelectorAll(".exam-option").forEach(function (o) { o.classList.remove("selected"); });
      opt.classList.add("selected");
      answers[qid] = idx;
      saveAnswers();
      updateProgress();
    }
  });

  document.getElementById("examTabBar").addEventListener("click", function (e) {
    var btn = e.target.closest(".tab-btn");
    if (!btn) return;
    var idx = btn.getAttribute("data-mondai-idx");
    document.querySelectorAll("#examTabBar .tab-btn").forEach(function (b) {
      b.classList.toggle("active", b === btn);
    });
    document.querySelectorAll(".exam-mondai-section").forEach(function (sec) {
      sec.style.display = sec.getAttribute("data-mondai-idx") === idx ? "" : "none";
    });
    // 「生词」「生词测试」都不是問題1〜14那套答题流程，底部整份卷子的
    // "交卷"条在这两个tab下都没有意义，藏起来（跟.exam-mondai-submit-bar
    // 在.exam-submitted之后统一隐藏是同一个道理，只是触发条件换成了
    // "当前在生词/生词测试tab"）。
    document.body.classList.toggle("vocab-tab-active", idx === String(VOCAB_SECTION_IDX) || idx === String(QUIZ_SECTION_IDX));
  });

  // 单题批改标记——被"交整份卷子"（submitExam）和"只交这一个大题"
  // （submitMondai）共用。用.review这个class本身当"这题已经标记过"的
  // 幂等判断：一道题如果先被单独交的大题批改过，之后再交整份卷子，
  // 不会把.exam-unanswered-mark再插一遍。返回值（是否答对）不受这个
  // 幂等判断影响，每次都按answers/q.answer现算，两条路径的总分/大题
  // 细分统计都能拿到准确数字。
  function gradeQuestion(q) {
    var qEl = document.getElementById("q-" + q.id);
    var userAns = answers[q.id];
    var isCorrect = String(userAns) === String(q.answer);
    if (!qEl.classList.contains("review")) {
      qEl.classList.add("review");
      qEl.querySelectorAll(".exam-option").forEach(function (o) {
        var oi = o.getAttribute("data-opt");
        if (String(oi) === String(q.answer)) o.classList.add("correct-answer");
        else if (String(oi) === String(userAns)) o.classList.add("wrong-selected");
      });
      if (userAns === undefined) {
        var numEl = qEl.querySelector(".exam-question-num");
        numEl.insertAdjacentHTML("afterend", '<span class="exam-unanswered-mark">未作答</span>');
      }
    }
    return isCorrect;
  }

  // 只交当前这一个大题——跟submitExam()是两条独立路径，谁先谁后互不
  // 覆盖：先单独交过的大题，之后再交整份卷子，gradeQuestion()的幂等
  // 判断会跳过重复标记，但总分照常累计进submitExam()的统计里。
  function submitMondai(sectionIdx) {
    if (submitted || mondaiSubmitted[sectionIdx]) return;
    var m = DATA.mondaiList[sectionIdx - 1];
    if (!m) return;
    mondaiSubmitted[sectionIdx] = true;
    var sec = document.querySelector('.exam-mondai-section[data-mondai-idx="' + sectionIdx + '"]');
    if (!sec) return;
    sec.classList.add("mondai-submitted");
    var total = 0, correct = 0;
    m.blocks.forEach(function (b) {
      b.questions.forEach(function (q) {
        total++;
        if (gradeQuestion(q)) correct++;
      });
    });
    var scoreEl = sec.querySelector(".exam-mondai-submit-score");
    if (scoreEl) scoreEl.textContent = correct + " / " + total;
    var btn = sec.querySelector(".exam-mondai-submit-btn");
    if (btn) btn.disabled = true;
  }

  function submitExam() {
    if (submitted) return;
    submitted = true;
    stopPlayback();
    // body上加这个class纯粹是给"隐藏所有問題自己的'提交本大题'按钮"用的
    // （整份卷子都交了，单独交某一个大题的入口自然没意义），题干/問題9
    // 段落早就不会因为交卷而变化了（见stemHtml()/blockHtml()的注释）。
    document.body.classList.add("exam-submitted");
    var total = 0, correct = 0;
    var perMondai = {};
    DATA.mondaiList.forEach(function (m) {
      perMondai[m.mondai] = { total: 0, correct: 0, label: m.label };
      mondaiSubmitted[m.mondai] = true;
      m.blocks.forEach(function (b) {
        b.questions.forEach(function (q) {
          total++;
          perMondai[m.mondai].total++;
          if (gradeQuestion(q)) { correct++; perMondai[m.mondai].correct++; }
        });
      });
    });

    var banner = document.getElementById("examScoreBanner");
    var mondaiBreakdown = Object.keys(perMondai).map(function (k) {
      var s = perMondai[k];
      return esc(s.label) + " " + s.correct + "/" + s.total;
    }).join("　");
    banner.innerHTML = '<div class="exam-score-num">' + correct + " / " + total + "</div>" +
      '<div class="exam-mondai-score">' + mondaiBreakdown + "</div>";
    banner.classList.add("show");
    document.getElementById("examSubmitBtn").disabled = true;
    document.getElementById("examProgressText").textContent = "已交卷，逐题解析已展开";
    if (banner.scrollIntoView) banner.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.getElementById("examSubmitBtn").addEventListener("click", submitExam);

  render();
})();
