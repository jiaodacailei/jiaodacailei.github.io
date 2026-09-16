// 编辑模式——给 data-driven 听力页加一个"直接在页面上改内容"的入口，不用
// 手动去改 data.js。没有 window.LESSON_DATA（非 data-driven 页面）时整个
// 不做事，不影响任何其它页面。
//
// 设计上跟"点卡片播放音频""默写/填空各自的卡片内点击行为"完全不冲突——
// 编辑入口是每张卡片右上角常驻的一个小 ✎ 图标（默认 CSS 隐藏，开启编辑模式
// 才显示），点这个图标单独 stopPropagation，不会带着卡片一起触发播放；卡片
// 其它位置的点击行为（播放、默写解锁……）完全不受影响，这样跟读/默写/填空
// 任何模式下都能一边听音频校对一边编辑，不用先切回跟读模式。
//
// 编辑的是这句"内容字段"（speaker/speakerKana/tokens/zh/notes/blanks），
// 不包括 id/audio——这两个字段是结构性的（id 用来定位句子、跟 audio 文件名
// 是绑定的），编辑面板里特意不显示，避免手滑改了导致这句跟音频/跟读进度对
// 不上。
//
// 应用一条编辑：直接改 window.LESSON_DATA 里对应句子对象的字段（跟 data.js
// 里的对象是同一个引用，改了就是改了，不用另外维护一份"改过的数据"），同时
// 记一份到 localStorage（按页面路径区分），本地刷新/下次打开这页都能恢复出
// 编辑过的样子（见 edit-mode-restore.js）。导出就是把当前这份已经带着所有
// 编辑的 window.LESSON_DATA 整个序列化下载成新的 data.js，直接替换生成时的
// 那份文件即可。
(function () {
  var DATA = window.LESSON_DATA;
  if (!DATA) return;

  var EDIT_MODE_KEY = "n2listen-edit-mode";
  var PENDING_KEY = "n2listen-pending-edits:" + location.pathname;
  var EDITABLE_FIELDS = ["speaker", "speakerKana", "tokens", "zh", "notes", "blanks"];

  var byId = {};
  (DATA.tabs || []).forEach(function (tab) {
    tab.questions.forEach(function (q) {
      q.sentences.forEach(function (s) {
        byId[s.id] = s;
      });
    });
  });

  var pending;
  try {
    pending = JSON.parse(localStorage.getItem(PENDING_KEY) || "{}");
  } catch (e) {
    pending = {};
  }

  function savePending() {
    localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
    updatePendingCount();
  }

  function pickEditable(s) {
    var out = {};
    EDITABLE_FIELDS.forEach(function (k) { out[k] = s[k] === undefined ? null : s[k]; });
    return out;
  }

  // ---- 每张卡片加一个常驻但默认隐藏的 ✎ 图标（CSS 按 body.edit-mode 控制
  //      显示），点了打开编辑面板 ----
  document.querySelectorAll(".seg-card").forEach(function (card) {
    var idMatch = /^card-a(\d+)$/.exec(card.id);
    if (!idMatch) return;
    var cardId = idMatch[1];
    if (!byId[cardId]) return;

    var icon = document.createElement("button");
    icon.type = "button";
    icon.className = "seg-edit-icon";
    icon.title = "编辑这句";
    icon.textContent = "✎";
    if (pending[cardId]) icon.classList.add("has-pending");
    icon.addEventListener("click", function (e) {
      e.stopPropagation();
      openEditor(cardId, card, icon);
    });
    card.appendChild(icon);
  });

  // ---- 编辑面板（整份页面只建一个，反复复用，不用每张卡片各建一个） ----
  var overlay = document.createElement("div");
  overlay.className = "edit-modal-overlay";
  overlay.innerHTML =
    '<div class="edit-modal">' +
      '<div class="edit-modal-header">' +
        '<span id="editModalTitle"></span>' +
        '<button type="button" class="edit-modal-play" id="editModalPlay">▶ 播放</button>' +
      "</div>" +
      '<textarea class="edit-modal-textarea" id="editModalTextarea" spellcheck="false"></textarea>' +
      '<div class="edit-modal-error" id="editModalError"></div>' +
      '<div class="edit-modal-footer">' +
        '<button type="button" class="dictate-btn" id="editModalCancel">取消</button>' +
        '<button type="button" class="dictate-btn dictate-check" id="editModalApply">应用</button>' +
      "</div>" +
    "</div>";
  document.body.appendChild(overlay);

  var titleEl = overlay.querySelector("#editModalTitle");
  var playBtn = overlay.querySelector("#editModalPlay");
  var textarea = overlay.querySelector("#editModalTextarea");
  var errorEl = overlay.querySelector("#editModalError");
  var cancelBtn = overlay.querySelector("#editModalCancel");
  var applyBtn = overlay.querySelector("#editModalApply");
  var modal = overlay.querySelector(".edit-modal");
  var header = overlay.querySelector(".edit-modal-header");

  // ---- 弹框可拖动——真实反馈"编辑句子json数据的弹框，做成可移动"：弹框
  //      默认居中显示，但常常正好挡住这句在页面里的原始位置（跟读高亮/
  //      挖空效果要对着原文看），拖开一点方便对照。拖拽只认header（标题栏），
  //      不认"▶ 播放"按钮，不然点播放会被误判成拖拽起点。第一次拖拽时才把
  //      弹框从"overlay flex居中"切到"position:fixed + 具体像素位置"（用
  //      当时的 getBoundingClientRect() 保证视觉位置不跳），之后每次拖拽
  //      基于那份固定定位累加，直到下次刷新页面才恢复默认居中——同一个
  //      overlay 反复复用编辑不同句子，拖开的位置故意不重置，连续编辑多句
  //      时不用每次重新拖。 ----
  (function () {
    var dragging = false, startX, startY, startLeft, startTop;
    // move/up 监听挂在 document 上，不挂在 header 自己身上——header 只是
    // 顶部一条细长条，正常拖拽时鼠标只要稍微移动快一点、或者往下拖动的
    // 幅度大一点，指针立刻就会离开 header 的实际像素范围，挂在 header 上
    // 的 pointermove 从那一刻起就再也收不到事件，拖拽像是"卡住不动"——
    // 真实反馈"点击弹框标题，无法移动"。挂在 document 上就不依赖指针是否
    // 还悬停在 header 上，只要 dragging 标记为真，鼠标移到页面任何位置都
    // 能继续跟踪。
    header.addEventListener("pointerdown", function (e) {
      if (e.target.closest("button")) return;
      var rect = modal.getBoundingClientRect();
      if (modal.style.position !== "fixed") {
        // width/height 也要在切成 fixed 定位的同一刻锁死成当前像素值——不锁的
        // 话原来的 "width:100%" 会从"占 overlay 内容区宽度"变成"占整个视口
        // 宽度"（fixed 元素的包含块是视口），弹框会在刚开始拖的瞬间突然变宽。
        modal.style.position = "fixed";
        modal.style.margin = "0";
        modal.style.width = rect.width + "px";
        modal.style.height = rect.height + "px";
        modal.style.left = rect.left + "px";
        modal.style.top = rect.top + "px";
      }
      dragging = true;
      startX = e.clientX; startY = e.clientY;
      startLeft = rect.left; startTop = rect.top;
    });
    document.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var maxLeft = window.innerWidth - modal.offsetWidth;
      var maxTop = window.innerHeight - modal.offsetHeight;
      var left = startLeft + (e.clientX - startX);
      var top = startTop + (e.clientY - startY);
      modal.style.left = Math.min(Math.max(0, left), Math.max(0, maxLeft)) + "px";
      modal.style.top = Math.min(Math.max(0, top), Math.max(0, maxTop)) + "px";
    });
    document.addEventListener("pointerup", function () { dragging = false; });
    document.addEventListener("pointercancel", function () { dragging = false; });
  })();

  var currentCardId = null, currentCard = null, currentIcon = null;

  // 标题栏用日文原句定位是在编辑哪一句（校对转录/挖空片段时看的就是日文），
  // 中文译文已经在下面文本框的 JSON（zh 字段）里，不重复放进标题。
  function sentenceJaText(s) {
    return (s.tokens || []).map(function (t) { return t.text || ""; }).join("");
  }

  function openEditor(cardId, card, icon) {
    currentCardId = cardId;
    currentCard = card;
    currentIcon = icon;
    var s = byId[cardId];
    titleEl.textContent = "card-a" + cardId + "（" + sentenceJaText(s).slice(0, 24) + "）";
    textarea.value = JSON.stringify(pickEditable(s), null, 2);
    errorEl.textContent = "";
    overlay.classList.add("open");
    textarea.focus();
  }

  function closeEditor() {
    overlay.classList.remove("open");
    currentCardId = currentCard = currentIcon = null;
  }

  playBtn.addEventListener("click", function () {
    var audio = document.getElementById("a" + currentCardId);
    if (audio) { audio.currentTime = 0; audio.play(); }
  });

  cancelBtn.addEventListener("click", closeEditor);
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeEditor();
  });

  applyBtn.addEventListener("click", function () {
    var parsed;
    try {
      parsed = JSON.parse(textarea.value);
    } catch (e) {
      errorEl.textContent = "JSON 格式错误：" + e.message;
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      errorEl.textContent = "顶层必须是一个 {...} 对象";
      return;
    }
    if (parsed.tokens !== null && parsed.tokens !== undefined && !Array.isArray(parsed.tokens)) {
      errorEl.textContent = "tokens 必须是数组";
      return;
    }
    if (parsed.blanks !== null && parsed.blanks !== undefined && !Array.isArray(parsed.blanks)) {
      errorEl.textContent = "blanks 必须是数组";
      return;
    }

    var s = byId[currentCardId];
    EDITABLE_FIELDS.forEach(function (k) {
      s[k] = parsed[k] === undefined ? null : parsed[k];
    });

    pending[currentCardId] = pickEditable(s);
    savePending();
    if (currentIcon) currentIcon.classList.add("has-pending");
    window.PageRenderer.rerenderCardContent(currentCard, s);
    // rerenderCardContent() 只更新卡片显示的 HTML/data-blanks 属性，不会
    // 重新搭填空练习模式的输入框——那套 UI 是 listening-page.js 在页面
    // 刚加载时按当时的 data-blanks 建好的，不会自动感知后续的修改（真实
    // 反馈"改完JS数据后，马上不能生效，需要reload页面才生效"）。这里改完
    // 之后单独喊它对这一张卡片重新搭一遍。没有 window.BlankMode（比如
    // 这句没有 blanks，或者页面版本较旧还没这个 hook）就跳过，不报错。
    if (window.BlankMode) window.BlankMode.refreshCard(currentCard);
    closeEditor();
  });

  // ---- 设置面板：编辑模式开关 + 待导出计数/导出/清除暂存 ----
  var settingsPanel = document.getElementById("settingsPanel");
  if (settingsPanel) {
    var group = document.createElement("div");
    group.className = "settings-group settings-group-editmode";
    group.innerHTML =
      '<div class="settings-label">内容编辑</div>' +
      '<div class="settings-options">' +
        '<button class="settings-opt" id="editModeToggle">✎ 编辑模式</button>' +
      "</div>" +
      '<div class="edit-mode-actions">' +
        '<span class="edit-pending-count" id="editPendingCount"></span>' +
        '<button type="button" class="dictate-btn" id="editExportBtn">导出</button>' +
        '<button type="button" class="dictate-btn" id="editClearBtn">清除暂存</button>' +
      "</div>";
    settingsPanel.appendChild(group);

    var toggleBtn = group.querySelector("#editModeToggle");
    var exportBtn = group.querySelector("#editExportBtn");
    var clearBtn = group.querySelector("#editClearBtn");

    function setEditMode(on) {
      document.body.classList.toggle("edit-mode", on);
      toggleBtn.classList.toggle("active", on);
      localStorage.setItem(EDIT_MODE_KEY, on ? "1" : "");
    }
    setEditMode(localStorage.getItem(EDIT_MODE_KEY) === "1");
    toggleBtn.addEventListener("click", function () {
      setEditMode(!document.body.classList.contains("edit-mode"));
    });

    exportBtn.addEventListener("click", function () {
      // "t"（跟读高亮时间戳）在 build_page.py 原始生成的 data.js 里是 Python
      // float，哪怕值本身是整数，json.dump 也会写成 "0.0" 不是 "0"。JS 的
      // JSON.stringify 不区分 int/float，同样的整数值会被写成 "0"——直接导出
      // 会让这些位置在 git diff 里显得"改过"，其实数值完全没变，只是格式跟
      // 原始文件不一致。这里把整数形式的 "t" 值补回 ".0" 后缀，让导出格式
      // 跟 build_page.py 的输出保持一致，避免纯格式噪音混进真实内容的 diff。
      var json = JSON.stringify(DATA, null, 2).replace(
        /"t": (-?\d+)([,\n])/g,
        '"t": $1.0$2'
      );
      var blob = new Blob(
        ["window.LESSON_DATA = " + json + ";\n"],
        { type: "application/javascript" }
      );
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "data.js";
      document.body.appendChild(a);
      a.click();
      a.remove();
    });

    clearBtn.addEventListener("click", function () {
      // 只清掉本地暂存记录（这样下次刷新页面会显示原始未编辑的数据），不
      // 撤销当前页面里已经生效的编辑——想撤销当场的修改，刷新页面就行。
      pending = {};
      localStorage.removeItem(PENDING_KEY);
      document.querySelectorAll(".seg-edit-icon.has-pending").forEach(function (el) {
        el.classList.remove("has-pending");
      });
      updatePendingCount();
    });
  }

  function updatePendingCount() {
    var el = document.getElementById("editPendingCount");
    if (!el) return;
    var n = Object.keys(pending).length;
    el.textContent = n ? n + " 处待导出" : "";
  }
  updatePendingCount();
})();
