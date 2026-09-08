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
  // "色"→いろ、"短"→みじか 同一类坑，跟 build_page.py 的表保持同步
  // （这两条之前在JS版本里漏收录了，是发现"短"这条坑时一起补的）。
  var KANJI_MIN_MORA = { "低": 2, "色": 2, "短": 3 };

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

  // 生词卡片"跟读"模式下面显示的例句——挖空目标词（blanks数组）加粗
  // 标出来，纯展示不给input。跟 listening-page.js 的 setupBlankForCard()
  // 定位挖空位置用的是同一套逻辑（indexOf + searchFrom 顺序往后找，
  // 处理同一段文字出现不止一次的情况），保持两处"怎么在句子里找到blanks
  // 对应的文字"这件事只有一套判断标准。
  // data-quiz-sentence/data-blanks 现在直接标在这个块自己身上（不是卡片
  // 外层），因为一张卡片可能有多个例句块（生词卡片的moreExamples，见下面
  // renderCard()）——setupBlankForCard() 按 .seg-example 逐块遍历，每块
  // 各自定位自己的挖空，不再假设卡片里只有唯一一份 quizSentence/blanks。
  function exampleSentenceHtml(sentence, blanks, audioSrc) {
    var ranges = [];
    var searchFrom = 0;
    (blanks || []).forEach(function (b) {
      var idx = sentence.indexOf(b, searchFrom);
      if (idx === -1) return;
      ranges.push({ start: idx, end: idx + b.length });
      searchFrom = idx + b.length;
    });
    var html = "";
    var cursor = 0;
    ranges.forEach(function (r) {
      html += esc(sentence.slice(cursor, r.start));
      html += '<b class="example-target">' + esc(sentence.slice(r.start, r.end)) + "</b>";
      cursor = r.end;
    });
    html += esc(sentence.slice(cursor));
    // 例句自己的音频（跟卡片主 <audio> 是两条独立的资源）——真实反馈"点击时
    // 播放的是单词的音频，点击句子时，播放句子的音频（如果没有就不播放）"。
    // 没有 audioSrc 就不生成这个 <audio> 标签，点击例句区域自然找不到可播的
    // 音频、静默不做任何事，不退化成播放单词音频（教材课的 quizSentence 目前
    // 都没有配对的例句录音，一律落在这个"没有就不播"的分支，属于预期行为，
    // 不是缺陷）。是不是 .seg-card 生成时唯一的 <audio> 由
    // `document.querySelectorAll(".seg-card audio")` 那段通用 loading/playing
    // 事件绑定自动接管（不区分是单词还是例句的音频元素，同一套逻辑），不用
    // 专门为这第二个 <audio> 标签另外写绑定代码。
    var audioHtml = audioSrc
      ? '<audio class="seg-example-audio" preload="none" src="' + esc(audioSrc) + '"></audio>'
      : "";
    var blanksAttr = (blanks && blanks.length) ? ' data-blanks="' + esc(JSON.stringify(blanks)) + '"' : "";
    return '<p class="seg-example" data-quiz-sentence="' + esc(sentence) + '"' + blanksAttr + ">" + html + audioHtml + "</p>";
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

    // 会话/课文这类没有quizSentence的卡片，blanks直接挖在卡片自己的
    // .seg-ja上，data-blanks留在卡片级别，这条路径完全不变。生词卡片
    // （有quizSentence）的blanks改成放在各自的.seg-example块上（见下面
    // exampleBlocks），不再重复放一份在卡片级别。
    var blanksAttr = "";
    if (!s.quizSentence && s.blanks && s.blanks.length) {
      blanksAttr = ' data-blanks="' + esc(JSON.stringify(s.blanks)) + '"';
    }
    // 生词卡片自己只有孤立的一个词，没有上下文句子——"填空"模式下借用
    // 单词测试里现成的例句+挖空位置（build_page.py 的 sentence_to_data()
    // 从 quiz_data 反推出来的），quizSentence 存在时优先用这句而不是卡片
    // 自己的 .seg-ja 当挖空底稿，见 listening-page.js 的 setupBlankForCard()。
    // 跟读模式下生词卡片单词下面显示的例句——跟"填空"模式复用同一份
    // quizSentence/blanks数据，只是这里是纯展示（挖空目标加粗，不是
    // input），默写/填空模式下用CSS隐藏掉（见listening-page.css）。
    // 真实反馈"跟读模式时，单词下面有没有对应的例句啊"——之前quizSentence
    // 只在填空模式才看得到，默认的跟读模式完全看不到例句。纯文本，不做
    // 假名注音（quizSentence本来就没有逐词kana数据，跟填空模式一致）。
    //
    // 一个词可能不止一条例句——原有的quizSentence（本来就有）+
    // moreExamples（语法与表达里额外命中这个词的例句追加进来的，见
    // tools/listening/build_grammar_notes_tab.py）——渲染成多个.seg-example
    // 块堆在同一张卡片下面，不是拆成好几张卡片重复显示同一个词（真实反馈
    // "投げ込む单词重复了"）。
    var exampleBlocks = [];
    if (s.quizSentence) exampleBlocks.push({ sentence: s.quizSentence, blanks: s.blanks, audio: s.sentenceAudio });
    (s.moreExamples || []).forEach(function (ex) {
      exampleBlocks.push({ sentence: ex.quizSentence, blanks: ex.blanks, audio: ex.sentenceAudio });
    });
    var exampleHtml = exampleBlocks.map(function (ex) {
      return exampleSentenceHtml(ex.sentence, ex.blanks, ex.audio);
    }).join("");
    // 跟 build_page.py 的 sentence_card_html() 里 clause_bounds_attr 一一对应——
    // 见 tools/listening/build_page.py 的 sentence_to_data() 注释。
    var clauseBoundsAttr = "";
    if (s.clauseBounds && s.clauseBounds.length) {
      clauseBoundsAttr = ' data-clause-bounds="' + s.clauseBounds.join(",") + '"';
    }

    return (
      '<div class="' + cardClass + '" id="card-a' + s.id + '"' + blanksAttr + clauseBoundsAttr + ">" +
        speakerHtml +
        '<p class="seg-ja">' + jaHtml + "</p>" +
        '<p class="seg-zh">' + zh + "</p>" + notesHtml + exampleHtml +
        (s.audio
          ? '<audio id="a' + s.id + '" preload="none" src="' + esc(s.audio) + '"></audio>'
          : '<audio id="a' + s.id + '" preload="none"></audio>') +
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
    var unitAttr = q.unit ? ' data-unit="' + esc(q.unit) + '"' : "";
    // wordAudio：N2语法/词汇页专属（词条/语法点标题本身的发音，独立于
    // 例句音频）——真实反馈"点击单词也要可以发音，和例句一样"，点标题
    // 播这份音频，见 listening-page.js 里 h3 click 那段。没有这个字段的
    // 页面（普通课文/听力页）不生成这个 <audio> 标签，点标题保持原有的
    // "从这里开始连续播放"行为不变。
    var wordAudioHtml = q.wordAudio
      ? '<audio class="word-audio" preload="none" src="' + esc(q.wordAudio) + '"></audio>'
      : "";
    return (
      '<div class="question-block" id="q-' + mondaiIdx + "-" + qIdx + '" data-scope="question"' + unitAttr + '>' +
        '<h3><span class="q-title-text">' + esc(label) + "</span>" + wordAudioHtml + "</h3>" +
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

  // 跟 build_page.py 的 mcq_section_html() 一一对应——独立于単语テスト的
  // "四选一"练习引擎（docs/js/mcq-quiz.js），N2语法/词汇页面专用。
  function renderMcqSection(mondaiIdx, mcqData, active) {
    var cls = "mondai-section" + (active ? " tab-active" : "");
    return (
      '<section class="' + cls + '" id="m-' + mondaiIdx + '" data-scope="mondai">' +
        "<h2>練習</h2>" +
        '<div class="quiz-app" id="mcqApp">' +
          '<div class="quiz-toolbar">' +
            '<div class="quiz-progress" id="mcqProgress">0 / 0</div>' +
            '<button type="button" class="quiz-reset-btn" id="mcqResetErrors">清除使用记录</button>' +
          "</div>" +
          '<div class="quiz-card" id="mcqCard">' +
            '<div class="mcq-stem" id="mcqStem"></div>' +
            '<div class="mcq-options" id="mcqOptions"></div>' +
            '<div class="quiz-status" id="mcqStatus"></div>' +
            '<div class="mcq-explanation" id="mcqExplanation"></div>' +
          "</div>" +
          '<div class="quiz-done" id="mcqDone" style="display:none">🎉 本轮全部完成！</div>' +
        "</div>" +
        '<script type="application/json" id="mcq-quiz-data">' + JSON.stringify(mcqData) + "</script>" +
      "</section>"
    );
  }

  // 标题默写页（N2语法/词汇，DATA.titleDictate）专属：默写/填空模式下侧栏
  // 目录也得把日语藏起来——不然旁边始终挂着一份"0005. 思いつき（おもいつき）"
  // 这样的答案，标题默写再怎么隐藏正文都没用。中文候补文字直接复用
  // overview 第一行（跟标题默写用的是同一份思路：接续：开头那行会把语法点
  // 原文写出来，先过滤掉，避免侧栏反而成了泄题的地方）——不新开字段。
  var NAV_LEAKY_OVERVIEW_LINE_RE = /^(接续|接続)[：:]/;
  function firstSafeOverviewLine(overview) {
    var lines = (overview || "").split("\n").filter(function (line) { return !NAV_LEAKY_OVERVIEW_LINE_RE.test(line); });
    return lines[0] || "";
  }

  // 词条数量很多时（N2词汇153个词），侧栏一个词一条太长了——真实反馈
  // "按照每十个单词的分组导航（如果最后一组少于5个，就划到上一组）"，
  // 分组规则直接照搬 build_exam_vocab.py 的 chunk_group_sizes()（同一个
  // 用户之前对N2真题模考"单词测试"分类提过一模一样的规则，这里是给侧栏
  // 导航用，两处场景不同但算法相同，各自独立实现一份，不共用模块）。
  // 只有超过 size 才分组——语法01只有10个语法点，10不大于size，
  // 直接走下面 else 分支保持逐条显示，不会被"分组"成唯一一条毫无意义
  // 的导航。分组边界按 unit 分段各自计算（不跨单元合并一组），保证以后
  // 追加词汇02时，新单元的分组从它自己的起点重新算，不会把两个单元的
  // 词混进同一组里。
  var NAV_GROUP_SIZE = 10;
  var NAV_GROUP_MIN_LAST = 5;
  function chunkGroupSizes(n, size, minLast) {
    if (n <= 0) return [];
    if (n <= size) return [n];
    var full = Math.floor(n / size), rem = n % size;
    if (rem === 0) return new Array(full).fill(size);
    if (rem < minLast) return new Array(full - 1).fill(size).concat([size + rem]);
    return new Array(full).fill(size).concat([rem]);
  }
  // 按 unit 分段（同一 unit 内连续的 questions 算一段），每段各自跑
  // chunkGroupSizes，返回 [{startIdx, size, unit}, ...]（startIdx 是
  // questions 数组里的 0-based 下标，跨越整个 mondai，不是段内相对位置）。
  function groupQuestionsByUnit(questions) {
    var groups = [];
    var i = 0;
    while (i < questions.length) {
      var unit = questions[i].unit;
      var j = i;
      while (j < questions.length && questions[j].unit === unit) j++;
      var runLen = j - i;
      var sizes = chunkGroupSizes(runLen, NAV_GROUP_SIZE, NAV_GROUP_MIN_LAST);
      var pos = i;
      sizes.forEach(function (sz) {
        groups.push({ startIdx: pos, size: sz, unit: unit });
        pos += sz;
      });
      i = j;
    }
    return groups;
  }

  // 跟 build_page.py 的 side_nav_list_html() 一一对应（桌面 .toc 和手机
  // .toc-float-panel 共用同一份 <ul> 标记）。questions 传完整对象（不只是
  // 标签字符串）是因为要点里同时要日语标题（跟读模式显示）跟中文提示
  // （默写/填空模式显示，来自 overview），CSS 按 body 的 mode-*/
  // has-title-dictate 类切换显示哪一份，两份都渲染进 DOM，不用 JS 在切换
  // 模式时重新渲染。
  function renderSideNavList(mondaiIdx, questions, active) {
    var cls = "side-nav-list" + (active ? " tab-active" : "");
    var items;
    if (questions.length > NAV_GROUP_SIZE) {
      // 分组导航：每条链接指向这一组第一个词，文字是"起-止"的位置范围
      // （不是词条本身的编号，避免依赖标题里的数字前缀这种词汇页特有的
      // 排版习惯）——纯数字范围不含日语原文，不算泄题，日语/中文两个
      // span 显示同样的文字就够，不用像单条词那样区分。
      items = groupQuestionsByUnit(questions).map(function (g) {
        var label = (g.startIdx + 1) + " - " + (g.startIdx + g.size);
        var unitAttr = g.unit ? ' data-unit="' + esc(g.unit) + '"' : "";
        return '<li class="toc-h2"' + unitAttr + '><a class="side-nav-btn" data-target="q-' + mondaiIdx + "-" + (g.startIdx + 1) + '">' +
          '<span class="side-nav-ja">' + label + "</span>" +
          '<span class="side-nav-cn">' + label + "</span>" +
          "</a></li>";
      }).join("");
    } else {
      items = questions.map(function (q, i) {
        var label = q.question || "";
        // 万一 overview 缺失/过滤完是空的（正常内容不会出现，纯粹兜底）——
        // 退回显示日语标题，不留一个空的导航项。
        var cn = firstSafeOverviewLine(q.overview) || label;
        var unitAttr = q.unit ? ' data-unit="' + esc(q.unit) + '"' : "";
        return '<li class="toc-h2"' + unitAttr + '><a class="side-nav-btn" data-target="q-' + mondaiIdx + "-" + (i + 1) + '">' +
          '<span class="side-nav-ja">' + esc(label) + "</span>" +
          '<span class="side-nav-cn">' + esc(cn) + "</span>" +
          "</a></li>";
      }).join("");
    }
    return '<ul class="' + cls + '" data-mondai-idx="' + mondaiIdx + '">' + items + "</ul>";
  }

  // 跟 build_page.py 的 mobile_nums_list_html() 一一对应。questions 传完整
  // 对象（不只是数量）是为了带上 data-unit，单元筛选时手机悬浮数字条也要
  // 跟着藏——不藏的话点个数字可能跳到一个已经被筛掉、当前不可见的词条。
  // 词条数超过分组阈值时，跟桌面侧栏用同一套分组（按钮数字变成"第几组"
  // 而不是"第几个词"，跟桌面侧栏的链接目标完全一致，只是手机小按钮放不下
  // 完整的范围文字，退回显示组的序号）。
  function renderMobileNumsList(mondaiIdx, questions, active) {
    var cls = "snm-nums-list" + (active ? " tab-active" : "");
    var btns;
    if (questions.length > NAV_GROUP_SIZE) {
      btns = groupQuestionsByUnit(questions).map(function (g, gi) {
        var unitAttr = g.unit ? ' data-unit="' + esc(g.unit) + '"' : "";
        return '<button class="toc-float-num side-nav-btn" data-target="q-' + mondaiIdx + "-" + (g.startIdx + 1) + '"' + unitAttr + ">" + (gi + 1) + "</button>";
      }).join("");
    } else {
      btns = questions.map(function (q, i) {
        var qi = i + 1;
        var unitAttr = q.unit ? ' data-unit="' + esc(q.unit) + '"' : "";
        return '<button class="toc-float-num side-nav-btn" data-target="q-' + mondaiIdx + "-" + qi + '"' + unitAttr + ">" + qi + "</button>";
      }).join("");
    }
    return '<div class="' + cls + '" data-mondai-idx="' + mondaiIdx + '">' + btns + "</div>";
  }

  // renderTokens/renderCard/exampleSentenceHtml/rerenderCardContent 这几个
  // 是纯渲染工具函数，不依赖 window.LESSON_DATA 是否存在——放在下面
  // "!DATA return" 之前无条件暴露，让没有整份 LESSON_DATA、只是想借用同一套
  // .seg-card 渲染规则的页面（比如 n2-exam 页面自己拼的"生词"tab）也能拿到
  // 用，不用整份 LESSON_DATA 页面才配置这些。函数声明本身有变量提升，就算
  // rerenderCardContent 定义在这行下面，这里引用它也没问题。
  window.PageRenderer = {
    renderTokens: renderTokens,
    rerenderCardContent: rerenderCardContent,
    renderCard: renderCard,
    renderQuizSection: renderQuizSection,
    renderMcqSection: renderMcqSection
  };

  // 下面这些是"整份 LESSON_DATA 驱动的听力页"专属的页面级渲染（tab栏/
  // 侧栏目录/mondai-section），必须真的有 window.LESSON_DATA 才跑——旧版
  // build_page.py 直接把内容烘焙进 index.html 的页面，或者非听力页，这里
  // 直接返回，不动那些页面已有的 DOM。
  if (!DATA) return;

  // titleDictate：N2语法/词汇页专属标记（build_n2_reference_page.py 生成时
  // 写进 DATA），标题本身就是"要记住的语法点/单词"，允许对标题做默写/填空。
  // 普通课文/听力页的 question-block 标题是场景名/生词表分组名，不是需要
  // 背诵的内容，不应该被这套逻辑影响，所以必须显式开关，不能靠标题"看起来
  // 像不像一个词"这种猜测去判断。
  if (DATA.titleDictate) document.body.classList.add("has-title-dictate");

  var sections = [];
  var navLists = [];
  var navNumsMobile = [];
  var tabLabels = [];

  (DATA.tabs || []).forEach(function (tab, i) {
    var mondaiIdx = i + 1;
    var isFirst = mondaiIdx === 1;
    var navQuestions = tab.questions.map(function (q) { return { question: q.question || tab.mondai, overview: q.overview, unit: q.unit }; });
    sections.push(renderMondaiSection(mondaiIdx, tab, isFirst));
    navLists.push(renderSideNavList(mondaiIdx, navQuestions, isFirst));
    navNumsMobile.push(renderMobileNumsList(mondaiIdx, navQuestions, isFirst));
    tabLabels.push(tab.mondai);
  });

  if (DATA.quiz) {
    var quizIdx = (DATA.tabs || []).length + 1;
    sections.push(renderQuizSection(quizIdx, DATA.quiz, false));
    navLists.push(renderSideNavList(quizIdx, [], false));
    navNumsMobile.push(renderMobileNumsList(quizIdx, [], false));
    tabLabels.push("単語テスト");
  }

  // DATA.mcq——N2语法/词汇页面的"练习"tab（docs/js/mcq-quiz.js接管），
  // 跟DATA.quiz（単语テスト）是两个独立字段，一个页面理论上可以同时有
  // 两种tab（虽然目前的用法里两者互斥），互不影响，顺序跟在quiz后面。
  if (DATA.mcq) {
    var mcqIdx = (DATA.tabs || []).length + (DATA.quiz ? 1 : 0) + 1;
    sections.push(renderMcqSection(mcqIdx, DATA.mcq, false));
    navLists.push(renderSideNavList(mcqIdx, [], false));
    navNumsMobile.push(renderMobileNumsList(mcqIdx, [], false));
    tabLabels.push("練習");
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

  // 单元选择下拉框（N2语法/词汇页专属，DATA.titleDictate）：内容按单元
  // （词汇01/词汇02……）持续追加进同一个页面，"生词"/"语法点"tab本身不再
  // 分tab（避免顶部tab栏随单元数量无限变长），改成一个跟"生词"/"练习"
  // 平级放在同一行tab栏里的下拉框，选哪个单元，"生词"tab（靠
  // .question-block[data-unit]显隐过滤）和"练习"tab（mcq-quiz.js监听同一个
  // localStorage key+自定义事件）都跟着换——两边共用同一份"当前单元"状态，
  // 不是各自独立的两套筛选。只有1个单元时不渲染下拉框（没有可选的意义），
  // 以后加了词汇02才会出现，不影响当前只有1个单元的现状。
  if (DATA.titleDictate) {
    var unitOrder = [];
    var unitSeen = {};
    (DATA.tabs || []).forEach(function (tab) {
      (tab.questions || []).forEach(function (q) {
        if (q.unit && !unitSeen[q.unit]) { unitSeen[q.unit] = true; unitOrder.push(q.unit); }
      });
    });
    if (unitOrder.length > 1) {
      var UNIT_KEY = "n2-unit:" + location.pathname;
      var currentUnit = localStorage.getItem(UNIT_KEY) || "all";
      if (currentUnit !== "all" && unitSeen[currentUnit] !== true) currentUnit = "all";

      function applyUnitFilter(unit) {
        // 正文卡片、桌面/手机侧栏目录、手机悬浮数字条——四处都要跟着筛，
        // 不然筛完之后侧栏还留着指向被藏起来的词条的链接，点了跳过去
        // 却什么都看不到。
        var selector = ".question-block[data-unit], .toc-h2[data-unit], .toc-float-num[data-unit]";
        document.querySelectorAll(selector).forEach(function (el) {
          el.style.display = (unit === "all" || el.dataset.unit === unit) ? "" : "none";
        });
      }

      var unitSelect = document.createElement("select");
      unitSelect.className = "tab-btn n2-unit-select";
      unitSelect.id = "n2UnitSelect";
      unitSelect.innerHTML = '<option value="all">全部单元</option>' +
        unitOrder.map(function (u) { return '<option value="' + esc(u) + '">' + esc(u) + "</option>"; }).join("");
      unitSelect.value = currentUnit;
      document.getElementById("tabBar").insertBefore(unitSelect, document.getElementById("tabBar").firstChild);

      unitSelect.addEventListener("change", function () {
        currentUnit = unitSelect.value;
        localStorage.setItem(UNIT_KEY, currentUnit);
        applyUnitFilter(currentUnit);
        window.dispatchEvent(new CustomEvent("n2unitchange", { detail: currentUnit }));
      });

      applyUnitFilter(currentUnit);
    }
  }

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

    if (!s.quizSentence && s.blanks && s.blanks.length) {
      cardEl.dataset.blanks = JSON.stringify(s.blanks);
    } else {
      delete cardEl.dataset.blanks;
    }

    // 重建全部例句块（原有quizSentence + moreExamples），不是只处理一块——
    // edit-mode 目前不编辑 quizSentence/moreExamples 本身，这里只是让"改了
    // 别的字段（notes/blanks等）之后"这几块仍然跟卡片其它内容一起刷新，不会
    // 因为只认第一个 .seg-example 而把 moreExamples 渲染出的其余块丢掉。
    var oldExampleEls = cardEl.querySelectorAll(".seg-example");
    var exampleBlocks = [];
    if (s.quizSentence) exampleBlocks.push({ sentence: s.quizSentence, blanks: s.blanks, audio: s.sentenceAudio });
    (s.moreExamples || []).forEach(function (ex) {
      exampleBlocks.push({ sentence: ex.quizSentence, blanks: ex.blanks, audio: ex.sentenceAudio });
    });
    var newExampleHtml = exampleBlocks.map(function (ex) {
      return exampleSentenceHtml(ex.sentence, ex.blanks, ex.audio);
    }).join("");
    if (oldExampleEls.length) {
      oldExampleEls[0].insertAdjacentHTML("beforebegin", newExampleHtml);
      oldExampleEls.forEach(function (el) { el.remove(); });
    } else if (newExampleHtml) {
      var audioEl = cardEl.querySelector("audio");
      audioEl.insertAdjacentHTML("beforebegin", newExampleHtml);
    }
  }
})();
