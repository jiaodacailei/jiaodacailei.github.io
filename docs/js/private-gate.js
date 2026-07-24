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

  async function sha256(str) {
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function afterUnlock() {
    gate.style.display = "none";
    document.getElementById("content").style.display = "block";
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
  if (sessionStorage.getItem(STORAGE_KEY) === "1") {
    afterUnlock();
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
