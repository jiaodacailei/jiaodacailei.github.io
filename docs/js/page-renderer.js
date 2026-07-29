// data-driven 听力页的前端渲染器——如果页面没有 window.LESSON_DATA（旧版
// build_page.py 直接把内容烘焙进 index.html 的页面，或者非听力页），这个文件
// 整个不做任何事，不影响任何现有页面。
//
// 有 window.LESSON_DATA 时，在这里把数据组装成 tab栏/侧栏目录/mondai-section/
// question-block/seg-card 这套 DOM 结构——结构必须跟 tools/listening/build_page.py
// 生成的完全一致（相同 class/id/data-* 属性），这样 listening-page.js 剩下的全部
// 交互逻辑（播放/跟读高亮/默写/填空/单词测试）不用改一行，它们看到的 DOM 跟以前
// Python 直接烘焙出来的没有任何区别。
//
// 这个文件必须以普通（非 defer 或者排在 listening-page.js 前面的 defer）脚本
// 形式，在 listening-page.js 之前执行完——listening-page.js 里大量
// `document.querySelectorAll(".seg-card")` 这类查询是脚本顶层直接跑的，不是包在
// DOMContentLoaded 或者某个"数据就绪"回调里，如果这个文件跑晚了或者是异步的，
// 那些查询会查到空结果，所有交互都不会生效。
(function () {
  var DATA = window.LESSON_DATA;
  if (!DATA) return;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // 跟 tools/listening/build_page.py 的 ruby_html_from_tokens() 是同一份逻辑——
  // 两边必须保持一致，token 有 kana 且跟 text 不同就包一层 <ruby>，有 t 就包一层
  // <span class="tw" data-t="...">。所有"怎么分词、读音该是什么"的判断都已经在
  // 生成 data.js 那一步由 Python（pykakasi + 各种订正表）做完了，这里纯粹是
  // 模板拼接，不做任何语言学分析。
  function renderTokens(tokens) {
    var parts = [];
    (tokens || []).forEach(function (tok) {
      if (tok.text === "\n") { parts.push("<br>"); return; }
      var text = esc(tok.text);
      var inner = tok.kana && tok.kana !== tok.text
        ? "<ruby>" + text + "<rt>" + esc(tok.kana) + "</rt></ruby>"
        : text;
      if (tok.t !== undefined && tok.t !== null) {
        parts.push('<span class="tw" data-t="' + tok.t.toFixed(2) + '">' + inner + "</span>");
      } else {
        parts.push(inner);
      }
    });
    return parts.join("");
  }

  // 跟 build_page.py 的 sentence_card_html() 一一对应。
  function renderCard(s) {
    var zh = esc(s.zh).replace(/\n/g, "<br>");
    var notesHtml = s.notes ? '<div class="seg-notes">' + esc(s.notes) + "</div>" : "";
    var jaHtml = renderTokens(s.tokens);

    var cardClass = "seg-card";
    var speakerHtml = "";
    if (s.speaker) {
      cardClass += " has-speaker";
      var speakerInner = s.speakerKana
        ? "<ruby>" + esc(s.speaker) + "<rt>" + esc(s.speakerKana) + "</rt></ruby>"
        : esc(s.speaker);
      speakerHtml = '<div class="seg-speaker">' + speakerInner + "</div>";
    }

    var blanksAttr = "";
    if (s.blanks && s.blanks.length) {
      blanksAttr = ' data-blanks="' + esc(JSON.stringify(s.blanks)) + '"';
    }

    return (
      '<div class="' + cardClass + '" id="card-a' + s.id + '"' + blanksAttr + ">" +
        speakerHtml +
        '<p class="seg-ja">' + jaHtml + "</p>" +
        '<p class="seg-zh">' + zh + "</p>" + notesHtml +
        '<audio id="a' + s.id + '" preload="none" src="' + esc(s.audio) + '"></audio>' +
      "</div>"
    );
  }

  // 跟 build_page.py 的 question_block_html() 一一对应。
  function renderQuestionBlock(mondaiIdx, qIdx, q) {
    var label = q.question || "";
    var overviewHtml = q.overview ? '<p class="q-overview">' + esc(q.overview) + "</p>" : "";
    var answerHtml = q.answer
      ? '<details class="seg-answer"><summary>答えを見る</summary><div>' + esc(q.answer) + "</div></details>"
      : "";
    var cards = q.sentences.map(renderCard).join("");
    return (
      '<div class="question-block" id="q-' + mondaiIdx + "-" + qIdx + '" data-scope="question">' +
        "<h3>" + esc(label) + "</h3>" +
        overviewHtml + answerHtml + cards +
      "</div>"
    );
  }

  // 跟 build_page.py 的 mondai_section_html() 一一对应。
  function renderMondaiSection(mondaiIdx, tab, active) {
    var label = tab.question || tab.mondai;
    var blocks = tab.questions.map(function (q, qi) {
      return renderQuestionBlock(mondaiIdx, qi + 1, q);
    }).join("");
    var cls = "mondai-section" + (active ? " tab-active" : "");
    return (
      '<section class="' + cls + '" id="m-' + mondaiIdx + '" data-scope="mondai">' +
        "<h2>" + esc(tab.mondai) + "</h2>" + blocks +
      "</section>"
    );
  }

  // 跟 build_page.py 的 quiz_section_html() 一一对应——単語テスト tab 不是
  // seg-card 列表，是运行时纯前端生成的互动题，这里只需要把 quiz 数据塞进跟
  // 生成时同名的 <script id="vocab-quiz-data"> 里，listening-page.js 里的 quiz
  // 引擎自己会去找这个标签接管渲染，逻辑完全不用动。
  function renderQuizSection(mondaiIdx, quizData, active) {
    var cls = "mondai-section" + (active ? " tab-active" : "");
    return (
      '<section class="' + cls + '" id="m-' + mondaiIdx + '" data-scope="mondai">' +
        "<h2>単語テスト</h2>" +
        '<div class="quiz-app" id="quizApp">' +
          '<div class="quiz-toolbar">' +
            '<div class="quiz-progress" id="quizProgress">0 / 0</div>' +
            '<button type="button" class="quiz-reset-btn" id="quizResetErrors">清除使用记录</button>' +
          "</div>" +
          '<div class="quiz-card" id="quizCard">' +
            '<div class="quiz-type-label" id="quizTypeLabel"></div>' +
            '<div class="quiz-prompt" id="quizPrompt"></div>' +
            '<button type="button" class="quiz-play-btn" id="quizPlayBtn" style="display:none">▶ 播放发音</button>' +
            '<div class="quiz-input-row">' +
              '<input type="text" class="quiz-input" id="quizInput" autocomplete="off" placeholder="在此输入…">' +
              '<button type="button" class="quiz-btn quiz-check" id="quizCheck">確認</button>' +
              '<button type="button" class="quiz-btn quiz-next" id="quizNext" style="display:none">次へ</button>' +
            "</div>" +
            '<div class="quiz-status" id="quizStatus"></div>' +
          "</div>" +
          '<div class="quiz-done" id="quizDone" style="display:none">🎉 本轮全部完成！</div>' +
        "</div>" +
        '<script type="application/json" id="vocab-quiz-data">' + JSON.stringify(quizData) + "</script>" +
      "</section>"
    );
  }

  // 跟 build_page.py 的 side_nav_list_html() 一一对应（桌面 .toc 和手机
  // .toc-float-panel 共用同一份 <ul> 标记）。
  function renderSideNavList(mondaiIdx, questionLabels, active) {
    var cls = "side-nav-list" + (active ? " tab-active" : "");
    var items = questionLabels.map(function (label, i) {
      return '<li class="toc-h2"><a class="side-nav-btn" data-target="q-' + mondaiIdx + "-" + (i + 1) + '">' + esc(label) + "</a></li>";
    }).join("");
    return '<ul class="' + cls + '" data-mondai-idx="' + mondaiIdx + '">' + items + "</ul>";
  }

  // 跟 build_page.py 的 mobile_nums_list_html() 一一对应。
  function renderMobileNumsList(mondaiIdx, questionLabels, active) {
    var cls = "snm-nums-list" + (active ? " tab-active" : "");
    var btns = questionLabels.map(function (_label, i) {
      var qi = i + 1;
      return '<button class="toc-float-num side-nav-btn" data-target="q-' + mondaiIdx + "-" + qi + '">' + qi + "</button>";
    }).join("");
    return '<div class="' + cls + '" data-mondai-idx="' + mondaiIdx + '">' + btns + "</div>";
  }

  var sections = [];
  var navLists = [];
  var navNumsMobile = [];
  var tabLabels = [];

  (DATA.tabs || []).forEach(function (tab, i) {
    var mondaiIdx = i + 1;
    var isFirst = mondaiIdx === 1;
    var qLabels = tab.questions.map(function (q) { return q.question || tab.mondai; });
    sections.push(renderMondaiSection(mondaiIdx, tab, isFirst));
    navLists.push(renderSideNavList(mondaiIdx, qLabels, isFirst));
    navNumsMobile.push(renderMobileNumsList(mondaiIdx, qLabels, isFirst));
    tabLabels.push(tab.mondai);
  });

  if (DATA.quiz) {
    var quizIdx = (DATA.tabs || []).length + 1;
    sections.push(renderQuizSection(quizIdx, DATA.quiz, false));
    navLists.push(renderSideNavList(quizIdx, [], false));
    navNumsMobile.push(renderMobileNumsList(quizIdx, [], false));
    tabLabels.push("単語テスト");
  }

  var tabButtons = tabLabels.map(function (label, i) {
    var idx = i + 1;
    return '<button class="tab-btn' + (idx === 1 ? " active" : "") + '" data-mondai-idx="' + idx + '">' + esc(label) + "</button>";
  }).join("");

  document.getElementById("tabBar").innerHTML = tabButtons;
  document.getElementById("sideNavLists").innerHTML = navLists.join("");
  document.getElementById("sideNavListsMobile").innerHTML = navLists.join("");
  document.getElementById("mobileNumsLists").innerHTML = navNumsMobile.join("");
  document.getElementById("postBody").innerHTML = sections.join("");
})();
