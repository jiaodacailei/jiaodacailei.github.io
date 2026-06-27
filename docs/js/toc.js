(function () {
  var body = document.querySelector('.post-body');
  if (!body) return;

  var headings = Array.from(body.querySelectorAll('h2, h3'));
  if (headings.length < 2) return;

  // assign IDs
  headings.forEach(function (h, i) {
    if (!h.id) h.id = 'toc-' + i;
  });

  // build nav
  var nav = document.createElement('nav');
  nav.className = 'toc';
  nav.innerHTML =
    '<div class="toc-label">目录</div><ul>' +
    headings.map(function (h) {
      return (
        '<li class="toc-' + h.tagName.toLowerCase() + '">' +
        '<a href="#' + h.id + '">' + h.textContent + '</a></li>'
      );
    }).join('') +
    '</ul>';

  document.body.appendChild(nav);

  var links = Array.from(nav.querySelectorAll('a'));

  // highlight current section on scroll
  function onScroll() {
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

  // smooth scroll on click
  links.forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var target = document.getElementById(a.getAttribute('href').slice(1));
      if (target) {
        window.scrollTo({ top: target.offsetTop - 80, behavior: 'smooth' });
      }
    });
  });
})();
