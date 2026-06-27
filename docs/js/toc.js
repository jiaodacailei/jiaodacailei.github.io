(function () {
  var postBody = document.querySelector('.post-body');
  if (!postBody) return;

  var headings = Array.from(postBody.querySelectorAll('h2, h3'));
  if (headings.length < 2) return;

  // save original texts BEFORE injecting badges
  var origTexts = headings.map(function (h) { return h.textContent.trim(); });

  // inject number badges into article headings
  headings.forEach(function (h, i) {
    if (!h.id) h.id = 'toc-' + i;
    var badge = document.createElement('span');
    badge.className = 'toc-num-badge';
    badge.textContent = i + 1;
    h.insertBefore(badge, h.firstChild);
  });

  // extract keyword before ：or ——
  function keyText(text) {
    var s = text.indexOf('：');
    if (s > 0) return text.slice(0, s);
    s = text.indexOf('——');
    if (s > 0) return text.slice(0, s);
    return text;
  }

  // build a TOC list item: number + gap + label
  function tocItem(cls, i, full) {
    var label = keyText(full);
    return '<li class="' + cls + '">' +
      '<a data-idx="' + i + '" title="' + full + '">' +
      '<span class="toc-item-num">' + (i + 1) + '</span>' +
      label +
      '</a></li>';
  }

  function scrollToHeading(idx) {
    var t = headings[idx];
    if (t) window.scrollTo({ top: t.offsetTop - 80, behavior: 'smooth' });
  }

  // ── DESKTOP (≥1200px): fixed right sidebar ──────────────────────────────
  function buildDesktop() {
    var nav = document.createElement('nav');
    nav.className = 'toc';
    nav.innerHTML =
      '<div class="toc-label">目录</div><ul>' +
      headings.map(function (h, i) {
        return tocItem('toc-' + h.tagName.toLowerCase(), i, origTexts[i]);
      }).join('') + '</ul>';
    postBody.parentNode.insertBefore(nav, postBody);

    var links = Array.from(nav.querySelectorAll('a'));
    function highlight() {
      var y = window.scrollY + 100, cur = 0;
      for (var i = 0; i < headings.length; i++) { if (headings[i].offsetTop <= y) cur = i; }
      links.forEach(function (a, i) { a.parentElement.classList.toggle('toc-active', i === cur); });
    }
    window.addEventListener('scroll', highlight, { passive: true });
    highlight();
    links.forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        scrollToHeading(+a.dataset.idx);
      });
    });
  }

  // ── MOBILE (<1200px): floating right-edge widget ─────────────────────────
  function buildMobile() {
    var widget = document.createElement('div');
    widget.className = 'toc-float';

    // collapsed: ≡ + number buttons
    var numsEl = document.createElement('div');
    numsEl.className = 'toc-float-nums';
    numsEl.innerHTML =
      '<button class="toc-float-toggle" title="展开目录">≡</button>' +
      headings.map(function (h, i) {
        return '<button class="toc-float-num" data-idx="' + i + '">' + (i + 1) + '</button>';
      }).join('');

    // expanded: full list panel
    var panel = document.createElement('div');
    panel.className = 'toc-float-panel';
    panel.innerHTML =
      '<div class="toc-float-header"><span>目录</span>' +
      '<button class="toc-float-close">✕</button></div>' +
      '<ul>' +
      headings.map(function (h, i) {
        return tocItem('toc-' + h.tagName.toLowerCase(), i, origTexts[i]);
      }).join('') + '</ul>';

    widget.appendChild(numsEl);
    widget.appendChild(panel);
    document.body.appendChild(widget);

    var numBtns  = Array.from(numsEl.querySelectorAll('.toc-float-num'));
    var listLinks = Array.from(panel.querySelectorAll('a'));

    function open()  { widget.classList.add('toc-open'); }
    function close() { widget.classList.remove('toc-open'); }

    numsEl.querySelector('.toc-float-toggle').addEventListener('click', open);
    panel.querySelector('.toc-float-close').addEventListener('click', close);
    numBtns.forEach(function (btn) {
      btn.addEventListener('click', function () { scrollToHeading(+btn.dataset.idx); });
    });
    listLinks.forEach(function (a) {
      a.addEventListener('click', function () { scrollToHeading(+a.dataset.idx); close(); });
    });

    function highlight() {
      var y = window.scrollY + 100, cur = 0;
      for (var i = 0; i < headings.length; i++) { if (headings[i].offsetTop <= y) cur = i; }
      numBtns.forEach(function (b, i)  { b.classList.toggle('active', i === cur); });
      listLinks.forEach(function (a, i) { a.parentElement.classList.toggle('toc-active', i === cur); });
    }
    window.addEventListener('scroll', highlight, { passive: true });
    highlight();
  }

  if (window.innerWidth >= 1200) {
    buildDesktop();
  } else {
    buildMobile();
  }
})();
