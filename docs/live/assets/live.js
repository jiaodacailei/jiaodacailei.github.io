// 直播背景板：缩放适配 + 场景切换
// 键盘：1-9 直接切场景，←/→ 上下一个，H 显示/隐藏提示，P 自动轮播开关，C 显示光标
// 网址参数：?scene=qa 指定起始场景；?auto=40 每 40 秒自动轮播
(function () {
  var stage = document.getElementById('stage');
  function fit() {
    var s = Math.min(innerWidth / 1920, innerHeight / 1080);
    stage.style.transform = 'scale(' + s + ')';
    stage.style.marginLeft = (-960 * s) + 'px';
    stage.style.marginTop = (-540 * s) + 'px';
  }
  addEventListener('resize', fit); fit();

  var scenes = Array.prototype.slice.call(document.querySelectorAll('.scene'));
  var cur = 0, timer = null, params = new URLSearchParams(location.search);
  function show(i) {
    cur = (i + scenes.length) % scenes.length;
    scenes.forEach(function (el, k) { el.classList.toggle('on', k === cur); });
    var hint = document.getElementById('hint');
    if (hint) hint.textContent = (cur + 1) + '/' + scenes.length + ' ' + (scenes[cur].dataset.scene || '') + '  [1-' + scenes.length + ' ←→ H P C]';
  }
  function auto(sec) {
    clearInterval(timer); timer = null;
    if (sec > 0) timer = setInterval(function () { show(cur + 1); }, sec * 1000);
  }
  var start = params.get('scene'), idx = 0;
  scenes.forEach(function (el, k) { if (el.dataset.scene === start) idx = k; });
  show(idx);
  auto(parseInt(params.get('auto') || '0', 10));

  addEventListener('keydown', function (e) {
    var n = parseInt(e.key, 10);
    if (n >= 1 && n <= scenes.length) { auto(0); show(n - 1); }
    else if (e.key === 'ArrowRight' || e.key === ' ') { auto(0); show(cur + 1); }
    else if (e.key === 'ArrowLeft') { auto(0); show(cur - 1); }
    else if (e.key === 'h' || e.key === 'H') document.body.classList.toggle('show-hint');
    else if (e.key === 'p' || e.key === 'P') auto(timer ? 0 : 40);
    else if (e.key === 'c' || e.key === 'C') document.documentElement.style.cursor = document.documentElement.style.cursor ? '' : 'default';
  });
})();
