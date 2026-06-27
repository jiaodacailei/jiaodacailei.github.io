(function () {
  var postBody = document.querySelector('.post-body');
  if (!postBody) return;

  var headings = Array.from(postBody.querySelectorAll('h2, h3'));
  if (headings.length < 2) return;

  // assign IDs
  headings.forEach(function (h, i) {
    if (!h.id) h.id = 'toc-' + i;
  });

  // extract keyword before ：or ——
  function keyText(text) {
    var s = text.indexOf('：');
    if (s > 0) return text.slice(0, s);
    s = text.indexOf('——');
    if (s > 0) return text.slice(0, s);
    return text;
  }

  // build nav — inserted before .post-body so mobile can flow inline
  var nav = document.createElement('nav');
  nav.className = 'toc';
  nav.innerHTML =
    '<div class="toc-label">目录</div><ul>' +
    headings.map(function (h) {
      var full = h.textContent;
      var label = keyText(full);
      return (
        '<li class="toc-' + h.tagName.toLowerCase() + '">' +
        '<a href="#' + h.id + '" title="' + full + '">' + label + '</a></li>'
      );
    }).join('') +
    '</ul>';

  postBody.parentNode.insertBefore(nav, postBody);

  var links = Array.from(nav.querySelectorAll('a'));

  // ── mobile: tap label to toggle ──
  nav.querySelector('.toc-label').addEventListener('click', function () {
    if (window.innerWidth < 1200) {
      nav.classList.toggle('toc-open');
    }
  });

  // ── mobile: auto-close after clicking a link ──
  links.forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var target = document.getElementById(a.getAttribute('href').slice(1));
      if (target) {
        window.scrollTo({ top: target.offsetTop - 80, behavior: 'smooth' });
      }
      if (window.innerWidth < 1200) {
        nav.classList.remove('toc-open');
      }
    });
  });

  // ── desktop: highlight current section on scroll ──
  function onScroll() {
    if (window.innerWidth < 1200) return;
    var scrollY = window.scrollY + 100;
    var current = 0;
    for (var i = 0; i < headings.length; i++) {
      if (headings[i].offsetTop <= scrollY) current = i;
    }
    links.forEach(function (a, i) {
      a.parentElement.classList.toggle('toc-active', i === current);
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
