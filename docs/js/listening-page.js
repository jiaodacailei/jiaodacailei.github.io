// 日语听力精听页共享脚本（tools/listening/build_page.py 生成的所有页面都用这一份）。
// 密码哈希是每个页面独有的数据，不能写死在这份共享文件里——从 #gate 的 data-hash
// 属性读，build_page.py 生成 HTML 时把哈希写进那个属性。
(function() {
  var HASH = document.getElementById("gate").dataset.hash;
  async function sha256(str) {
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function afterUnlock() {
    document.getElementById("gate").style.display = "none";
    document.getElementById("content").style.display = "block";
  }
  async function tryUnlock(pwd) {
    var h = await sha256(pwd);
    if (h === HASH) {
      afterUnlock();
      sessionStorage.setItem("unlocked-" + location.pathname, "1");
    } else {
      document.getElementById("pwdErr").textContent = "パスワードが違います";
    }
  }
  if (sessionStorage.getItem("unlocked-" + location.pathname) === "1") {
    afterUnlock();
  }
  document.getElementById("pwdBtn").addEventListener("click", function() {
    tryUnlock(document.getElementById("pwdInput").value);
  });
  document.getElementById("pwdInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") tryUnlock(this.value);
  });
})();

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
