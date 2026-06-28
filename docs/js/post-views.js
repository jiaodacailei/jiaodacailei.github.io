(function () {
  var meta = document.querySelector('.post-page-meta');
  if (!meta) return;
  var span = document.createElement('span');
  span.className = 'post-view-count';
  span.textContent = '…';
  meta.appendChild(span);
  fetch('https://jiaodacailei.goatcounter.com/counter' + window.location.pathname + '.json')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      span.textContent = '👁 ' + (d.count || 0) + ' 次阅读';
    })
    .catch(function () { span.remove(); });
})();
