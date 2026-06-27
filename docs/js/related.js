(function () {
  var parts = location.pathname.split('/');
  var slug = parts[parts.length - 1].replace('.html', '');

  fetch('../posts.json')
    .then(function (r) { return r.json(); })
    .then(function (posts) {
      var cur = null;
      for (var i = 0; i < posts.length; i++) {
        if (posts[i].slug === slug) { cur = posts[i]; break; }
      }
      if (!cur || !cur.tags.length) return;

      var scored = posts
        .filter(function (p) { return p.slug !== slug; })
        .map(function (p) {
          var score = p.tags.filter(function (t) { return cur.tags.indexOf(t) !== -1; }).length;
          return { slug: p.slug, title: p.title, score: score };
        })
        .filter(function (p) { return p.score > 0; })
        .sort(function (a, b) { return b.score - a.score; })
        .slice(0, 4);

      if (!scored.length) return;

      var section = document.createElement('div');
      section.className = 'related-posts';
      section.innerHTML = '<h3>相关阅读</h3><ul>' +
        scored.map(function (p) {
          return '<li><a href="' + p.slug + '.html">' + p.title + '</a></li>';
        }).join('') +
        '</ul>';

      var body = document.querySelector('.post-body');
      if (body) body.insertAdjacentElement('afterend', section);
    })
    .catch(function () {});
})();
