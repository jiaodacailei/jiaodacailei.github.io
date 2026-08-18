# -*- coding: utf-8 -*-
"""
用法：
  python boundary_editor_server.py <docs/private/<slug>> <tab的mondai名>
      [--out <工作目录，默认同 build_boundary_editor.py>] [--port 8080]

共享工具（`jp-textbook-lesson` 用）：`build_boundary_editor.py` +
`boundary_editor.html` + `apply_boundary_edits.py` 那一套"人工拖边界"
流程原来要走"网页导出JSON→人工复制粘贴回对话→Claude手动跑脚本落地"
这一圈，纯粹是因为网页是用 `npx http-server` 起的静态文件服务器，浏览器
里的JS没有文件系统写权限、也没法直接跑ffmpeg——**用户明确问过"为什么
不能直接反应到项目文件里，还要再发一次给你"，这个脚本就是answer**：
把静态文件服务器换成这一个，多加一个 `POST /apply` 接口，网页里点"保存"
直接 `fetch` 过来，接口在本地直接调 `apply_boundary_edits.apply_edits()`
落地音频+data.js，成功后立刻用 `build_boundary_editor.build_editor_data()`
把 `manifest.json`/`merged.mp3` 刷新成最新发布状态，网页收到成功响应后
自动刷新页面，可以无缝继续编辑下一批——全程不需要再经过对话。

只监听 127.0.0.1，跟直接在本机跑任何脚本是同一个信任级别，不会暴露给
局域网/公网。

首次跑这个脚本时会顺带生成一次 `manifest.json`/`merged.mp3`（等价于先跑
一遍 `build_boundary_editor.py`），不用分两步。
"""
import sys
import os
import json
import http.server
import socketserver
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from apply_boundary_edits import apply_edits
from build_boundary_editor import build_editor_data


def make_handler(slug_dir, tab_name, work_dir):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f"[server] {self.address_string()} " + (fmt % args))

        def do_POST(self):
            if self.path != "/apply":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                result = apply_edits(slug_dir, work_dir, payload)
                if result["touched"]:
                    # 落地成功，立刻重新生成一份反映最新状态的 manifest/merged.mp3，
                    # 网页刷新后能无缝继续编辑，不用再手动跑 build_boundary_editor.py
                    build_editor_data(slug_dir, tab_name, work_dir)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, **result}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug_dir", help="docs/private/<slug>")
    ap.add_argument("tab", help='tab的mondai名，比如 "会话"/"课文"/"生词"')
    ap.add_argument("--out", default=None, help="工作目录，默认 tools/listening/work/<slug>/boundary_editor_<tab>/")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    slug_dir = os.path.abspath(args.slug_dir.rstrip("/\\"))
    slug = os.path.basename(slug_dir)
    work_dir = os.path.abspath(args.out or os.path.join(
        "tools", "listening", "work", slug, f"boundary_editor_{args.tab}"
    ))

    print(f"生成/刷新一份最新的编辑数据到 {work_dir} ...")
    manifest = build_editor_data(slug_dir, args.tab, work_dir)
    print(f"就绪：{len(manifest['sentences'])} 条，总时长 {manifest['totalDuration']:.1f}s")

    os.chdir(work_dir)
    handler = make_handler(slug_dir, args.tab, work_dir)
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"浏览器打开 http://127.0.0.1:{args.port}/boundary_editor.html")
        print(f"点“保存到项目文件”会直接落地到 {slug_dir}，不用再导出JSON")
        print("Ctrl+C 停止")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("已停止")


if __name__ == "__main__":
    main()
