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

  // 跟 tools/listening/build_page.py 的 _is_kanji()/_kata_to_hira_char()/
  // _split_kana_segments() 是同一份逻辑的 JS 移植——原来这几个函数只在 Python
  // 生成 data.js 那一步跑一次，注释里写"这里纯粹是模板拼接，不做任何语言学
  // 分析"是因为假设 token 永远是 Python 那边预先拆好的。但编辑模式
  // （edit-mode.js）允许直接在浏览器里手打一个"汉字+送假名"合并成一个 token
  // 的 kana 覆盖（比如把"聞き間違える"整个填一个 kana="ききまちがえる"），
  // 这条路径完全绕开了 Python，如果渲染器自己不会拆，编辑模式存的合并 token
  // 就会照原样渲染成一个 <ruby> 盖住整段文字——真实案例：用户在编辑模式里
  // 填了这种合并 token，验证发现确实没有正确拆分。渲染器必须有能力独立完成
  // 同样的拆分，不能只依赖 Python 那一步做好，两边逻辑改动也要保持同步。
  function isKanji(ch) {
    var code = ch.charCodeAt(0);
    return (code >= 0x4e00 && code <= 0x9fff) || ch === "々";
  }

  function kataToHiraChar(ch) {
    var code = ch.charCodeAt(0);
    return (code >= 0x30a1 && code <= 0x30f6) ? String.fromCharCode(code - 0x60) : ch;
  }

  // 跟 tools/listening/build_page.py 的 _KANJI_MIN_MORA 是同一张表——某些
  // 常见汉字单字训读本身有2拍以上，如果这个字读音的最后一拍恰好跟紧跟着的
  // 送假名首字符相同（比如"低く"，低→ひく最后一拍是く，紧跟送假名也是く），
  // 默认"至少1拍"的下限不够，会在还没跳过这个字真实读音之前就撞见这个假
  // 字符，误判读音提前结束（真实案例："低"被错误注音成"ひ"，正确应为
  // "ひく"）。只登记真的观察到撞车的字，不用未卜先知地收录每个2拍字。
  var KANJI_MIN_MORA = { "低": 2 };

  function splitKanaSegments(orig, hira) {
    if (orig === hira) return [{ text: orig }];
    var groups = [];
    for (var i = 0; i < orig.length; i++) {
      var ch = orig[i];
      var k = isKanji(ch);
      if (groups.length && groups[groups.length - 1][0] === k) {
        groups[groups.length - 1][1] += ch;
      } else {
        groups.push([k, ch]);
      }
    }
    var kanjiGroupCount = groups.filter(function (g) { return g[0]; }).length;
    if (kanjiGroupCount === 0 || kanjiGroupCount === groups.length) {
      // 退化情况：整段没有汉字，或者整段全是汉字（熟字训，没有送假名可当
      // 定位锚点）——都没法按分段对齐，整体当一段注音。
      return [{ text: orig, kana: hira }];
    }

    // "〜"（语法笔记占位符，比如"〜性""同〜"）完全不发音，字面不会出现在
    // hira 里——先过滤掉它跑锚点定位算出每段汉字的读音，最后再按原始顺序
    // 把占位段交错拼回去（不能在第一遍顺手拼，"〜"可能出现在待定汉字读音
    // **结算之前**，比如"同〜"，"同"的读音要等到整个 orig 处理完才结算，
    // 这时候如果顺手把"〜"也塞进 segments，输出顺序会变成"〜"排在"同"前面）。
    // 占位符"〜"可能是 U+301C（WAVE DASH）或 U+FF5E（FULLWIDTH TILDE）两种
    // 视觉相似但码位不同的字符（真实案例 textbook-sjp-zg-l16 用了后者），
    // 两种都要当占位符处理，见 build_page.py 里 _split_kana_segments() 的
    // 同款修复（两处逻辑必须保持同步）。
    var filtered = groups.filter(function (g) { return g[0] || (g[1] !== "〜" && g[1] !== "～"); });
    var kanjiReadings = [];
    var hiraPos = 0;
    var pendingKanji = null;
    filtered.forEach(function (g) {
      var isK = g[0], gtext = g[1];
      if (isK) { pendingKanji = gtext; return; }
      if (pendingKanji !== null) {
        var anchorChar = kataToHiraChar(gtext[0]);
        var minMora = 0;
        for (var ci = 0; ci < pendingKanji.length; ci++) {
          minMora += KANJI_MIN_MORA[pendingKanji[ci]] || 1;
        }
        var minStart = hiraPos + Math.max(1, minMora);
        var idx = hira.indexOf(anchorChar, minStart);
        if (idx === -1) idx = hira.indexOf(anchorChar, hiraPos);
        if (idx === -1) {
          kanjiReadings.push(null);
          idx = hiraPos;
        } else {
          kanjiReadings.push(hira.slice(hiraPos, idx) || null);
        }
        hiraPos = idx;
        pendingKanji = null;
      }
      hiraPos += gtext.length;
    });
    if (pendingKanji !== null) {
      kanjiReadings.push(hira.slice(hiraPos) || null);
    }

    var segments = [];
    var ki = 0;
    groups.forEach(function (g) {
      var isK = g[0], gtext = g[1];
      if (isK) {
        var reading = kanjiReadings[ki++];
        segments.push(reading ? { text: gtext, kana: reading } : { text: gtext });
      } else {
        segments.push({ text: gtext });
      }
    });
    return segments;
  }

  // 跟 tools/listening/build_page.py 的 ruby_html_from_tokens() 是同一份逻辑——
  // 两边必须保持一致，token 有 kana 且跟 text 不同就包一层 <ruby>，有 t 就包一层
  // <span class="tw" data-t="...">。"怎么分词、读音该是什么"这部分语言学判断
  // （pykakasi + 各种订正表）仍然只在 Python 生成 data.js 那一步做——这里只是
  // 额外兜底"送假名要不要从汉字读音里拆出来"这一步（splitKanaSegments()），
  // 保证不管 token 是 Python 预先拆好的、还是编辑模式里手填的合并 kana 覆盖，
  // 渲染出来的排版规则都一致。
  function renderTokens(tokens) {
    var parts = [];
    (tokens || []).forEach(function (tok) {
      if (tok.text === "\n") { parts.push("<br>"); return; }
      var segs = (tok.kana && tok.kana !== tok.text)
        ? splitKanaSegments(tok.text, tok.kana)
        : [{ text: tok.text }];
      var inner = segs.map(function (seg) {
        var segText = esc(seg.text);
        return (seg.kana && seg.kana !== seg.text)
          ? "<ruby>" + segText + "<rt>" + esc(seg.kana) + "</rt></ruby>"
          : segText;
      }).join("");
      if (tok.t !== undefined && tok.t !== null) {
        parts.push('<span class="tw" data-t="' + tok.t.toFixed(2) + '">' + inner + "</span>");
      } else {
        parts.push(inner);
      }
    });
    return parts.join("");
  }

  // 跟 build_page.py 的 sentence_card_html() 一一对应。contextSpeaker 是"进
  // 这张卡片之前，当前对话轮到谁说"的状态（由 renderQuestionBlock 按顺序
  // 维护，见那边的注释）——同一个人连续说好几句时，只有第一句在 data 里
  // 显式带 speaker，后面几句 speaker 是 null，但左边的说话人栏依然要空出来
  // 跟上一句对齐（只是不重复显示名字），不然连续对话看起来就一会儿缩进一会儿
  // 不缩进，很乱。
  function renderCard(s, contextSpeaker) {
    var zh = esc(s.zh).replace(/\n/g, "<br>");
    var notesHtml = s.notes ? '<div class="seg-notes">' + esc(s.notes) + "</div>" : "";
    var jaHtml = renderTokens(s.tokens);

    var cardClass = "seg-card";
    var speakerHtml = "";
    if (s.speaker || contextSpeaker) {
      cardClass += " has-speaker";
      if (s.speaker) {
        var speakerInner = s.speakerKana
          ? "<ruby>" + esc(s.speaker) + "<rt>" + esc(s.speakerKana) + "</rt></ruby>"
          : esc(s.speaker);
        speakerHtml = '<div class="seg-speaker">' + speakerInner + "</div>";
      } else {
        // 延续上一句的说话人，只留空位对齐，不重复显示名字。
        speakerHtml = '<div class="seg-speaker"></div>';
      }
    }

    var blanksAttr = "";
    if (s.blanks && s.blanks.length) {
      blanksAttr = ' data-blanks="' + esc(JSON.stringify(s.blanks)) + '"';
    }
    // 生词卡片自己只有孤立的一个词，没有上下文句子——"填空"模式下借用
    // 单词测试里现成的例句+挖空位置（build_page.py 的 sentence_to_data()
    // 从 quiz_data 反推出来的），quizSentence 存在时优先用这句而不是卡片
    // 自己的 .seg-ja 当挖空底稿，见 listening-page.js 的 setupBlankForCard()。
    var quizSentenceAttr = s.quizSentence
      ? ' data-quiz-sentence="' + esc(s.quizSentence) + '"'
      : "";

    return (
      '<div class="' + cardClass + '" id="card-a' + s.id + '"' + blanksAttr + quizSentenceAttr + ">" +
        speakerHtml +
        '<p class="seg-ja">' + jaHtml + "</p>" +
        '<p class="seg-zh">' + zh + "</p>" + notesHtml +
        '<audio id="a' + s.id + '" preload="none" src="' + esc(s.audio) + '"></audio>' +
      "</div>"
    );
  }

  // 跟 build_page.py 的 question_block_html() 一一对应。currentSpeaker 这个
  // "当前对话轮到谁说"的状态每道小题（question-block）开始时重置为
  // null——换了场景/段落，不该把上一题最后说话的人顺带延续过来。
  function renderQuestionBlock(mondaiIdx, qIdx, q) {
    var label = q.question || "";
    var overviewHtml = q.overview ? '<p class="q-overview">' + esc(q.overview) + "</p>" : "";
    var answerHtml = q.answer
      ? '<details class="seg-answer"><summary>答えを見る</summary><div>' + esc(q.answer) + "</div></details>"
      : "";
    var currentSpeaker = null;
    var cards = q.sentences.map(function (s) {
      var html = renderCard(s, currentSpeaker);
      currentSpeaker = s.speaker || currentSpeaker;
      return html;
    }).join("");
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

  // 编辑模式（docs/js/edit-mode.js）用来在原地刷新一张卡片的显示内容，不用
  // 重新渲染整个页面（那样会把 listening-page.js 已经挂在其它卡片上的交互
  // 状态全部打乱）。只更新 .seg-speaker/.seg-ja/.seg-zh/.seg-notes/data-blanks
  // 这几处内容，不动 .seg-card 本身这个 DOM 节点（点击播放的事件监听器挂在
  // 卡片节点上，节点不替换就不用重新绑定）。
  //
  // 说话人栏是否显示（has-speaker 类）**保持卡片原有状态不变**，不根据编辑
  // 后的 speaker 字段重新判断——判断"这句该不该有说话人缩进"依赖同一小题里
  // 前后句的说话人状态链（见 renderQuestionBlock 的 contextSpeaker），单张
  // 卡片编辑时不具备这个上下文，重新计算容易算错、影响到没被编辑的其它卡片。
  // 如果真的需要新增/去掉某句的说话人缩进，应该走完整重新生成流程，不是这里
  // 的局部编辑。
  function rerenderCardContent(cardEl, s) {
    var jaHtml = renderTokens(s.tokens);
    cardEl.querySelector(".seg-ja").innerHTML = jaHtml;
    cardEl.querySelector(".seg-zh").innerHTML = esc(s.zh).replace(/\n/g, "<br>");

    var notesEl = cardEl.querySelector(".seg-notes");
    if (s.notes) {
      if (!notesEl) {
        notesEl = document.createElement("div");
        notesEl.className = "seg-notes";
        cardEl.querySelector(".seg-zh").insertAdjacentElement("afterend", notesEl);
      }
      notesEl.innerHTML = esc(s.notes);
    } else if (notesEl) {
      notesEl.remove();
    }

    var speakerEl = cardEl.querySelector(".seg-speaker");
    if (speakerEl) {
      speakerEl.innerHTML = s.speaker
        ? (s.speakerKana
          ? "<ruby>" + esc(s.speaker) + "<rt>" + esc(s.speakerKana) + "</rt></ruby>"
          : esc(s.speaker))
        : "";
    }

    if (s.blanks && s.blanks.length) {
      cardEl.dataset.blanks = JSON.stringify(s.blanks);
    } else {
      delete cardEl.dataset.blanks;
    }
  }

  window.PageRenderer = { renderTokens: renderTokens, rerenderCardContent: rerenderCardContent };
})();
