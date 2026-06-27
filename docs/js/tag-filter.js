document.addEventListener('DOMContentLoaded', function () {
  var items = Array.from(document.querySelectorAll('.post-item'));

  // collect tag frequencies from subtitle text
  var tagCount = {};
  items.forEach(function (item) {
    var sub = item.querySelector('.post-subtitle');
    if (!sub) return;
    sub.textContent.split('·').forEach(function (t) {
      t = t.trim();
      if (t) tagCount[t] = (tagCount[t] || 0) + 1;
    });
  });

  // tags appearing 2+ times, sorted by frequency desc
  var topTags = Object.keys(tagCount)
    .filter(function (t) { return tagCount[t] >= 2; })
    .sort(function (a, b) { return tagCount[b] - tagCount[a]; });

  if (!topTags.length) return;

  // build filter bar (collapsed by default)
  var bar = document.createElement('div');
  bar.className = 'tag-filter collapsed';
  var allBtn = '<button class="tag-btn active" data-tag="all">全部 (' + items.length + ')</button>';
  var tagBtns = topTags.map(function (t) {
    return '<button class="tag-btn" data-tag="' + t + '">' + t + ' (' + tagCount[t] + ')</button>';
  }).join('');
  bar.innerHTML = allBtn + tagBtns;

  // expand / collapse toggle button
  var toggle = document.createElement('button');
  toggle.className = 'tag-toggle-btn';
  toggle.textContent = '展开 ▾';
  toggle.addEventListener('click', function () {
    var isExpanded = bar.classList.toggle('expanded');
    bar.classList.toggle('collapsed', !isExpanded);
    toggle.textContent = isExpanded ? '收起 ▴' : '展开 ▾';
  });

  var list = document.querySelector('.post-list');
  if (list) {
    list.parentNode.insertBefore(bar, list);
    list.parentNode.insertBefore(toggle, list);
  }

  // filter on click
  bar.addEventListener('click', function (e) {
    var btn = e.target.closest('.tag-btn');
    if (!btn) return;
    bar.querySelectorAll('.tag-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    var tag = btn.dataset.tag;
    items.forEach(function (item) {
      var sub = item.querySelector('.post-subtitle');
      var tags = sub ? sub.textContent.split('·').map(function (t) { return t.trim(); }) : [];
      item.style.display = (tag === 'all' || tags.indexOf(tag) !== -1) ? '' : 'none';
    });
  });
});
