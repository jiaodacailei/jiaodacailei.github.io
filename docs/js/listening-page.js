// 日语听力精听页共享脚本（tools/listening/build_page.py 生成的所有页面都用这一份）。
// 密码门逻辑不在这份文件里——那是所有私有页面（不只是听力页）通用的一段，抽到
// private-gate.js 了，页面里在这份文件之前先引入那个。

// 播放/暂停图标（SVG，取自 Material Design，跟 build_page.py 里静态 HTML 用的是
// 同一份路径）——这两个是播放中动态切换用的，其它图标（设置齿轮/循环/关闭/上一个
// 下一个/最前最后）只在生成时渲染一次、不会运行时切换，留在 build_page.py 里当
// 静态 HTML 生成，不用在这份共享 JS 里重复一份。
var ICON_PLAY = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
var ICON_PAUSE = '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';

// ── 统一播放器：逐句 / 小题整体 / 大题整体都走同一套状态，
//    点标题/内容播放，配合右下角悬浮迷你播放器暂停/继续/上一个/下一个/最前/最后/循环/停止 ──
(function() {
  // navType: "sentence" | "question" | "mondai"；navSiblings 是同级兄弟节点数组（用于上一个/
  // 下一个/最前/最后导航，导航不跨级——句子不跨小题、小题不跨大题、大题就是顶层）；
  // loop 不随 playScope 重置，是迷你播放器里的全局开关，切换播放目标时保持原状态。
  // rangeStart/rangeEnd：选段复读模式下的播放范围（秒，相对当前 audio 自己
  // 的时间轴），非选段播放时都是 null——tickWordHighlight() 靠这两个字段
  // 判断要不要在到达终点时截断/循环回起点，见文件后面"选段复读"那一段。
  var player = {
    audios: [], idx: 0, loop: false, active: false, finished: false, scopeLabel: "",
    navType: null, navSiblings: [], navIndex: -1,
    rangeStart: null, rangeEnd: null
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
    // 选段复读：到达范围终点——循环开着就跳回起点接着放，没开循环就停在终点，
    // 不往下播这句剩下的内容（这是跟"整句播放不循环时自然播完"最大的行为
    // 差异，见 playRange() 的注释）。rangeEnd 为 null 表示选中的终点已经是
    // 这句最后一个词，没有"下一个词的 t"可用，退化成用这条音频自己的总时长
    // 当终点——duration 要等浏览器加载完元数据才有值，播放开始后几乎立刻
    // 就绪，加载完之前这里先不做截断判断，不影响观感（正常听感上不会卡在
    // 这一两帧的窗口期）。
    if (a && player.rangeStart !== null) {
      var effectiveEnd = player.rangeEnd !== null ? player.rangeEnd : a.duration;
      if (effectiveEnd && a.currentTime >= effectiveEnd) {
        if (player.loop) {
          a.currentTime = player.rangeStart;
        } else {
          // finishPlayer()（复用整句/整题播放"自然播完"那条路径，一并清掉
          // 卡片的 .playing 高亮，跟正常播放完的视觉表现保持一致）本身不会
          // 暂停音频——它设计给"onended 已经自然触发过、音频早就停了"的
          // 场景用，这里是自己主动检测到范围终点、音频其实还在播，要先
          // 手动暂停。
          a.pause();
          finishPlayer();
        }
      }
    }
    wordHighlightRAF = requestAnimationFrame(tickWordHighlight);
  }
  function startWordHighlight() {
    if (wordHighlightRAF === null) { wordHighlightRAF = requestAnimationFrame(tickWordHighlight); }
  }

  // 卡片是不是已经在"不被顶部 sticky-header / 底部悬浮播放器挡住"的可视区域内——
  // 连播一长串句子时，如果每一句都不管三七二十一地 scrollIntoView，画面会一直在
  // 平滑滚动动画中，用户这时候点别的句子卡片，点击坐标是按当前视觉位置算的，
  // 但内容正在动画滚动、真实位置随时在变，就会出现"点了没反应"或者"点好几次
  // 才点中"——不是点击逻辑本身的 bug，是不必要的滚动动画抢了点击的准头。
  function isCardVisible(card) {
    var r = card.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var topGuard = 70;   // sticky-header 实际高度约55px，留一点余量
    var bottomGuard = 90; // 悬浮迷你播放器实际高度约55px，留一点余量
    return r.top >= topGuard && r.bottom <= vh - bottomGuard;
  }

  // 当前正在播放的句子加高亮效果，只有卡片不在可视区域时才自动滚动——已经看
  // 得见就不打断，方便连播/跳转时跟着看，又不会因为动画滚动干扰点击。
  function setPlayingCard(audio) {
    document.querySelectorAll(".seg-card.playing").forEach(function(c) { c.classList.remove("playing"); });
    if (audio) {
      var card = audio.closest(".seg-card");
      if (card) {
        card.classList.add("playing");
        if (!isCardVisible(card)) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    }
  }

  function updateMiniPlayer() {
    // 悬浮设置按钮平时贴底显示，播放中迷你播放器出现时才需要让位上移，
    // 靠这个 body class（不是 miniPlayer 自己的 .active，那个只在悬浮播放器
    // 元素上，CSS 兄弟选择器够不到它前面的 .settings-toggle）驱动 CSS 联动。
    document.body.classList.toggle("mini-player-open", player.active);
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
  // 顺带清掉选段复读的范围状态——这是退出选段模式的唯一方式（clearRange
  // Selection 定义在文件后面"选段复读"那一段，函数声明会被提升到本闭包
  // 顶部，这里调用在定义之前没问题）。
  function stopPlayer() {
    player.audios.forEach(function(a) { a.onended = null; a.pause(); });
    player.active = false;
    player.finished = false;
    player.audios = [];
    player.rangeStart = null;
    player.rangeEnd = null;
    clearRangeSelection();
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
    // 正常整句/整题/整大题播放跟选段复读互斥——切到这边来的话，之前如果
    // 还留着选段的范围状态/卡片上的选中样式，要一并清掉，不然 tickWord
    // Highlight() 会拿旧范围去截断这次的正常播放。
    player.rangeStart = null;
    player.rangeEnd = null;
    clearRangeSelection();
    playNext();
  }

  // 选段复读：只播一句音频里 [startT, endT) 这一段，循环开着就在到达 endT
  // 时跳回 startT 继续放（边界检测在 tickWordHighlight() 里，跟跟读高亮
  // 用的是同一个 RAF 循环，不需要另外起一个定时器）。跟 playScope() 的
  // "从头到尾依次播完一串 <audio>"形状不一样（只有一个 audio、只播中间
  // 一段），所以单独开一个入口，不往 playScope() 里硬塞参数。
  function playRange(audio, startT, endT, label) {
    player.audios.forEach(function(a) { a.onended = null; a.pause(); });
    player.audios = [audio];
    player.idx = 0;
    player.finished = false;
    player.scopeLabel = label;
    player.navType = null;   // 没有同级兄弟节点，导航按钮在 updateMiniPlayer() 里自动禁用
    player.navSiblings = [];
    player.navIndex = -1;
    player.rangeStart = startT;
    player.rangeEnd = endT;
    player.active = true;
    audio.currentTime = startT;
    audio.onended = null;    // 选段模式不依赖 onended 判断"播完"，靠 tickWordHighlight() 的范围检测
    audio.play();
    setPlayingCard(audio);
    updateMiniPlayer();
    startWordHighlight();
  }

  mpPlayPause.addEventListener("click", function() {
    if (!player.active) return;
    if (player.finished) {
      player.finished = false;
      // 选段复读播完停在终点（没开循环）时，"再播一次"要回到选段的起点
      // 重新放，不能走下面 playNext() 那条路——那个是给"依次播完一串
      // <audio>"设计的，会把 currentTime 强制归零（回到整条音频最开头，
      // 不是选段的起点）、还会重新挂上"播完自动接下一条"的 onended，两个
      // 都不是选段模式想要的行为。
      if (player.rangeStart !== null) {
        var a = player.audios[player.idx];
        a.currentTime = player.rangeStart;
        a.play();
        setPlayingCard(a);
        updateMiniPlayer();
        startWordHighlight();
        return;
      }
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

  // ── 选段复读：跟读模式下选中一句话里连续的一段词，单独循环播放这一段 ──
  // 只在带跟读时间戳（.tw[data-t]，来自会话/课文句子的 char_times）的卡片
  // 上出现——生词条目没有逐词时间戳，天然不会有任何 .tw[data-t]，图标不会
  // 被插入，不用额外传参区分。默认关闭（body 不带 repeat-mode-on 类时图标
  // 整体 CSS 隐藏），设置面板里的开关打开才显示，避免平时跟读模式下卡片
  // 右下角多一个不相关的图标。
  var selectingCard = null, selectStart = null;

  // 去掉假名注音（<rt>）之后的原文纯文本——跟默写/填空模块里同名函数逻辑
  // 完全一样，但那份定义在文件后面另一个独立的 IIFE 里，闭包作用域够不到，
  // 这里单独放一份（选段复读的播放条标题文字要用，只取 <ruby> 的 base 部分，
  // 不要把假名读音也拼进去）。
  function plainTextOf(node) {
    var clone = node.cloneNode(true);
    Array.from(clone.querySelectorAll("rt")).forEach(function(rt) { rt.remove(); });
    return clone.textContent;
  }

  // 退出选段模式的入口都要清这份状态——stopPlayer()（点✕/切Tab/播完后点了
  // 别处）、playScope()（切去正常整句/整题播放）都已经在调用这个函数。
  function clearRangeSelection() {
    selectingCard = null;
    selectStart = null;
    document.querySelectorAll(".seg-card.seg-selecting").forEach(function(c) {
      c.classList.remove("seg-selecting");
    });
    document.querySelectorAll(".tw.seg-range-pending, .tw.seg-range-selected").forEach(function(w) {
      w.classList.remove("seg-range-pending", "seg-range-selected");
    });
  }

  var anyRepeatable = false;
  document.querySelectorAll(".seg-card").forEach(function(card) {
    var words = Array.from(card.querySelectorAll(".seg-ja .tw[data-t]"));
    if (!words.length) return;   // 生词条目/没有跟读时间戳的卡片不显示图标
    anyRepeatable = true;

    var icon = document.createElement("button");
    icon.type = "button";
    icon.className = "seg-repeat-icon";
    icon.title = "选段复读";
    icon.textContent = "🔁";
    icon.addEventListener("click", function(e) {
      e.stopPropagation();
      // 同一张卡片已经点了起点、还在等点终点——再点一次图标视为取消，退回
      // 中性状态，不重新进入选段中（要重新选，用户自己再点一次图标）。
      if (selectingCard === card && selectStart) {
        clearRangeSelection();
        return;
      }
      // 其它情况（中性状态点开始选、或者切到别的卡片重新选）：先彻底停掉
      // 当前播放/清空旧的选段状态，再进入这张卡片的"选段中"。
      stopPlayer();
      selectingCard = card;
      card.classList.add("seg-selecting");
    });
    card.appendChild(icon);

    words.forEach(function(w) {
      w.addEventListener("click", function(e) {
        if (selectingCard !== card) return;   // 不在选段中，交给卡片自己的点击逻辑正常整句播放
        e.stopPropagation();
        if (!selectStart) {
          selectStart = w;
          w.classList.add("seg-range-pending");
          return;
        }
        var startIdx = words.indexOf(selectStart);
        var endIdx = words.indexOf(w);
        if (startIdx > endIdx) { var tmp = startIdx; startIdx = endIdx; endIdx = tmp; }

        selectStart.classList.remove("seg-range-pending");
        for (var i = startIdx; i <= endIdx; i++) { words[i].classList.add("seg-range-selected"); }

        var startT = parseFloat(words[startIdx].getAttribute("data-t"));
        var endT = endIdx + 1 < words.length ? parseFloat(words[endIdx + 1].getAttribute("data-t")) : null;
        var label = words.slice(startIdx, endIdx + 1).map(function(x) { return plainTextOf(x); }).join("");
        if (label.length > 20) { label = label.slice(0, 20) + "…"; }

        card.classList.remove("seg-selecting");
        selectingCard = null;
        selectStart = null;

        var audio = card.querySelector("audio");
        playRange(audio, startT, endT, label);
      });
    });
  });

  // 设置面板开关——一整个页面都没有带跟读时间戳的卡片（比如纯生词表页面）
  // 时不显示这个开关，打开了也没有任何图标会出现，纯粹是无意义的按钮。
  // 默认关闭（localStorage 没记过就是关），跟编辑模式的开关是同一套持久化
  // 方式，但两个功能互不依赖，各自存各自的 key。
  if (anyRepeatable) {
    var repeatSettingsPanel = document.getElementById("settingsPanel");
    if (repeatSettingsPanel) {
      var REPEAT_MODE_KEY = "n2listen-repeat-mode";
      var repeatGroup = document.createElement("div");
      repeatGroup.className = "settings-group settings-group-repeatmode";
      repeatGroup.innerHTML =
        '<div class="settings-label">跟读练习</div>' +
        '<div class="settings-options">' +
          '<button class="settings-opt" id="repeatModeToggle">🔁 选段复读</button>' +
        "</div>";
      repeatSettingsPanel.appendChild(repeatGroup);

      var repeatToggleBtn = repeatGroup.querySelector("#repeatModeToggle");
      function setRepeatMode(on) {
        document.body.classList.toggle("repeat-mode-on", on);
        repeatToggleBtn.classList.toggle("active", on);
        localStorage.setItem(REPEAT_MODE_KEY, on ? "1" : "");
        if (!on) clearRangeSelection();
      }
      setRepeatMode(localStorage.getItem(REPEAT_MODE_KEY) === "1");
      repeatToggleBtn.addEventListener("click", function() {
        setRepeatMode(!document.body.classList.contains("repeat-mode-on"));
      });
    }
  }
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
    var sections = document.querySelectorAll('.mondai-section[data-scope="mondai"]');
    sections.forEach(function(sec, i) {
      sec.classList.toggle("tab-active", i === idx);
    });
    // 单词测试 tab 是单卡片互动出题，没有"小题"可跳转，也不需要跟读速度/显示
    // 模式/默写填空这些跟句子卡片相关的设置——用这个 body class 联动隐藏悬浮
    // 目录和设置面板里不相关的选项组（是否是这个 tab 靠"里面有没有单词测试的
    // 数据 script 标签"判断，不用在 build_page.py 里为此专门加一个新 class）。
    document.body.classList.toggle("quiz-tab-active", !!(sections[idx] && sections[idx].querySelector("#vocab-quiz-data")));
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
    group.className = "settings-group settings-group-mode";
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
  // 全角数字/字母（０-９Ａ-Ｚａ-ｚ）跟半角（0-9A-Za-z）是同一个字符，但课本
  // 原文排版经常用全角（比如"テレビＣＭ"里的ＣＭ）、键盘打字自然是半角——
  // 判分前先统一转成半角，不然会出现"明明打对了，就因为全角/半角不一致
  // 被判错"的情况。全角形式（Unicode 全角字符区）到半角 ASCII 的码位偏移
  // 统一是 0xFEE0，数字/大写字母/小写字母都适用，不用分开写三次转换。
  function normalizeFullwidth(s) {
    return (s || "").replace(/[０-９Ａ-Ｚａ-ｚ]/g, function(ch) {
      return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0);
    });
  }
  function stripPunct(s) { return normalizeFullwidth(s).replace(PUNCT_RE, ""); }

  // 会话类课文原文常带"说话人：”前缀（比如"王：あのポスター…"）——默写时整句
  // 日语原文是隐藏的（连中文提示都只有翻译，不提示是谁说的），逼用户去猜说话人
  // 名字打不打得对没有意义（而且音频本身也不会念出"王："这三个字），正确答案
  // 比对前把这部分去掉，只要求听写实际说的台词。只在句首匹配"非空白/非冒号
  // 字符+冒号"，且第一个字符不能是数字——避免误伤"10:30に集合"这类句首就是
  // 时间写法的句子（时间前缀几乎总以数字开头，说话人名字不会）。
  var SPEAKER_LABEL_RE = /^([^\s：:\d][^\s：:]*)[：:]/;
  function stripSpeakerLabel(s) { return (s || "").replace(SPEAKER_LABEL_RE, ""); }

  // ---- 默写：逐句隐藏日语原文，常驻提示中文翻译，输入跟原文一致（忽略标点）
  //      才算过关，按小题（question-block）顺序解锁下一句；哪些句子已经过关
  //      记 localStorage，刷新页面不从头重来——跟单词测试的 completed 是
  //      同一个道理，card.id（形如"card-a48"）在整份页面里天然唯一，直接
  //      当 key 用，不用另外拼 errKey 那一套。 ----
  var DICTATE_DONE_KEY = "n2listen-dictate-done:" + location.pathname;
  var dictateDone = {};
  try { (JSON.parse(localStorage.getItem(DICTATE_DONE_KEY) || "[]")).forEach(function(id) { dictateDone[id] = 1; }); } catch (e) { dictateDone = {}; }
  function saveDictateDone() {
    localStorage.setItem(DICTATE_DONE_KEY, JSON.stringify(Object.keys(dictateDone)));
  }

  document.querySelectorAll(".seg-card").forEach(function(card) {
    var segJa = card.querySelector(".seg-ja");
    var segZh = card.querySelector(".seg-zh");
    if (!segJa) return;
    var answer = stripSpeakerLabel(plainTextOf(segJa));
    var answerStripped = stripPunct(answer);

    var ui = document.createElement("div");
    ui.className = "dictate-ui";
    ui.innerHTML =
      '<div class="dictate-hint"></div>' +
      '<div class="dictate-row">' +
        '<textarea class="dictate-input" rows="2" autocomplete="off" placeholder="听写这一句的日语…"></textarea>' +
        '<button type="button" class="dictate-btn dictate-check">確認</button>' +
      '</div>' +
      '<div class="dictate-status"></div>' +
      '<div class="dictate-answer"></div>' +
      '<div class="dictate-redo-row"><button type="button" class="dictate-btn dictate-redo">重新练习</button></div>' +
      '<button type="button" class="dictate-locked">▶ 点击开始听写</button>';
    segJa.insertAdjacentElement("afterend", ui);

    var input = ui.querySelector(".dictate-input");
    var checkBtn = ui.querySelector(".dictate-check");
    var status = ui.querySelector(".dictate-status");
    var answerBox = ui.querySelector(".dictate-answer");
    var redoBtn = ui.querySelector(".dictate-redo");
    var lockedBtn = ui.querySelector(".dictate-locked");
    var hintBox = ui.querySelector(".dictate-hint");
    if (segZh) hintBox.textContent = segZh.textContent;
    // 只挡输入框/按钮的点击（避免每次点它们都触发外层 .seg-card 的"点击播放"），
    // 提示区/空白处仍然能点击播放——不整体 stopPropagation。
    [input, checkBtn, redoBtn, lockedBtn].forEach(function(el) {
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

    // 判对之后的展示逻辑单独拆出来，重新打开页面恢复已完成的句子时也要用
    // 同一套（不然恢复出来的样子跟当场刚答对时不一致）。
    function renderDone() {
      answerBox.innerHTML = '<span class="dictate-badge ok">✓ 正解</span> ' + segJa.innerHTML;
      status.textContent = "";
      status.className = "dictate-status";
      ui.classList.remove("revealed");
      setState("done");
    }
    card._dictate.renderDone = renderDone;
    if (dictateDone[card.id]) renderDone();

    // 默写没有"查看答案"按钮——提交后不对，直接把正确答案显示出来，但不算
    // 过关、不解锁下一句，必须用户自己把输入框改成跟答案一致再提交一次才能
    // 前进（跟单词测试"不管对错都显示答案+自动倒计时前进"的逻辑不是一回事，
    // 默写就是要逼着用户改到对为止，不能靠等自动跳过）。
    function check() {
      if (card._dictate.state === "done") return;
      var matched = stripPunct(input.value) === answerStripped;
      if (matched) {
        renderDone();
        dictateDone[card.id] = 1;
        saveDictateDone();
        advance(card);
      } else {
        answerBox.innerHTML = '<span class="dictate-badge wrong">✗ 答案</span> ' + segJa.innerHTML;
        ui.classList.add("revealed");
        status.textContent = "跟上面的答案对一下，改好之后重新提交";
        status.className = "dictate-status ng";
      }
    }
    checkBtn.addEventListener("click", check);
    input.addEventListener("keydown", function(e) {
      if (e.key === "Enter") { e.preventDefault(); check(); }
    });

    // 已经过关的句子想重复练习——只是把这一句重新切回"作答中"，不影响它
    // 已经记进 localStorage 的过关状态（不需要真的答对第二次才能继续解锁
    // 后面的句子），也不影响其它句子的进度，纯粹是这一句自己的"再练一次"。
    redoBtn.addEventListener("click", function() {
      input.value = "";
      status.textContent = "";
      status.className = "dictate-status";
      ui.classList.remove("revealed");
      setState("active");
      input.focus();
    });

    // 不限制顺序——任何一句还锁着的卡片都能直接点开开始练习，不用先做完
    // 前面的句子。跟 redoBtn 一样只切状态，不自动 focus/scroll（同样是为了
    // 避免连续点击误触下一个元素）。
    lockedBtn.addEventListener("click", function() {
      setState("active");
      input.focus();
    });

    // 给"清除默写进度"整体重置用——跟 redoBtn 几乎一样，但目标状态是
    // "locked"（回到初始未开始，不是"active"继续这一句），给全局清除按钮
    // 调用，不暴露给单句自己的 UI（单句重来用 redoBtn 就够）。
    card._dictate.reset = function() {
      input.value = "";
      status.textContent = "";
      status.className = "dictate-status";
      ui.classList.remove("revealed");
      setState("locked");
    };
  });

  function advance(card) {
    var block = card.closest(".question-block");
    if (!block) return;
    var cards = Array.from(block.querySelectorAll(".seg-card")).filter(function(c) { return c._dictate; });
    var i = cards.indexOf(card);
    // 只在原地解锁下一句，不自动聚焦/自动滚动——之前 focus()+scrollIntoView 会把视口
    // 拉到下一句，如果下一句的"確認"按钮刚好滚到跟当前点击位置同一个坐标，用户紧
    // 接着的第二次点击（哪怕只是手抖多点一下）就会误触下一句，连锁着把好几句都
    // 当场看了答案。留在原地，用户自己决定什么时候滚下去、点进下一句的输入框。
    // 只在下一句还是"locked"时才自动解锁——用户可能已经跳着练习把下一句
    // 提前做完了（active 甚至 done），这时不能覆盖它的状态，否则会把已经
    // 做完的句子重新打回"作答中"、白白抹掉刚记的 ✓ 正解。
    if (i >= 0 && i + 1 < cards.length && cards[i + 1]._dictate.state === "locked") {
      cards[i + 1]._dictate.setState("active");
    }
  }

  // 不再自动解锁"第一句还没过关的"——所有句子（包括第一句）默认都收起，
  // 只显示中文提示，用户点哪句就练哪句。已过关的句子在上面 forEach 里
  // 已经各自 renderDone() 恢复成 done，其余的都保持 setState("locked") 时
  // 的初始状态，不用在这里再处理。

  // ---- 填空：挖哪几个空、正确答案是什么，来自每张卡片自己的 data-blanks
  //      （build_page.py 按 `blanks` 字段生成，比如 ["映画にしても音楽にしても"]，
  //      内容作者显式指定的这句原文里的真实子串），在句子里定位到对应的
  //      .tw 词（挖空按词级 token 对齐，不做字符级切割），挖空成一个输入框。
  //      以前是从 seg-notes 文字里用正则猜「…」引号内容当挖空目标，猜不准
  //      两类场景：notes 写抽象占位字母（"AでもBでも"，句子里根本没有这几个
  //      字母）、notes 引用词典型但句子里是活用形（"とんでもない" vs 实际的
  //      "とんでもありません"）——猜错了没有任何报错，只有打开填空模式点开
  //      才会发现，而且改起来还得先读懂正则猜测逻辑才知道该往 notes 里塞
  //      什么样的文字才能猜对。现在 `blanks` 由内容作者直接看着句子原文写，
  //      要挖哪段就写哪段，前端不用猜，也没有猜错的可能——`data-blanks` 里
  //      随便打错一个字，唯一后果就是这个空找不到位置、被跳过，不会误挖到
  //      不该挖的地方。 ----
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

  // 哪些空已经提交过（对/错都算"提交过"）记 localStorage，刷新页面恢复成
  // 提交时的样子（对错状态+正确答案），不用重新做一遍——值存的是对/错
  // （true/false），不是用户当时打的原文，恢复时统一直接显示正确答案就
  // 够了（打对了本来就等于正确答案，打错了揭示出来的也是正确答案，没必要
  // 单独记一份用户当时的错误输入）。
  var BLANK_DONE_KEY = "n2listen-blank-done:" + location.pathname;
  var blankDone = {};
  try { blankDone = JSON.parse(localStorage.getItem(BLANK_DONE_KEY) || "{}"); } catch (e) { blankDone = {}; }
  function saveBlankDone() {
    localStorage.setItem(BLANK_DONE_KEY, JSON.stringify(blankDone));
  }

  document.querySelectorAll(".seg-card").forEach(function(card) {
    var segJa = card.querySelector(".seg-ja");
    var notes = card.querySelector(".seg-notes");
    if (!segJa || !card.dataset.blanks) return;
    var blankTexts;
    try { blankTexts = JSON.parse(card.dataset.blanks); } catch (e) { blankTexts = null; }
    if (!blankTexts || !blankTexts.length) return;

    // 在原文的克隆上动手（不碰真正的 .seg-ja，跟读高亮/切模式回退都还是原样）
    var clone = segJa.cloneNode(true);
    clone.className = "seg-ja-blank";
    var cloneTokens = baseTokens(clone);
    var plain = cloneTokens.map(function(t) { return t.text; }).join("");

    var ranges = [];
    // searchFrom 只往前推进，不用每条都从头 plain.indexOf(text)——同一段文字
    // 在句子里出现不止一次时（比如"AでもBでも"两个"でも"都要单独挖空），从
    // 头找每次都会命中同一个最靠前的位置，导致后一条被当成"跟前一条重叠"
    // 在下面的去重步骤里静默吃掉，那个空实际上永远不会出现。要求 blanks
    // 数组按它们在原文里从左到右出现的顺序书写（正常写法本来就是这样）。
    var searchFrom = 0;
    blankTexts.forEach(function(text) {
      var idx = plain.indexOf(text, searchFrom);
      if (idx === -1) {
        // data-blanks 里的文字在这句原文里找不到——多半是内容作者打字打错了
        // （或者句子后来改过、blanks 没跟着更新，或者这一条排在了它在原文
        // 里实际位置的后一条前面），控制台报警方便定位，不静默跳过导致
        // "这个空莫名其妙消失了"却没人知道为什么。
        console.warn("[填空] " + card.id + " 的 data-blanks 里 “" + text + "” 没有在原文中找到，检查数据是否有误");
        return;
      }
      ranges.push({ start: idx, end: idx + text.length });
      searchFrom = idx + text.length;
    });
    ranges.sort(function(a, b) { return a.start - b.start; });
    // 两个 blanks 条目意外圈到同一段文字时只保留先出现的那个，避免同一批
    // token 被挖空两次（第二次挖的时候 token 已经不在 DOM 里了）。这一步
    // 只挡得住"两个 range 字符范围本身重叠"的情况，挡不住"range 不重叠，
    // 但恰好都覆盖到同一个多字符 token 的一部分"这种——挖空是按整个 token
    // 挖的，不是按字符精确裁的，这种情况得在下面按 token 级别（而不是字符
    // 级别）去重，见 consumedNodes。
    ranges = ranges.filter(function(r, i) { return i === 0 || r.start >= ranges[i - 1].end; });
    if (!ranges.length) return;

    // 一句可能挖了不止一个空，但 seg-notes 往往是把这几个语法点写在同一段
    // 笔记里的（比如"「AでもBでも」表示…；「当たる」在此意为…"）——如果
    // 提交了第一个空就把 seg-notes 整段放出来，会连第二个空的答案一起提前
    // 剧透。要等这句所有空都提交过之后才放出 seg-notes，不能每提交一个空
    // 就检查一次单独放行。
    var blanksTotal = 0, blanksResolved = 0;
    function maybeRevealNotes() {
      if (blanksResolved >= blanksTotal) card.classList.add("blank-revealed");
    }
    // 给"清除填空进度"整体重置收集每个空自己的重置动作——每个空的
    // input/redoBtn/everResolved 都是下面 ranges.forEach 里各自的闭包变量，
    // 只能在定义的地方各自收一份重置函数，没法从外面直接够到。
    var blankResets = [];

    // token 粒度可能比语法点标注的原文粗——分词器有时会把一长串纯假名（比如
    // "があるというわけではないんですね"）粘成一个不可再分的 token，但语法
    // 点笔记只标了其中一小段（"というわけではない"）。挖空范围/正确答案都要
    // 按 range 精确裁切，不能把命中到的整个 token 一起挖空，不然要求用户打
    // 的"正确答案"会比语法点本身长一大截，用户对着 notes 打不出来。
    function isPlainToken(t) {
      return t.node.nodeType === 3 || (t.node.nodeType === 1 && !t.node.querySelector("ruby"));
    }
    var consumedNodes = [];
    ranges.forEach(function(range, blankIdx) {
      var overlapping = cloneTokens.filter(function(t) {
        return t.start < range.end && t.end > range.start && consumedNodes.indexOf(t.node) === -1;
      });
      if (!overlapping.length) return;
      consumedNodes = consumedNodes.concat(overlapping.map(function(t) { return t.node; }));
      var answer = overlapping.map(function(t) {
        var s = Math.max(t.start, range.start) - t.start;
        var e = Math.min(t.end, range.end) - t.start;
        return t.text.slice(s, e);
      }).join("");
      var blankId = card.id + ":" + blankIdx;
      blanksTotal++;

      var input = document.createElement("input");
      input.type = "text";
      input.className = "blank-input";
      input.autocomplete = "off";
      input.dataset.answer = answer;
      input.style.width = (answer.length * 1.4 + 1.2) + "em";
      var first = overlapping[0], last = overlapping[overlapping.length - 1];
      var parent = first.node.parentNode;
      // 首尾 token 如果比 range 宽、且是纯文本（没有 ruby 标注结构），劈开成
      // "不挖空的那一截照常保留"+"挖空的那一截换成输入框"，纯假名 token 直接
      // 切字符串就行；如果边界 token 带 ruby（汉字词，切开会破坏注音结构），
      // 这种少见情况退回整个 token 一起挖空的旧行为，不强行拆。
      if (first.start < range.start && isPlainToken(first)) {
        parent.insertBefore(document.createTextNode(first.text.slice(0, range.start - first.start)), first.node);
      }
      parent.insertBefore(input, first.node);
      if (last.end > range.end && isPlainToken(last)) {
        parent.insertBefore(document.createTextNode(last.text.slice(range.end - last.start)), last.node.nextSibling);
      }
      overlapping.forEach(function(t) { if (t.node.parentNode) t.node.parentNode.removeChild(t.node); });
      input.addEventListener("click", function(e) { e.stopPropagation(); });

      // 重做按钮——提交过之后（不管对错）才出现，点了把这个空重新切回可编辑，
      // 跟默写的"重新练习"一个道理：只是给用户一个重新做一遍的入口，不影响
      // 已经记进 localStorage 的过关状态、也不影响 seg-notes 的揭示状态
      // （notes 一旦因为"这句所有空都提交过"而放出来，就不会因为重做某一个
      // 空又重新藏回去——放出来的内容已经看到了，藏回去没有意义）。
      var redoBtn = document.createElement("button");
      redoBtn.type = "button";
      redoBtn.className = "blank-redo";
      redoBtn.textContent = "↻";
      redoBtn.title = "重新做这道题";
      redoBtn.addEventListener("click", function(e) {
        e.stopPropagation();
        input.disabled = false;
        input.value = "";
        input.classList.remove("ok", "ng");
        input.focus();
      });

      // 不管对错，提交后都直接给出正确答案，不要求改到对才能继续——这条
      // 特意跟单词测试的"不管对错都显示答案"保持一致，不是默写"必须改对"
      // 那一套（填空考的是语法点本身记没记住，不是靠反复重试硬凑答案）。
      // everResolved 只在"这次页面加载里，这个空第一次被 resolve()"时推进
      // blanksResolved/放出 notes——必须从 false 开始，不能按 blankDone
      // 是否已有记录来初始化：blanksResolved 是每次刷新页面都从 0 重新计的
      // 内存计数器，哪怕这个空之前已经在 localStorage 里记过，这次加载时
      // 用 blankDone 恢复状态那一次 resolve() 调用也必须真的执行一次
      // "+1"，不然 blanksResolved 永远数不到 blanksTotal、notes 也就永远
      // 放不出来（真实踩过：写成按 blankDone 初始化，导致刷新页面之后所有
      // 已完成的填空都不再显示 notes，即使这句所有空都做完了）。这个 flag
      // 真正要防的是"同一次页面加载里，用户重做之后再提交一次"不要重复计数，
      // 不是要跳过刷新页面后的首次恢复。
      var everResolved = false;
      function resolve(ok) {
        input.disabled = true;
        input.classList.toggle("ok", ok);
        input.classList.toggle("ng", !ok);
        if (!ok) input.value = answer;
        redoBtn.classList.add("shown");
        if (!everResolved) {
          everResolved = true;
          blanksResolved++;
          maybeRevealNotes();
        }
        blankDone[blankId] = ok;
        saveBlankDone();
      }
      input.addEventListener("keydown", function(e) {
        if (e.key !== "Enter" || input.disabled) return;
        e.preventDefault();
        resolve(input.value.trim() === answer);
      });
      input.parentNode.insertBefore(redoBtn, input.nextSibling);
      blankResets.push(function() {
        input.disabled = false;
        input.value = "";
        input.classList.remove("ok", "ng");
        redoBtn.classList.remove("shown");
        everResolved = false;
      });

      if (blankId in blankDone) {
        input.value = answer;
        resolve(blankDone[blankId]);
      }
    });
    if (!blanksTotal) return;

    segJa.insertAdjacentElement("afterend", clone);
    card.classList.add("has-blank");
    card._blank = {
      reset: function() {
        blankResets.forEach(function(fn) { fn(); });
        blanksResolved = 0;
        card.classList.remove("blank-revealed");
      }
    };
  });

  // ---- 设置面板：清除默写/填空进度——默写/填空各自独立一个按钮，只清
  //      对应模式自己的 localStorage 记录 + 把所有卡片打回初始未作答状态，
  //      不影响另一种模式、也不影响跟读/单词测试的进度。跟单词测试的
  //      "清除使用记录"是同一个设计思路，这里两个模式分开放（而不是共用
  //      一个"清除全部进度"），因为默写/填空是两件独立的事，用户可能只想
  //      重来其中一种。 ----
  if (settingsPanel) {
    var progressGroup = document.createElement("div");
    progressGroup.className = "settings-group settings-group-progress-reset";
    progressGroup.innerHTML =
      '<div class="settings-options">' +
        '<button type="button" class="settings-reset-btn" id="dictateProgressReset">清除默写进度</button>' +
        '<button type="button" class="settings-reset-btn" id="blankProgressReset">清除填空进度</button>' +
      '</div>';
    settingsPanel.appendChild(progressGroup);

    document.getElementById("dictateProgressReset").addEventListener("click", function() {
      dictateDone = {};
      localStorage.removeItem(DICTATE_DONE_KEY);
      document.querySelectorAll(".seg-card").forEach(function(card) {
        if (card._dictate) card._dictate.reset();
      });
    });
    document.getElementById("blankProgressReset").addEventListener("click", function() {
      blankDone = {};
      localStorage.removeItem(BLANK_DONE_KEY);
      document.querySelectorAll(".seg-card").forEach(function(card) {
        if (card._blank) card._blank.reset();
      });
    });
  }
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

  // 单词测试分"全部/会话相关/课文相关/其他"四个分类分别测试——分类来自
  // build_vocab_quiz_data.py 写进每个词条的 category 字段（"dialogue"/"text"/
  // "other"，直接复用人工核实过的"这个词真的出现在哪"的数据，不是拿词典
  // 基本型重新猜一遍）。没有 category 字段的旧数据（页面还没用新版脚本重新
  // 生成过）一律当"other"处理，不会报错也不会漏词。
  var CATEGORY_KEY = "n2listen-quiz-category:" + location.pathname;
  var CATEGORIES = [
    { key: "all", label: "全部" },
    { key: "dialogue", label: "会话相关" },
    { key: "text", label: "课文相关" },
    { key: "other", label: "其他单词" }
  ];
  var presentCategories = {};
  words.forEach(function(w) { presentCategories[w.category || "other"] = true; });
  // "全部"永远展示；具体分类只在这份数据里真的有对应词的时候才展示，避免
  // 点开一个空空如也的分类（比如某一课没有课文 tab，就不会有"课文相关"）。
  var availableCategories = CATEGORIES.filter(function(c) { return c.key === "all" || presentCategories[c.key]; });
  var category = localStorage.getItem(CATEGORY_KEY) || "all";
  if (category !== "all" && !presentCategories[category]) category = "all";

  function categoryWords() {
    if (category === "all") return words;
    return words.filter(function(w) { return (w.category || "other") === category; });
  }

  // 错题/进度/出题范围这三份状态都要按分类分开记——同一个页面里"会话相关"
  // 跟"课文相关"是两套独立的做题进度，不能共用一份 localStorage。key 里的
  // category 会随用户切分类实时变化，所以不能像 DELAY_KEY 那样在模块顶层
  // 算一次就定死，每次要用的时候都要重新拼。
  function stateKeys() {
    var suffix = ":" + location.pathname + ":" + category;
    return {
      error: "n2listen-quiz-errors" + suffix,
      progress: "n2listen-quiz-progress" + suffix,
      scope: "n2listen-quiz-scope" + suffix
    };
  }

  // 每个词的 id 理应是这份 quiz_data 里全局唯一、稳定不变的编号，但真实出过
  // bug（textbook-sjp-zg-l11：生词表 id 编号体系用错，事后修复重新发布后
  // 全部 144 个词的 id 整体平移了 35）——用户浏览器里旧的错题/进度记录是按
  // 旧 id 存的，页面更新后这些 key 对不上任何一个"现在真实存在的词"，变成
  // 无主的孤儿记录。`totalErrorCount()` 是直接累加 errors 对象里所有值，
  // 不会区分"这个 key 现在还对应哪个词"，孤儿记录会让错题数显示比"仅错题"
  // 队列里真实能筛出来的题目数更大（真实案例：显示"1 / 7(9)"，队列只有7道
  // 真实能匹配上的错题，但累计错误数被两条孤儿记录污染成了9）。
  var validWordIds = {};
  words.forEach(function(w) { validWordIds[w.id] = true; });

  // 清掉 errors/completed 里 key 对应的 wordId 已经不在当前词表里的孤儿
  // 记录——errKey 格式是 "wordId:type"，取冒号前的部分对比。清完立刻存回
  // localStorage，不是只在内存里筛一下，不然下次读到的还是带孤儿记录的
  // 旧数据、每次都要重新筛一遍。
  function pruneOrphans(obj, saveFn) {
    var changed = false;
    Object.keys(obj).forEach(function(key) {
      var wordId = key.slice(0, key.lastIndexOf(":"));
      if (!validWordIds[wordId]) {
        delete obj[key];
        changed = true;
      }
    });
    if (changed) saveFn();
    return changed;
  }

  var errors = {}, completed = {}, scope = "all";
  function loadCategoryState() {
    var k = stateKeys();
    try { errors = JSON.parse(localStorage.getItem(k.error) || "{}"); } catch (e) { errors = {}; }
    // 记录"这一轮已经做过（判对或已看答案）的题"，刷新页面时跳过这些，只接着
    // 做剩下的——不然每次刷新都从头重来一遍。等一轮全部做完（剩余为空）才
    // 清空，开始下一轮；"错题记录清零"按钮也会顺带清掉这份记录，视为完全重开。
    completed = {};
    try { (JSON.parse(localStorage.getItem(k.progress) || "[]")).forEach(function(key) { completed[key] = 1; }); } catch (e) { completed = {}; }
    // 出题范围："all"=四类题型全部都做，"wrong"=只做累计出过错的题（getErr>0）。
    scope = localStorage.getItem(k.scope) || "all";
    pruneOrphans(errors, function() { localStorage.setItem(k.error, JSON.stringify(errors)); });
    pruneOrphans(completed, function() { localStorage.setItem(k.progress, JSON.stringify(Object.keys(completed))); });
  }
  loadCategoryState();

  function errKey(wordId, type) { return wordId + ":" + type; }
  function getErr(k) { return errors[k] || 0; }
  function bumpErr(k) {
    errors[k] = getErr(k) + 1;
    localStorage.setItem(stateKeys().error, JSON.stringify(errors));
  }
  function saveProgress() {
    localStorage.setItem(stateKeys().progress, JSON.stringify(Object.keys(completed)));
  }
  function totalErrorCount() {
    return Object.keys(errors).reduce(function(sum, k) { return sum + errors[k]; }, 0);
  }
  function markDone(q) {
    completed[errKey(q.word.id, q.type)] = 1;
    saveProgress();
  }

  // 确认后自动跳下一题的等待秒数——是通用偏好（不跟具体某一课绑定），所以
  // key 不带 location.pathname，跟 SPEED_KEY/LANG_KEY/MODE_KEY 一样全站共用。
  var DELAY_KEY = "n2listen-quiz-delay";
  var advanceDelay = parseInt(localStorage.getItem(DELAY_KEY) || "3", 10);

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
  // 出题范围先筛一遍（all=全部，wrong=只留累计错过至少一次的），范围本身
  // 决定了"这一轮"的总题数，跟错误次数排序、round 完成后重开是两件独立的事，
  // 顺序不能反——先按范围筛，再在筛出来的这个子集里判断"是不是都做完了"。
  function scopedAllItems() {
    var all = [];
    categoryWords().forEach(function(w) {
      TYPES.forEach(function(t) {
        if (scope === "wrong" && getErr(errKey(w.id, t)) <= 0) return;
        all.push({ word: w, type: t });
      });
    });
    return all;
  }

  var TOTAL_THIS_ROUND = 0; // buildQueue() 每次都会重新算，跟着 scope/completed 变化

  function buildQueue() {
    var all = scopedAllItems();
    // 只留这一轮还没做过的；如果全都做过了（上一轮刚好在这里做完、或者
    // localStorage 里的记录跟当前生词表对不上了），当作新一轮重新开始，不
    // 留下"永远显示已完成"的死状态。"仅错题"范围下 all 本身就可能是空的
    // （还没积累出任何错题），这种情况不当"一轮做完了"处理，交给调用方
    // （render）显示"还没有错题"，不在这里瞎重置。
    var q = all.length ? all.filter(function(item) { return !completed[errKey(item.word.id, item.type)]; }) : [];
    if (all.length && !q.length) {
      completed = {};
      saveProgress();
      q = all;
    }
    shuffle(q);
    q.sort(function(a, b) {
      return getErr(errKey(b.word.id, b.type)) - getErr(errKey(a.word.id, a.type));
    });
    TOTAL_THIS_ROUND = all.length;
    return q;
  }
  var queue = buildQueue();

  var qi = 0;
  var resolved = false;      // 这道题是否已经判完（点过确认），控制按钮显隐
  var countedWrong = false;  // 这道题这一轮是否已经计过一次错，避免反复提交同一道题重复累加
  var autoAdvanceTimer = null; // 点确认后3秒自动跳下一题的计时器，手动点"次へ"或提前进新题要清掉，避免重复推进

  var quizApp = document.getElementById("quizApp");
  var quizProgress = document.getElementById("quizProgress");
  var quizCard = document.getElementById("quizCard");
  var quizDone = document.getElementById("quizDone");
  var quizTypeLabel = document.getElementById("quizTypeLabel");
  var quizPrompt = document.getElementById("quizPrompt");
  var quizPlayBtn = document.getElementById("quizPlayBtn");
  var quizInput = document.getElementById("quizInput");
  var quizCheck = document.getElementById("quizCheck");
  var quizNext = document.getElementById("quizNext");
  var quizStatus = document.getElementById("quizStatus");
  var quizResetErrors = document.getElementById("quizResetErrors");
  var quizAudio = new Audio();

  [quizInput, quizCheck, quizNext, quizPlayBtn, quizResetErrors].forEach(function(el) {
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
    // ja2zh（根据单词写中文意思）判分放宽成"包含"：只要某个可接受释义片段里
    // 包含用户输入的内容就算对，不要求逐字对齐——用户可能只打了释义的一部分
    // （比如"担心"打成"担"也算抓住了意思），严格相等对这种简答式题目太苛刻。
    if (q.type === "ja2zh") {
      return !!v && zhSegments(q.word.zh).some(function(seg) { return seg.indexOf(v) !== -1; });
    }
    return v === answerFor(q);
  }

  // 进度显示按"这一轮总题数"（TOTAL_THIS_ROUND，buildQueue() 里定，随 scope
  // 变化）算，不是按当次刷新后剩下的队列长度算——不然刷新恢复进度之后，进度
  // 条会从一个奇怪的小分母重新数起（比如剩 385 题就显示"1 / 385"），显得之前
  // 做过的全部作废了。
  function doneCountThisRound() { return TOTAL_THIS_ROUND - queue.length; }

  // 进度条格式："当前题号/本轮总题数(累计错误次数)"，括号里的错误数是红色——
  // 不是本轮的错误数，是从有记录以来累计的错误次数，点"清除使用记录"才清零。
  function progressHtml(current) {
    return current + " / " + TOTAL_THIS_ROUND +
      '<span class="quiz-progress-err">(' + totalErrorCount() + ')</span>';
  }

  // 判错之后立刻刷新括号里的错误数（不调用 render()，那会连题目状态一起重置）
  function refreshProgress() {
    if (qi >= queue.length) { quizProgress.innerHTML = progressHtml(TOTAL_THIS_ROUND); return; }
    quizProgress.innerHTML = progressHtml(doneCountThisRound() + qi + 1);
  }

  function render() {
    if (TOTAL_THIS_ROUND === 0) {
      // "仅错题"范围下，还没有任何累计错误——不是"这一轮做完了"，是压根没题可做
      quizCard.style.display = "none";
      quizDone.style.display = "block";
      quizDone.textContent = "还没有错题，切换到「全部题目」先做一遍积累错题吧";
      quizProgress.innerHTML = "0 / 0";
      return;
    }
    if (qi >= queue.length) {
      quizCard.style.display = "none";
      quizDone.style.display = "block";
      quizDone.textContent = "🎉 本轮全部完成！";
      quizProgress.innerHTML = progressHtml(TOTAL_THIS_ROUND);
      return;
    }
    quizCard.style.display = "";
    quizDone.style.display = "none";
    quizProgress.innerHTML = progressHtml(doneCountThisRound() + qi + 1);

    if (autoAdvanceTimer) { clearTimeout(autoAdvanceTimer); autoAdvanceTimer = null; }

    var q = queue[qi];
    resolved = false;
    countedWrong = false;
    quizTypeLabel.textContent = TYPE_LABELS[q.type];
    quizInput.value = "";
    quizInput.disabled = false;
    quizStatus.textContent = "";
    quizStatus.className = "quiz-status";
    quizCheck.style.display = "";
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

  // 点"確認"之后不管对错都立刻定死答案（不再要求额外点"答えを見る"才能看到
  // 正确答案）——正解也把标准答案带出来，方便用户核对自己的写法是否也算数
  // （比如 ja2zh 现在是"包含"判分，用户可能想知道完整释义是什么）。
  function markResolved(correct, revealedAnswer) {
    resolved = true;
    quizInput.disabled = true;
    quizCheck.style.display = "none";
    quizNext.style.display = "";
    if (correct) {
      quizStatus.textContent = "✓ 正解！　答案：" + revealedAnswer;
      quizStatus.className = "quiz-status ok";
    } else {
      quizStatus.textContent = "✗ 答案：" + revealedAnswer;
      quizStatus.className = "quiz-status rev";
    }
    // 等 advanceDelay 秒后自动跳下一题（设置面板可调1/2/3秒），手动点"次へ"
    // 会提前触发并清掉这个计时器，不会重复推进
    autoAdvanceTimer = setTimeout(function() {
      autoAdvanceTimer = null;
      qi++;
      render();
    }, advanceDelay * 1000);
  }

  function doCheck() {
    if (resolved) return;
    var q = queue[qi];
    var ok = checkAnswer(q, quizInput.value);
    if (!ok && !countedWrong) { bumpErr(errKey(q.word.id, q.type)); countedWrong = true; refreshProgress(); }
    markDone(q);
    var ans = q.type === "ja2zh" ? q.word.zh.replace(POS_RE, "") : answerFor(q);
    markResolved(ok, ans);
  }

  quizCheck.addEventListener("click", doCheck);
  quizInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") { e.preventDefault(); doCheck(); }
  });
  quizNext.addEventListener("click", function() { qi++; render(); });
  quizPlayBtn.addEventListener("click", function() { quizAudio.currentTime = 0; quizAudio.play(); });
  quizResetErrors.addEventListener("click", function() {
    errors = {};
    localStorage.setItem(stateKeys().error, JSON.stringify(errors));
    completed = {};
    saveProgress();
    queue = buildQueue();
    qi = 0;
    render();
  });

  // 分类选择条（全部/会话相关/课文相关/其他单词）——只有真的存在对应词的
  // 分类才会出现在 availableCategories 里，不足两个分类（比如这一课没有课文
  // tab、所有词都归"其他"）时不用渲染这排按钮，避免看起来像"有得选却选了
  // 也没变化"。放在答题卡片上方、跟"出题范围"这类藏在设置面板里的次要偏好
  // 区别开——选哪个分类是"测哪一批词"这种主要选择，要放在显眼位置。
  if (availableCategories.length > 1) {
    var categoryBar = document.createElement("div");
    categoryBar.className = "quiz-category-bar";
    categoryBar.innerHTML = availableCategories.map(function(c) {
      return '<button type="button" class="quiz-category-btn" data-category="' + c.key + '">' +
        c.label + '</button>';
    }).join("");
    quizApp.insertBefore(categoryBar, quizApp.firstChild);
    var categoryBtns = Array.from(categoryBar.querySelectorAll(".quiz-category-btn"));
    categoryBtns.forEach(function(b) {
      b.classList.toggle("active", b.dataset.category === category);
      b.addEventListener("click", function(e) {
        e.stopPropagation();
        if (b.dataset.category === category) return;
        category = b.dataset.category;
        localStorage.setItem(CATEGORY_KEY, category);
        categoryBtns.forEach(function(x) { x.classList.toggle("active", x === b); });
        loadCategoryState();
        scopeBtns.forEach(function(x) { x.classList.toggle("active", x.dataset.scope === scope); });
        queue = buildQueue();
        qi = 0;
        render();
      });
    });
  }

  // 出题范围（全部题目／仅错题）——设置面板里只在单词测试 tab 激活时才显示
  // 的那一组，跟播放速度/显示模式/练习模式那几组是互斥的（见 CSS 的
  // .settings-group-quizscope 规则），不用这个 tab 时完全不占地方。
  var settingsPanel = document.getElementById("settingsPanel");
  if (settingsPanel) {
    var scopeGroup = document.createElement("div");
    scopeGroup.className = "settings-group settings-group-quizscope";
    scopeGroup.innerHTML =
      '<div class="settings-label">出題範囲</div>' +
      '<div class="settings-options" id="quizScopeOptions">' +
        '<button class="settings-opt" data-scope="all">全部题目</button>' +
        '<button class="settings-opt" data-scope="wrong">仅错题</button>' +
      '</div>';
    settingsPanel.appendChild(scopeGroup);
    var scopeBtns = Array.from(scopeGroup.querySelectorAll(".settings-opt"));
    scopeBtns.forEach(function(b) {
      b.classList.toggle("active", b.dataset.scope === scope);
      b.addEventListener("click", function() {
        if (b.dataset.scope === scope) return;
        scope = b.dataset.scope;
        localStorage.setItem(stateKeys().scope, scope);
        scopeBtns.forEach(function(x) { x.classList.toggle("active", x === b); });
        queue = buildQueue();
        qi = 0;
        render();
      });
    });

    // 确认后自动跳下一题的等待秒数，同样只在单词测试 tab 激活时显示，跟
    // 出题范围共用 .settings-group-quizscope 的显隐规则。
    var delayGroup = document.createElement("div");
    delayGroup.className = "settings-group settings-group-quizscope";
    delayGroup.innerHTML =
      '<div class="settings-label">自動次へ（秒）</div>' +
      '<div class="settings-options" id="quizDelayOptions">' +
        '<button class="settings-opt" data-delay="1">1</button>' +
        '<button class="settings-opt" data-delay="2">2</button>' +
        '<button class="settings-opt" data-delay="3">3</button>' +
      '</div>';
    settingsPanel.appendChild(delayGroup);
    var delayBtns = Array.from(delayGroup.querySelectorAll(".settings-opt"));
    delayBtns.forEach(function(b) {
      b.classList.toggle("active", parseInt(b.dataset.delay, 10) === advanceDelay);
      b.addEventListener("click", function() {
        advanceDelay = parseInt(b.dataset.delay, 10);
        localStorage.setItem(DELAY_KEY, advanceDelay);
        delayBtns.forEach(function(x) { x.classList.toggle("active", x === b); });
      });
    });
  }

  render();
})();
