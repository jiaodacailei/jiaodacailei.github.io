// 日语听力精听页共享脚本（tools/listening/build_page.py 生成的所有页面都用这一份）。
// 密码门逻辑不在这份文件里——那是所有私有页面（不只是听力页）通用的一段，抽到
// private-gate.js 了，页面里在这份文件之前先引入那个。

// 播放/暂停图标（SVG，取自 Material Design，跟 build_page.py 里静态 HTML 用的是
// 同一份路径）——这两个是播放中动态切换用的，其它图标（设置齿轮/循环/关闭/上一个
// 下一个/最前最后）只在生成时渲染一次、不会运行时切换，留在 build_page.py 里当
// 静态 HTML 生成，不用在这份共享 JS 里重复一份。
var ICON_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
var ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';

// ── 统一播放器：逐句 / 小题整体 / 大题整体都走同一套状态，
//    点标题/内容播放，配合右下角悬浮迷你播放器暂停/继续/上一个/下一个/最前/最后/循环/停止 ──
(function() {
  // navType: "sentence" | "question" | "mondai"；navSiblings 是同级兄弟节点数组（用于上一个/
  // 下一个/最前/最后导航，导航不跨级——句子不跨小题、小题不跨大题、大题就是顶层）；
  // loop 不随 playScope 重置，是迷你播放器里的全局开关，切换播放目标时保持原状态。
  var player = {
    audios: [], idx: 0, loop: false, active: false, finished: false, scopeLabel: "",
    navType: null, navSiblings: [], navIndex: -1
  };

  var miniPlayer = document.getElementById("miniPlayer");
  var mpScope = document.getElementById("mpScope");
  var mpPos = document.getElementById("mpPos");
  var mpPlayPause = document.getElementById("mpPlayPause");
  var mpLoop = document.getElementById("mpLoop");
  var mpStop = document.getElementById("mpStop");
  var mpFirst = document.getElementById("mpFirst");
  var mpPrev = document.getElementById("mpPrev");
  var mpNext = document.getElementById("mpNext");
  var mpLast = document.getElementById("mpLast");

  // 跟读高亮：播放到哪个词就给哪个 .tw 加 tw-active。用 requestAnimationFrame
  // 自己重新调度（而不是 audio 的 timeupdate 事件，那个大概 4Hz 一次，词级高亮
  // 切换会明显卡顿），player.active 变 false 时自然停止重新调度、顺带清掉高亮。
  var wordHighlightRAF = null, hlCard = null, hlWord = null;
  function tickWordHighlight() {
    if (!player.active) {
      wordHighlightRAF = null;
      if (hlWord) hlWord.classList.remove("tw-active");
      hlCard = null; hlWord = null;
      return;
    }
    var a = player.audios[player.idx];
    var card = a ? a.closest(".seg-card") : null;
    if (card !== hlCard) {
      if (hlWord) hlWord.classList.remove("tw-active");
      hlWord = null;
      hlCard = card;
    }
    if (a && card) {
      var words = card.querySelectorAll(".seg-ja .tw");
      var t = a.currentTime, active = null;
      for (var i = 0; i < words.length; i++) {
        if (parseFloat(words[i].getAttribute("data-t")) <= t) { active = words[i]; } else { break; }
      }
      if (active !== hlWord) {
        if (hlWord) hlWord.classList.remove("tw-active");
        if (active) active.classList.add("tw-active");
        hlWord = active;
      }
    }
    wordHighlightRAF = requestAnimationFrame(tickWordHighlight);
  }
  function startWordHighlight() {
    if (wordHighlightRAF === null) { wordHighlightRAF = requestAnimationFrame(tickWordHighlight); }
  }

  // 当前正在播放的句子加高亮效果，并自动滚动到可视区域内，方便连播/跳转时跟着看
  function setPlayingCard(audio) {
    document.querySelectorAll(".seg-card.playing").forEach(function(c) { c.classList.remove("playing"); });
    if (audio) {
      var card = audio.closest(".seg-card");
      if (card) {
        card.classList.add("playing");
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }

  function updateMiniPlayer() {
    if (!player.active) {
      miniPlayer.classList.remove("active");
      return;
    }
    miniPlayer.classList.add("active");
    mpScope.textContent = player.scopeLabel;
    mpPos.textContent = player.audios.length > 1 ? (player.idx + 1) + " / " + player.audios.length : "";
    var current = player.audios[player.idx];
    mpPlayPause.innerHTML = current && !current.paused ? ICON_PAUSE : ICON_PLAY;
    mpLoop.classList.toggle("active", player.loop);
    var hasNav = !!player.navType && player.navSiblings.length > 1;
    var atFirst = player.navIndex <= 0;
    var atLast = player.navIndex < 0 || player.navIndex >= player.navSiblings.length - 1;
    mpFirst.disabled = !hasNav || atFirst;
    mpPrev.disabled = !hasNav || atFirst;
    mpNext.disabled = !hasNav || atLast;
    mpLast.disabled = !hasNav || atLast;
  }

  // 主动停止/关闭：彻底隐藏迷你播放器（✕按钮、切 Tab、播完后点了别处）
  function stopPlayer() {
    player.audios.forEach(function(a) { a.onended = null; a.pause(); });
    player.active = false;
    player.finished = false;
    player.audios = [];
    setPlayingCard(null);
    updateMiniPlayer();
  }
  document.addEventListener("stopAllAudio", stopPlayer);

  // 自然播完（没开循环）：迷你播放器不消失，停在"播完"状态，等用户点别处/点✕才关掉
  function finishPlayer() {
    player.idx = Math.max(0, player.audios.length - 1);
    player.finished = true;
    setPlayingCard(null);
    updateMiniPlayer();
  }

  function playNext() {
    if (!player.active) return;
    if (player.idx >= player.audios.length) {
      if (player.loop) { player.idx = 0; } else { finishPlayer(); return; }
    }
    var a = player.audios[player.idx];
    a.currentTime = 0;
    a.onended = function() { player.idx++; playNext(); };
    a.play();
    setPlayingCard(a);
    updateMiniPlayer();
    startWordHighlight();
  }

  // 点句卡片/h3/h2 或迷你播放器导航按钮都走这一个入口。
  // navSiblings/navIndex 定位"这是同级里的第几个"，用于上一个/下一个/最前/最后。
  function playScope(navType, navSiblings, navIndex) {
    var el = navSiblings[navIndex];
    if (navType === "mondai" && document.querySelectorAll(".tab-btn").length) {
      // 切到别的大题要先把 Tab 切过去（会顺带停止当前播放），Tab 切换是同步的，
      // 切完再紧接着开始新播放，不会产生"播了一半又被 Tab 停掉"的竞态。
      document.dispatchEvent(new CustomEvent("activateTab", { detail: { idx: navIndex } }));
    }
    var audios, label;
    if (navType === "sentence") {
      audios = [el.querySelector("audio")];
      label = "文 " + (navIndex + 1) + " / " + navSiblings.length;
    } else if (navType === "question") {
      audios = Array.from(el.querySelectorAll("audio"));
      label = "小問 " + el.querySelector("h3").textContent.trim();
    } else {
      audios = Array.from(el.querySelectorAll("audio"));
      label = "大問 " + el.querySelector("h2").textContent.trim();
    }
    player.audios.forEach(function(a) { a.onended = null; a.pause(); });
    player.audios = audios;
    player.idx = 0;
    player.finished = false;
    player.scopeLabel = label;
    player.navType = navType;
    player.navSiblings = navSiblings;
    player.navIndex = navIndex;
    player.active = true;
    playNext();
  }

  mpPlayPause.addEventListener("click", function() {
    if (!player.active) return;
    if (player.finished) {
      player.finished = false;
      player.idx = 0;
      playNext();
      return;
    }
    var current = player.audios[player.idx];
    if (!current) return;
    if (current.paused) { current.play(); } else { current.pause(); }
    updateMiniPlayer();
  });
  // 播完后停在原地，点了迷你播放器以外的任何地方才把它关掉
  document.addEventListener("click", function(e) {
    if (player.finished && player.active && !miniPlayer.contains(e.target)) {
      stopPlayer();
    }
  });
  mpLoop.addEventListener("click", function() {
    if (!player.active) return;
    player.loop = !player.loop;
    updateMiniPlayer();
  });
  mpStop.addEventListener("click", stopPlayer);
  mpFirst.addEventListener("click", function() {
    if (player.navType) playScope(player.navType, player.navSiblings, 0);
  });
  mpLast.addEventListener("click", function() {
    if (player.navType) playScope(player.navType, player.navSiblings, player.navSiblings.length - 1);
  });
  mpPrev.addEventListener("click", function() {
    if (player.navType && player.navIndex > 0) playScope(player.navType, player.navSiblings, player.navIndex - 1);
  });
  mpNext.addEventListener("click", function() {
    if (player.navType && player.navIndex < player.navSiblings.length - 1) {
      playScope(player.navType, player.navSiblings, player.navIndex + 1);
    }
  });

  document.querySelectorAll(".seg-card").forEach(function(card) {
    card.addEventListener("click", function() {
      var block = card.closest(".question-block");
      var siblings = block ? Array.from(block.querySelectorAll(".seg-card")) : [card];
      playScope("sentence", siblings, siblings.indexOf(card));
    });
  });

  document.querySelectorAll('.question-block[data-scope="question"]').forEach(function(block) {
    var h3 = block.querySelector("h3");
    h3.addEventListener("click", function() {
      var mondaiSec = block.closest(".mondai-section");
      var siblings = mondaiSec ? Array.from(mondaiSec.querySelectorAll('.question-block[data-scope="question"]')) : [block];
      playScope("question", siblings, siblings.indexOf(block));
    });
  });

  document.querySelectorAll('.mondai-section[data-scope="mondai"]').forEach(function(section) {
    var h2 = section.querySelector("h2");
    h2.addEventListener("click", function() {
      var siblings = Array.from(document.querySelectorAll('.mondai-section[data-scope="mondai"]'));
      playScope("mondai", siblings, siblings.indexOf(section));
    });
  });
})();

// ── Tab 切换：問題1~5，点击后只显示该大题内容 + 对应的小题导航 ──
(function() {
  var tabBtns = Array.from(document.querySelectorAll(".tab-btn"));
  if (!tabBtns.length) return;

  // 直接标记某小题为当前高亮，不读取任何布局属性（避免强制回流）
  function setCurrent(targetId) {
    document.querySelectorAll(".side-nav-btn").forEach(function(b) {
      var isCurrent = b.dataset.target === targetId;
      if (b.tagName === "A") {
        b.parentElement.classList.toggle("toc-active", isCurrent);
      } else {
        b.classList.toggle("active", isCurrent);
      }
    });
  }

  function activate(idx, opts) {
    opts = opts || {};
    document.dispatchEvent(new CustomEvent("stopAllAudio"));

    tabBtns.forEach(function(b, i) { b.classList.toggle("active", i === idx); });
    document.querySelectorAll('.mondai-section[data-scope="mondai"]').forEach(function(sec, i) {
      sec.classList.toggle("tab-active", i === idx);
    });
    document.querySelectorAll(".side-nav-list").forEach(function(list, i) {
      list.classList.toggle("tab-active", i === idx);
    });
    document.querySelectorAll(".snm-nums-list").forEach(function(list, i) {
      list.classList.toggle("tab-active", i === idx);
    });
    // 切换后总是回到顶部，所以新 tab 的第一小题必然是"当前项"，直接设置，不用等滚动测量
    setCurrent("q-" + (idx + 1) + "-1");
    if (!opts.skipScroll) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  tabBtns.forEach(function(b, i) {
    b.addEventListener("click", function() { activate(i); });
  });
  // 迷你播放器导航到别的大题时触发，跳过"滚回顶部"（接下来会直接滚到正在播放的那句）
  document.addEventListener("activateTab", function(e) {
    activate(e.detail.idx, { skipScroll: true });
  });
  activate(0, { skipScroll: true });

  // 小题导航（复用博客 .toc / .toc-float 同款结构）：点击滚动到对应 question-block
  var sideNavMobile = document.getElementById("sideNavMobile");
  document.querySelectorAll(".side-nav-btn").forEach(function(b) {
    b.addEventListener("click", function(e) {
      e.preventDefault();
      var target = document.getElementById(b.dataset.target);
      if (target) window.scrollTo({ top: target.offsetTop - 100, behavior: "smooth" });
      if (sideNavMobile) sideNavMobile.classList.remove("toc-open");
    });
  });

  // 高亮当前小题（滚动时用）：用 requestAnimationFrame 节流，避免每个 scroll 事件都同步读布局触发强制回流
  function highlightCurrentQuestion() {
    var activeSection = document.querySelector(".mondai-section.tab-active");
    if (!activeSection) return;
    var blocks = Array.from(activeSection.querySelectorAll(".question-block"));
    var y = window.scrollY + 130, cur = null;
    blocks.forEach(function(bl) { if (bl.offsetTop <= y) cur = bl.id; });
    if (cur) setCurrent(cur);
  }
  var rafPending = false;
  function scheduleHighlight() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function() { rafPending = false; highlightCurrentQuestion(); });
  }
  window.addEventListener("scroll", scheduleHighlight, { passive: true });

  var snmToggle = document.getElementById("snmToggle");
  var snmClose = document.getElementById("snmClose");
  if (snmToggle) snmToggle.addEventListener("click", function() { sideNavMobile.classList.add("toc-open"); });
  if (snmClose) snmClose.addEventListener("click", function() { sideNavMobile.classList.remove("toc-open"); });
})();

// ── 右下角悬浮设置：播放速度 + 显示模式（存 localStorage，刷新/换 tab 都记得住）──
(function() {
  var SPEED_KEY = "n2listen-speed", LANG_KEY = "n2listen-lang";
  var speed = parseFloat(localStorage.getItem(SPEED_KEY) || "1");
  var lang = localStorage.getItem(LANG_KEY) || "both";

  function applySpeed() {
    document.querySelectorAll("audio").forEach(function(a) { a.playbackRate = speed; });
  }
  function applyLang() {
    document.body.classList.remove("lang-ja-only", "lang-zh-only");
    if (lang === "ja") document.body.classList.add("lang-ja-only");
    if (lang === "zh") document.body.classList.add("lang-zh-only");
  }
  applySpeed();
  applyLang();

  document.querySelectorAll("#speedOptions .settings-opt").forEach(function(b) {
    b.classList.toggle("active", parseFloat(b.dataset.speed) === speed);
    b.addEventListener("click", function() {
      speed = parseFloat(b.dataset.speed);
      localStorage.setItem(SPEED_KEY, speed);
      document.querySelectorAll("#speedOptions .settings-opt").forEach(function(x) { x.classList.toggle("active", x === b); });
      applySpeed();
    });
  });
  document.querySelectorAll("#langOptions .settings-opt").forEach(function(b) {
    b.classList.toggle("active", b.dataset.lang === lang);
    b.addEventListener("click", function() {
      lang = b.dataset.lang;
      localStorage.setItem(LANG_KEY, lang);
      document.querySelectorAll("#langOptions .settings-opt").forEach(function(x) { x.classList.toggle("active", x === b); });
      applyLang();
    });
  });

  var settingsToggle = document.getElementById("settingsToggle");
  var settingsPanel = document.getElementById("settingsPanel");
  settingsToggle.addEventListener("click", function(e) {
    e.stopPropagation();
    settingsPanel.classList.toggle("open");
  });
  document.addEventListener("click", function(e) {
    if (settingsPanel.classList.contains("open") && !settingsPanel.contains(e.target) && e.target !== settingsToggle) {
      settingsPanel.classList.remove("open");
    }
  });
})();

// ── 练习模式：跟读（默认，现状）／默写／填空 ──
// 模式按钮是运行时插进设置面板的（不改 build_page.py 模板、不用重新生成任何一个
// 已有页面），默写/填空的 UI 同样是运行时读取 .seg-card 里已有的 .seg-ja/.seg-zh/
// .seg-notes 现造出来的，所以这份改动对所有已生成的听力页（n2-listening、
// dingliehui 会议听力页……）立即生效。
(function() {
  var MODE_KEY = "n2listen-mode";
  var mode = localStorage.getItem(MODE_KEY) || "read";

  function applyMode() {
    document.body.classList.remove("mode-dictate", "mode-blank");
    if (mode === "dictate") document.body.classList.add("mode-dictate");
    if (mode === "blank") document.body.classList.add("mode-blank");
  }

  var settingsPanel = document.getElementById("settingsPanel");
  if (settingsPanel) {
    var group = document.createElement("div");
    group.className = "settings-group";
    group.innerHTML =
      '<div class="settings-label">練習モード</div>' +
      '<div class="settings-options" id="modeOptions">' +
        '<button class="settings-opt" data-mode="read">跟读</button>' +
        '<button class="settings-opt" data-mode="dictate">默写</button>' +
        '<button class="settings-opt" data-mode="blank">填空</button>' +
      '</div>';
    settingsPanel.appendChild(group);
    Array.from(group.querySelectorAll(".settings-opt")).forEach(function(b) {
      b.classList.toggle("active", b.dataset.mode === mode);
      b.addEventListener("click", function() {
        mode = b.dataset.mode;
        localStorage.setItem(MODE_KEY, mode);
        Array.from(group.querySelectorAll(".settings-opt")).forEach(function(x) { x.classList.toggle("active", x === b); });
        applyMode();
      });
    });
  }
  applyMode();

  // 去掉假名注音（<rt>）之后的原文纯文本——默写比对的标准答案、填空定位挖空范围
  // 用的"纯文本坐标系"，都是这份文本。
  function plainTextOf(node) {
    var clone = node.cloneNode(true);
    Array.from(clone.querySelectorAll("rt")).forEach(function(rt) { rt.remove(); });
    return clone.textContent;
  }

  var PUNCT_RE = /[\s　、。，,．.!?！？「」『』()（）:：;；~〜・…\-—―'"]/g;
  function stripPunct(s) { return (s || "").replace(PUNCT_RE, ""); }

  // ---- 默写：逐句隐藏日语原文，常驻提示中文翻译，输入跟原文一致（忽略标点）
  //      才算过关，按小题（question-block）顺序解锁下一句 ----
  document.querySelectorAll(".seg-card").forEach(function(card) {
    var segJa = card.querySelector(".seg-ja");
    var segZh = card.querySelector(".seg-zh");
    if (!segJa) return;
    var answer = plainTextOf(segJa);
    var answerStripped = stripPunct(answer);

    var ui = document.createElement("div");
    ui.className = "dictate-ui";
    ui.innerHTML =
      '<div class="dictate-hint"></div>' +
      '<div class="dictate-row">' +
        '<input type="text" class="dictate-input" autocomplete="off" placeholder="听写这一句的日语…">' +
        '<button type="button" class="dictate-btn dictate-check">確認</button>' +
        '<button type="button" class="dictate-btn dictate-reveal">答えを見る</button>' +
      '</div>' +
      '<div class="dictate-status"></div>' +
      '<div class="dictate-answer"></div>' +
      '<div class="dictate-locked">🔒 先完成上一句</div>';
    segJa.insertAdjacentElement("afterend", ui);

    var input = ui.querySelector(".dictate-input");
    var checkBtn = ui.querySelector(".dictate-check");
    var revealBtn = ui.querySelector(".dictate-reveal");
    var status = ui.querySelector(".dictate-status");
    var answerBox = ui.querySelector(".dictate-answer");
    var hintBox = ui.querySelector(".dictate-hint");
    if (segZh) hintBox.textContent = segZh.textContent;
    // 只挡输入框/按钮的点击（避免每次点它们都触发外层 .seg-card 的"点击播放"），
    // 提示区/空白处仍然能点击播放——不整体 stopPropagation。
    [input, checkBtn, revealBtn].forEach(function(el) {
      el.addEventListener("click", function(e) { e.stopPropagation(); });
    });

    card._dictate = { state: "locked" };

    function setState(s) {
      card._dictate.state = s;
      ui.classList.remove("state-locked", "state-active", "state-done");
      ui.classList.add("state-" + s);
      input.disabled = (s !== "active");
    }
    card._dictate.setState = setState;
    setState("locked");

    function check(reveal) {
      if (card._dictate.state === "done") return;
      var matched = stripPunct(input.value) === answerStripped;
      if (reveal || matched) {
        var badge = matched
          ? '<span class="dictate-badge ok">✓ 正解</span> '
          : '<span class="dictate-badge rev">👁 答案</span> ';
        answerBox.innerHTML = badge + segJa.innerHTML;
        setState("done");
        advance(card);
      } else {
        status.textContent = "✗ 不一致，再检查一下";
        status.className = "dictate-status ng";
      }
    }
    checkBtn.addEventListener("click", function() { check(false); });
    revealBtn.addEventListener("click", function() { check(true); });
    input.addEventListener("keydown", function(e) {
      if (e.key === "Enter") { e.preventDefault(); check(false); }
    });
  });

  function advance(card) {
    var block = card.closest(".question-block");
    if (!block) return;
    var cards = Array.from(block.querySelectorAll(".seg-card")).filter(function(c) { return c._dictate; });
    var i = cards.indexOf(card);
    // 只在原地解锁下一句，不自动聚焦/自动滚动——之前 focus()+scrollIntoView 会把视口
    // 拉到下一句，如果下一句的"確認/答えを見る"按钮刚好滚到跟当前点击位置同一个坐标，
    // 用户紧接着的第二次点击（哪怕只是手抖多点一下）就会误触下一句，连锁着把好几句
    // 都当场看了答案。留在原地，用户自己决定什么时候滚下去、点进下一句的输入框。
    if (i >= 0 && i + 1 < cards.length) {
      cards[i + 1]._dictate.setState("active");
    }
  }

  // 每个小题解锁第一句为 active，其余保持 locked——只跑一次，不随模式来回切换重置进度
  document.querySelectorAll(".question-block").forEach(function(block) {
    var cards = Array.from(block.querySelectorAll(".seg-card")).filter(function(c) { return c._dictate; });
    if (cards.length) cards[0]._dictate.setState("active");
  });

  // ---- 填空：从 seg-notes 里第一个「…」抓语法点原文，在句子里定位到对应的
  //      .tw 词（挖空按词级 token 对齐，不做字符级切割），挖空成一个输入框 ----
  function baseTokens(segJa) {
    var tokens = [], offset = 0;
    Array.from(segJa.childNodes).forEach(function(node) {
      if (node.nodeType === 3) {
        var t = node.textContent;
        if (t) { tokens.push({ start: offset, end: offset + t.length, node: node, text: t }); offset += t.length; }
      } else if (node.nodeType === 1) {
        if (node.tagName === "BR") { tokens.push({ start: offset, end: offset + 1, node: node, text: "\n" }); offset += 1; return; }
        if (node.classList.contains("tw")) {
          var txt = plainTextOf(node);
          tokens.push({ start: offset, end: offset + txt.length, node: node, text: txt });
          offset += txt.length;
        }
      }
    });
    return tokens;
  }

  function extractGrammarQuery(notesText) {
    var m = notesText.match(/「([^」]+)」/);
    if (!m) return null;
    var q = m[1].replace(/^[~〜]+/, "").replace(/[^\p{L}\p{N}ー々]+$/u, "");
    return q.length >= 2 ? q : null;
  }

  function findBlankRange(plain, query) {
    for (var len = query.length; len >= 2; len--) {
      var idx = plain.indexOf(query.slice(0, len));
      if (idx !== -1) return { start: idx, end: idx + len };
    }
    return null;
  }

  document.querySelectorAll(".seg-card").forEach(function(card) {
    var segJa = card.querySelector(".seg-ja");
    var notes = card.querySelector(".seg-notes");
    if (!segJa || !notes) return;
    var query = extractGrammarQuery(notes.textContent);
    if (!query) return;
    var tokens = baseTokens(segJa);
    var plain = tokens.map(function(t) { return t.text; }).join("");
    var range = findBlankRange(plain, query);
    if (!range) return;

    // 在原文的克隆上动手（不碰真正的 .seg-ja，跟读高亮/切模式回退都还是原样）
    var clone = segJa.cloneNode(true);
    clone.className = "seg-ja-blank";
    var cloneTokens = baseTokens(clone);
    var overlapping = cloneTokens.filter(function(t) { return t.start < range.end && t.end > range.start; });
    if (!overlapping.length) return;
    var answer = overlapping.map(function(t) { return t.text; }).join("");

    var input = document.createElement("input");
    input.type = "text";
    input.className = "blank-input";
    input.autocomplete = "off";
    input.dataset.answer = answer;
    input.style.width = (answer.length * 1.4 + 1.2) + "em";
    var parent = overlapping[0].node.parentNode;
    parent.insertBefore(input, overlapping[0].node);
    overlapping.forEach(function(t) { if (t.node.parentNode) t.node.parentNode.removeChild(t.node); });
    input.addEventListener("click", function(e) { e.stopPropagation(); });
    input.addEventListener("keydown", function(e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      var ok = input.value.trim() === input.dataset.answer;
      input.classList.toggle("ok", ok);
      input.classList.toggle("ng", !ok);
      if (ok) card.classList.add("blank-revealed");
    });

    segJa.insertAdjacentElement("afterend", clone);
    card.classList.add("has-blank");
  });
})();

// ── 单词测试 tab：填空题／听音频写假名／中文写假名／日文写中文，四类题目每次
//    都全做一遍（不抽样），错题次数记本地存储，下次优先做之前错过的 ──
// 数据来自 build_vocab_quiz_data.py 生成、build_page.py 内嵌的 <script
// id="vocab-quiz-data">；没有这个 tab 的页面（没传 --quiz-json 生成的）这段
// 直接整体跳过，不影响任何现有听力页。
(function() {
  var dataEl = document.getElementById("vocab-quiz-data");
  if (!dataEl) return;
  var words = JSON.parse(dataEl.textContent);

  var ERROR_KEY = "n2listen-quiz-errors:" + location.pathname;
  var errors = {};
  try { errors = JSON.parse(localStorage.getItem(ERROR_KEY) || "{}"); } catch (e) { errors = {}; }

  function errKey(wordId, type) { return wordId + ":" + type; }
  function getErr(k) { return errors[k] || 0; }
  function bumpErr(k) {
    errors[k] = getErr(k) + 1;
    localStorage.setItem(ERROR_KEY, JSON.stringify(errors));
  }

  var TYPES = ["blank", "audio2kana", "zh2kana", "ja2zh"];
  var TYPE_LABELS = {
    blank: "填空题", audio2kana: "听音频写假名",
    zh2kana: "根据中文写假名", ja2zh: "根据单词写中文意思"
  };
  var KANJI_RE = /[一-鿿]/;
  // 词性标签（"[名]"「[动3]」之类）是词典抄来的，不算释义内容，判分前先去掉，
  // 不然用户如果照抄了词性标签会误判、如果没抄也不该因为"少打了标签"算错。
  var POS_RE = /^\s*[「『\[［【]{1}[^\]」』］】]*[\]」』］】]\s*/;

  function audioSrcFor(word) {
    var id = String(word.id);
    while (id.length < 3) id = "0" + id;
    return "audio/seg-" + id + ".mp3";
  }

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  // 队列：每个词 × 4 种题型，全量不抽样；按"这道题之前错过几次"降序排列，之前
  // 错得越多排越前。同错误次数的题目顺序要随机——先整体洗牌一次，再用稳定
  // 排序按错误次数分组，稳定排序不会打乱同错误次数题目之间的相对顺序，也就
  // 是洗牌后的随机顺序（不这么做的话，同一个词的4种题型会挨在一起连续出现，
  // 因为一开始所有词的错误次数都是0，稳定排序会原样保留"逐词展开"时的插入
  // 顺序）。
  function buildQueue() {
    var q = [];
    words.forEach(function(w) {
      TYPES.forEach(function(t) { q.push({ word: w, type: t }); });
    });
    shuffle(q);
    q.sort(function(a, b) {
      return getErr(errKey(b.word.id, b.type)) - getErr(errKey(a.word.id, a.type));
    });
    return q;
  }
  var queue = buildQueue();

  var qi = 0;
  var resolved = false;      // 这道题是否已经判完（正确或已看答案），控制按钮显隐
  var countedWrong = false;  // 这道题这一轮是否已经计过一次错，避免反复提交同一道题重复累加

  var quizProgress = document.getElementById("quizProgress");
  var quizCard = document.getElementById("quizCard");
  var quizDone = document.getElementById("quizDone");
  var quizTypeLabel = document.getElementById("quizTypeLabel");
  var quizPrompt = document.getElementById("quizPrompt");
  var quizPlayBtn = document.getElementById("quizPlayBtn");
  var quizInput = document.getElementById("quizInput");
  var quizCheck = document.getElementById("quizCheck");
  var quizReveal = document.getElementById("quizReveal");
  var quizNext = document.getElementById("quizNext");
  var quizStatus = document.getElementById("quizStatus");
  var quizResetErrors = document.getElementById("quizResetErrors");
  var quizAudio = new Audio();

  [quizInput, quizCheck, quizReveal, quizNext, quizPlayBtn, quizResetErrors].forEach(function(el) {
    el.addEventListener("click", function(e) { e.stopPropagation(); });
  });

  function answerFor(q) {
    if (q.type === "blank") return q.word.blank;
    if (q.type === "audio2kana" || q.type === "zh2kana") return q.word.kana;
    return null; // ja2zh 是多选一匹配，见 checkJa2Zh
  }

  function zhSegments(zh) {
    return zh.replace(POS_RE, "").split(/[,，、;；]/).map(function(s) { return s.trim(); }).filter(Boolean);
  }

  function checkAnswer(q, raw) {
    var v = raw.trim();
    if (q.type === "ja2zh") return zhSegments(q.word.zh).indexOf(v) !== -1;
    return v === answerFor(q);
  }

  function render() {
    if (qi >= queue.length) {
      quizCard.style.display = "none";
      quizDone.style.display = "block";
      quizProgress.textContent = queue.length + " / " + queue.length;
      return;
    }
    quizCard.style.display = "";
    quizDone.style.display = "none";
    quizProgress.textContent = (qi + 1) + " / " + queue.length;

    var q = queue[qi];
    resolved = false;
    countedWrong = false;
    quizTypeLabel.textContent = TYPE_LABELS[q.type];
    quizInput.value = "";
    quizInput.disabled = false;
    quizStatus.textContent = "";
    quizStatus.className = "quiz-status";
    quizCheck.style.display = "";
    quizReveal.style.display = "";
    quizNext.style.display = "none";
    quizPlayBtn.style.display = "none";

    if (q.type === "blank") {
      var idx = q.word.sentence.indexOf(q.word.blank);
      var blanked = idx === -1 ? q.word.sentence
        : q.word.sentence.slice(0, idx) + "____" + q.word.sentence.slice(idx + q.word.blank.length);
      quizPrompt.innerHTML = '<div class="quiz-ja">' + blanked + '</div>' +
        '<div class="quiz-zh-hint">' + q.word.sentence_zh + '</div>';
    } else if (q.type === "audio2kana") {
      quizPrompt.innerHTML = '<div class="quiz-hint-text">听发音，写出假名</div>';
      quizPlayBtn.style.display = "";
      quizAudio.src = audioSrcFor(q.word);
    } else if (q.type === "zh2kana") {
      quizPrompt.innerHTML = '<div class="quiz-zh-prompt">' + q.word.zh + '</div>';
    } else {
      var shown = KANJI_RE.test(q.word.text) && q.word.kana && q.word.kana !== q.word.text
        ? q.word.text + "（" + q.word.kana + "）" : q.word.text;
      quizPrompt.innerHTML = '<div class="quiz-ja-prompt">' + shown + '</div>';
    }
    quizInput.focus();
  }

  function markResolved(correct, revealedAnswer) {
    resolved = true;
    quizInput.disabled = true;
    quizCheck.style.display = "none";
    quizReveal.style.display = "none";
    quizNext.style.display = "";
    if (correct) {
      quizStatus.textContent = "✓ 正解！";
      quizStatus.className = "quiz-status ok";
    } else {
      quizStatus.textContent = "👁 答案：" + revealedAnswer;
      quizStatus.className = "quiz-status rev";
    }
  }

  function doCheck() {
    if (resolved) return;
    var q = queue[qi];
    var ok = checkAnswer(q, quizInput.value);
    if (ok) {
      markResolved(true, null);
    } else {
      if (!countedWrong) { bumpErr(errKey(q.word.id, q.type)); countedWrong = true; }
      quizStatus.textContent = "✗ 不对，再检查一下";
      quizStatus.className = "quiz-status ng";
    }
  }

  function doReveal() {
    if (resolved) return;
    var q = queue[qi];
    if (!countedWrong) { bumpErr(errKey(q.word.id, q.type)); countedWrong = true; }
    var ans = q.type === "ja2zh" ? q.word.zh.replace(POS_RE, "") : answerFor(q);
    markResolved(false, ans);
  }

  quizCheck.addEventListener("click", doCheck);
  quizReveal.addEventListener("click", doReveal);
  quizInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") { e.preventDefault(); doCheck(); }
  });
  quizNext.addEventListener("click", function() { qi++; render(); });
  quizPlayBtn.addEventListener("click", function() { quizAudio.currentTime = 0; quizAudio.play(); });
  quizResetErrors.addEventListener("click", function() {
    errors = {};
    localStorage.setItem(ERROR_KEY, JSON.stringify(errors));
    queue = buildQueue();
    qi = 0;
    render();
  });

  render();
})();
