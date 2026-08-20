# -*- coding: utf-8 -*-
"""
用法：
  python boundary_editor_server.py [--port 8080] [--root .]

共享工具（`jp-textbook-lesson` 用）：一体化本地服务器，单进程服务全部课程，
浏览器 URL 里带 `?slug=<课程>&tab=<mondai名>` 就能切换要编辑哪一课的哪个
tab，不用每换一课就重新起一个进程/占一个新端口（真实反馈：用户直接问
"能不能url中带上课程的标识，方便我切换课程"）。

跟旧版（每个进程绑死一个 slug+tab，启动时传参数）的区别：
  旧：python boundary_editor_server.py docs/private/<slug> <tab> --port 8080
      只服务这一个 slug+tab，换课程要另开一个进程换个端口。
  新：python boundary_editor_server.py --port 8080
      单进程，`GET /manifest.json?slug=X&tab=Y`/`GET /merged.mp3?slug=X&tab=Y`
      /`POST /apply`（body 里已经带 slug/tab）全部动态解析，浏览器直接改
      URL 的 query string 就能切换，不用重启进程。

路由：
  GET  /                          重定向到 /boundary_editor.html
  GET  /boundary_editor.html      编辑器页面本身（跟 slug/tab 无关，纯静态）
  GET  /lessons                   扫 docs/private/ 下有 data.js 的目录，
                                   返回 [{"slug":, "title":, "tabs":[...]}]
                                   给页面里的课程切换器用
  GET  /manifest.json?slug=&tab=  现场用 build_editor_data() 重新生成
                                   （保证永远反映当前已发布状态，不会有
                                   "work目录缓存过期"的问题），返回JSON
  GET  /merged.mp3?slug=&tab=     跟上面配套生成的同一份音频（页面先
                                   fetch manifest.json 再 fetch 这个，
                                   顺序保证了这时候文件已经写好）
  POST /apply                     body 是 boundary_editor.html 导出的
                                   {slug, tab, edits} 原样格式，调用
                                   apply_boundary_edits.apply_edits() 落地，
                                   成功后立刻重新生成对应 work 目录

只监听 127.0.0.1，不会暴露给局域网/公网。
"""
import sys
import os
import re
import json
import glob
import http.server
import socketserver
import argparse
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    # 关键：line_buffering=True，不然stdout重定向到文件时是全缓冲，日志攒在
    # 内存里可能几十条才落一次盘——真实踩过的坑：进程正常跑着的时候查日志文件
    # 一直是空的，误以为"没收到过这个请求"，其实是缓冲区还没冲下去，跟请求
    # 有没有真的发生是两回事，靠这份日志做取证完全靠不住
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from apply_boundary_edits import apply_edits
from build_boundary_editor import build_editor_data, load_lesson_data

REPO_ROOT = None  # 启动时设成 --root 的绝对路径


def slug_dir_of(slug):
    return os.path.join(REPO_ROOT, "docs", "private", slug)


def work_dir_of(slug, tab):
    return os.path.join(REPO_ROOT, "tools", "listening", "work", slug, f"boundary_editor_{tab}")


def discover_lessons():
    private_dir = os.path.join(REPO_ROOT, "docs", "private")
    out = []
    for entry in sorted(os.listdir(private_dir)):
        slug_dir = os.path.join(private_dir, entry)
        data_js = os.path.join(slug_dir, "data.js")
        if not os.path.isfile(data_js):
            continue
        try:
            data = load_lesson_data(slug_dir)
        except Exception:
            continue
        tabs = [t.get("mondai") for t in data.get("tabs", []) if t.get("mondai")]
        if not tabs:
            continue
        out.append({"slug": entry, "title": data.get("title") or entry, "tabs": tabs})
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} " + (fmt % args))

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        if not os.path.exists(path):
            self._json(404, {"ok": False, "error": f"not found: {path}"})
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/boundary_editor.html")
            self.end_headers()
            return

        if path == "/boundary_editor.html":
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boundary_editor.html")
            self._file(html_path, "text/html; charset=utf-8")
            return

        if path == "/lessons":
            try:
                self._json(200, {"ok": True, "lessons": discover_lessons()})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/manifest.json":
            slug, tab = qs.get("slug", [None])[0], qs.get("tab", [None])[0]
            if not slug or not tab:
                self._json(400, {"ok": False, "error": "缺 slug 或 tab 参数"})
                return
            try:
                manifest = build_editor_data(slug_dir_of(slug), tab, work_dir_of(slug, tab))
                self._json(200, manifest)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/merged.mp3":
            slug, tab = qs.get("slug", [None])[0], qs.get("tab", [None])[0]
            if not slug or not tab:
                self._json(400, {"ok": False, "error": "缺 slug 或 tab 参数"})
                return
            self._file(os.path.join(work_dir_of(slug, tab), "merged.mp3"), "audio/mpeg")
            return

        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/apply":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
            slug, tab = payload["slug"], payload["tab"]
            # 默认的 HTTP access log 只记路径（POST /apply 本身不带参数，
            # 真正的 slug/tab/edits 都在 body 里），不单独记一行的话，事后
            # 想查"到底是哪一课被存了、存了什么"完全没法追溯——真实踩过的坑
            print(f"[apply] slug={slug} tab={tab} edits={payload.get('edits')}")
            result = apply_edits(slug_dir_of(slug), work_dir_of(slug, tab), payload)
            print(f"[apply] slug={slug} tab={tab} 落地完成，touched={[t['id'] for t in result['touched']]}, "
                  f"clauseBoundsTouched={[t['id'] for t in result.get('clauseBoundsTouched', [])]}, "
                  f"tokenOverridesTouched={[t['id'] for t in result.get('tokenOverridesTouched', [])]}")
            if result["touched"] or result.get("clauseBoundsTouched") or result.get("tokenOverridesTouched"):
                # 落地成功，立刻刷新这个 slug+tab 的 work 目录，下次 GET
                # manifest.json 或者切回这一课都不会读到过期状态——clauseBounds-only
                # 的改动虽然不重切音频，但也会让缓存在 work 目录里的 manifest.json
                # 里的 clauseBounds 字段过期，同样要刷新（apply_edits() 自己读的
                # 是这份缓存文件当"编辑前"的基准，不重新生成的话下一次 /apply
                # 会拿着过期的 clauseBounds 基准去算，可能把已经保存过的改动覆盖掉）
                build_editor_data(slug_dir_of(slug), tab, work_dir_of(slug, tab))
            self._json(200, {"ok": True, **result})
        except Exception as e:
            print(f"[apply] 失败: {e}")
            self._json(500, {"ok": False, "error": str(e)})


def main():
    global REPO_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="仓库根目录（含 docs/、tools/），默认当前目录")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    REPO_ROOT = os.path.abspath(args.root)
    if not os.path.isdir(os.path.join(REPO_ROOT, "docs", "private")):
        print(f"FAIL: {REPO_ROOT} 下没有 docs/private/，--root 传对了吗？")
        sys.exit(1)

    lessons = discover_lessons()
    print(f"发现 {len(lessons)} 门课程：{', '.join(l['slug'] for l in lessons)}")

    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"浏览器打开 http://127.0.0.1:{args.port}/boundary_editor.html?slug=<课程slug>&tab=<mondai名>")
        print("不带参数打开会看到课程/tab选择器")
        print("Ctrl+C 停止")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("已停止")


if __name__ == "__main__":
    main()
