// 密码门共享脚本——所有密码保护的私有页面（听力精听页、枢纽页……）都用这一份。
// 页面结构约定：#gate（data-hash 属性存密码的 SHA-256）+ #pwdInput/#pwdBtn/#pwdErr +
// #content（验证通过后显示的正文）。
//
// 解锁状态按"密码哈希"存 sessionStorage，不按页面路径存——同一个密码在多个页面通用
// （比如枢纽页和它链接的每个听力页密码都一样），解锁任意一个，同一浏览器标签页里
// 哈希相同的其它页面都会自动识别成已解锁，不用重复输密码。不管是先开枢纽页登录、
// 还是直接开某个子页面登录，效果一样。
(function() {
  var gate = document.getElementById("gate");
  var HASH = gate.dataset.hash;
  var STORAGE_KEY = "unlocked-hash-" + HASH;

  // crypto.subtle 只在"安全上下文"可用：页面被嵌进 http:// 的父页面（比如内网 http 部署的学习平台用
  // iframe 嵌入）时，即使本页是 https，浏览器也判定为非安全上下文，crypto.subtle 为 undefined，
  // 密码验证会直接抛错、#pw= 自动解锁失效。这时退回下面的纯 JS 实现（结果与 crypto.subtle 相同）。
  function sha256Js(str) {
    var msg = unescape(encodeURIComponent(str));
    var K = [
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    ];
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var bytes = [];
    for (var i = 0; i < msg.length; i++) bytes.push(msg.charCodeAt(i));
    var bitLen = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    for (var s = 7; s >= 0; s--) bytes.push(s >= 4 ? 0 : (bitLen >>> (s * 8)) & 0xff);
    var rotr = function(x, n) { return (x >>> n) | (x << (32 - n)); };
    for (var off = 0; off < bytes.length; off += 64) {
      var w = new Array(64);
      for (var t = 0; t < 16; t++) {
        w[t] = (bytes[off + t * 4] << 24) | (bytes[off + t * 4 + 1] << 16) | (bytes[off + t * 4 + 2] << 8) | bytes[off + t * 4 + 3];
      }
      for (t = 16; t < 64; t++) {
        var s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
        var s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (t = 0; t < 64; t++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[t] + w[t]) | 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
      H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
    }
    return H.map(function(x) { return ("00000000" + (x >>> 0).toString(16)).slice(-8); }).join("");
  }
  async function sha256(str) {
    if (!(window.crypto && crypto.subtle)) return sha256Js(str);
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function afterUnlock() {
    gate.style.display = "none";
    document.getElementById("content").style.display = "block";
    // 通知其它脚本"正文现在可见了"（listening-page.js 的 ?qs= 深链接要等正文
    // 显示之后才能算滚动位置——#content 解锁前是 display:none，offsetTop 恒为0）。
    document.dispatchEvent(new CustomEvent("gateunlocked"));
  }
  async function tryUnlock(pwd) {
    var h = await sha256(pwd);
    if (h === HASH) {
      afterUnlock();
      sessionStorage.setItem(STORAGE_KEY, "1");
    } else {
      document.getElementById("pwdErr").textContent = "パスワードが違います";
    }
  }
  // 从 URL 取密码自动解锁（方便从别的应用直接跳进来）：优先 #pw=<密码>
  // （fragment 不会发给服务器/写进访问日志，也不会进 Referer），也兼容
  // ?pw=<密码>。取到后立刻从地址栏抹掉，不留在历史记录/分享出去的链接里。
  // 只是把明文密码放进链接的便利功能——链接本身等于密码，别转发。
  function takePasswordFromUrl() {
    var pwd = null;
    try {
      var h = new URLSearchParams(location.hash.replace(/^#/, ""));
      var q = new URLSearchParams(location.search);
      if (h.has("pw")) { pwd = h.get("pw"); h.delete("pw"); }
      if (q.has("pw")) { if (pwd === null) pwd = q.get("pw"); q.delete("pw"); }
      if (pwd !== null) {
        var qs = q.toString(), hs = h.toString();
        history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + (hs ? "#" + hs : ""));
      }
    } catch (e) {}
    return pwd;
  }
  var urlPwd = takePasswordFromUrl();
  if (sessionStorage.getItem(STORAGE_KEY) === "1") {
    afterUnlock();
  } else if (urlPwd) {
    tryUnlock(urlPwd).then(function() {
      if (gate.style.display !== "none") document.getElementById("pwdInput").focus();
    });
  } else {
    // HTML 上已经写了 autofocus，这里再用 JS 调一次 .focus() 兜底（defer 脚本
    // 执行时机、部分浏览器对 autofocus 的处理差异等都可能让它不生效）。iOS
    // Safari 出于防止意外弹出键盘的考虑，非用户手势触发的 focus() 大概率还是
    // 不会拉起键盘——这是平台限制，网页代码没有绕过的办法，光标停在输入框上
    // （聚焦态本身）依然是生效的，只是键盘不会自动弹出，用户点一下就行。
    document.getElementById("pwdInput").focus();
  }
  document.getElementById("pwdBtn").addEventListener("click", function() {
    tryUnlock(document.getElementById("pwdInput").value);
  });
  document.getElementById("pwdInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") tryUnlock(this.value);
  });
})();
