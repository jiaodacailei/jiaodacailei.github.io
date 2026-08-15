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

  // ---- 渲染 ----
  var root = document.getElementById("examRoot");

  function passageHtml(sentences) {
    if (!sentences || !sentences.length) return "";
    var rows = sentences.map(function (s, i) {
      var playBtn = s.audio
        ? '<button class="exam-inline-play" data-audio="' + esc(s.audio) + '" title="読み上げ">🔊</button>'
        : "";
      return '<div class="exam-passage-sentence">' + playBtn +
        '<span class="exam-passage-text">' + renderTokensHtml(s.tokens) + "</span></div>";
    }).join("");
    return '<div class="exam-passage">' + rows + "</div>";
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
    if (q.stem) {
      return '<div class="exam-stem-row"><button class="exam-play-btn" data-audio="' +
        esc(q.stem.audio) + '">▶</button><span>' + renderTokensHtml(q.stem.tokens) + "</span></div>";
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
    return '<div class="exam-block">' + passageHtml(block.passageSentences) + qsHtml + "</div>";
  }

  function mondaiSectionHtml(m, idx) {
    var blocksHtml = m.blocks.map(blockHtml).join("");
    return '<section class="exam-mondai-section" data-mondai-idx="' + (idx + 1) + '"' +
      (idx === 0 ? "" : ' style="display:none"') + ">" +
      '<div class="exam-mondai-instruction">' + esc(m.instruction) + "</div>" +
      blocksHtml + "</section>";
  }

  function tabBarHtml() {
    return DATA.mondaiList.map(function (m, i) {
      return '<button class="tab-btn' + (i === 0 ? " active" : "") + '" data-mondai-idx="' + (i + 1) + '">' +
        esc(m.label) + "</button>";
    }).join("");
  }

  function render() {
    document.getElementById("examTitle").textContent = DATA.title;
    document.getElementById("examTabBar").innerHTML = tabBarHtml();
    root.innerHTML = DATA.mondaiList.map(mondaiSectionHtml).join("");
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
    if (submitted) return;
    var opt = e.target.closest(".exam-option");
    if (opt) {
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
  });

  function submitExam() {
    if (submitted) return;
    submitted = true;
    stopPlayback();
    var total = 0, correct = 0;
    var perMondai = {};
    DATA.mondaiList.forEach(function (m) {
      perMondai[m.mondai] = { total: 0, correct: 0, label: m.label };
      m.blocks.forEach(function (b) {
        b.questions.forEach(function (q) {
          total++;
          perMondai[m.mondai].total++;
          var qEl = document.getElementById("q-" + q.id);
          qEl.classList.add("review");
          var userAns = answers[q.id];
          var isCorrect = String(userAns) === String(q.answer);
          if (isCorrect) { correct++; perMondai[m.mondai].correct++; }
          qEl.querySelectorAll(".exam-option").forEach(function (o) {
            var oi = o.getAttribute("data-opt");
            if (String(oi) === String(q.answer)) o.classList.add("correct-answer");
            else if (String(oi) === String(userAns)) o.classList.add("wrong-selected");
          });
          if (userAns === undefined) {
            var numEl = qEl.querySelector(".exam-question-num");
            numEl.insertAdjacentHTML("afterend", '<span class="exam-unanswered-mark">未作答</span>');
          }
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
