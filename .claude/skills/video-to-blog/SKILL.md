---
name: video-to-blog
description: Turn a video the user gives (YouTube link, or a local video file) into a blog post on this site, with the video embedded — used when there is no ready-made transcript/script (no captions track, no accompanying txt/pptx). Screenshots frames at a fixed interval, crops the burned-in subtitle band, tiles frames into contact sheets so the transcript can be read off in a handful of vision passes instead of one call per frame, then writes the post following BLOG_CONVERT.md's template/tone/index-update steps and picks a few illustrative screenshots to embed alongside the text. Use when the user gives a video link/file and asks to "把这个视频做成博客"/"视频转博客"/"帮我写篇博客把视频嵌进去" or similar. If the user already has a script/文字稿/要点, skip straight to BLOG_CONVERT.md's txt-conversion path instead — this skill is specifically for the no-transcript-available case.
---

# 视频转博客

给一个视频（YouTube 链接，或本地视频文件），在没有现成文字稿的情况下（没有字幕轨、
用户手头也没有口播稿/大纲），生成一篇博客文章，把视频嵌入进去，正文内容来自视频里
烧录在画面上的硬字幕。

真实案例：`docs/blog/posts/ai-reversal-senior-engineers.html`（2026-09-18，YouTube
链接 `https://youtu.be/nL250_LxcPY`）——一条3分45秒的口播视频，YouTube 页面本身没有
字幕轨（`timedtext` 接口返回空），但视频画面下方正中烧录了硬字幕，靠"截图+视觉
识别"完整听写出了文字稿。

## 何时用这个 skill，何时不用

- **用户已经有文字稿/口播稿/大纲**（哪怕只是要点）：直接走 `BLOG_CONVERT.md` 的
  "二、txt 文件转博客"，不需要这个 skill——先问用户"能不能贴一份文字稿/要点"永远是
  最快路径，这个 skill 只在问过之后用户明确说"看不到/没有/你直接分析视频"时才用。
- **视频本身有字幕轨**：先尝试直接拿字幕（见下面"零、先试试有没有现成字幕"），
  成功就不需要走截图流程——截图流程是没有字幕轨时的兜底方案，不是默认第一选择。
- **视频没有任何文字性字幕（纯口播无字幕）**：这个 skill 处理不了，Claude 没有能
  "听"音频转写的工具，如果画面上也没有烧录字幕，只能请用户提供文字稿。

## 零、先试试有没有现成字幕（大概率会失败，但值得先排除）

1. `WebFetch` 拿 oEmbed 信息确认视频标题/作者（`https://www.youtube.com/oembed?url=<encoded_watch_url>&format=json`），
   确认这是用户自己的内容、拿到标题方便后面起标题。
2. 直接 `WebFetch` watch 页面通常拿不到东西——YouTube 是重 JS 渲染的页面，`WebFetch`
   把 HTML 转 markdown 后只剩页脚导航链接，标题/描述/字幕数据全部丢失（唯一能捞到的
   是 `<title>` 标签里的视频标题）。
3. 真正想拿字幕轨，用 `curl` 抓原始页面 HTML（不要用 `WebFetch`，它会把 JSON 数据
   转没了），搜索 `captionTracks`/`timedtext`：
   ```bash
   curl -sL "https://www.youtube.com/watch?v=<VIDEO_ID>" -A "Mozilla/5.0 ..." -o yt.html
   grep -o '"captionTracks":\[[^]]*\]' yt.html
   ```
   真实案例这一步搜不到任何 `captionTracks`（说明这条视频没有上传/生成字幕轨），
   `https://video.google.com/timedtext?type=list&v=<VIDEO_ID>` 也返回空——**这是
   预期的常见结果，不是环境配置问题**，遇到空结果不用反复重试，直接进入下一步。

## 一、下载视频

需要 `yt-dlp`（没装就 `python -m pip install --user --quiet yt-dlp`，Windows 上直接
`python -m yt_dlp ...` 调用，不依赖 PATH 里有没有这个命令）。

**先列出可用格式，不要猜清晰度代号**——不同视频的格式列表不一样，直接传
`-f "best[height<=480]/best"` 这类猜测式选择器，遇到某些视频会报
`Requested format is not available`：
```bash
python -m yt_dlp --list-formats "<watch_url>"
```
只是为了截图 OCR 字幕，**选一个 360p 左右的纯视频流**（不需要音频，`video only`
那几行），文件小、下载快：
```bash
python -m yt_dlp -f <format_id> -o "video.%(ext)s" "<watch_url>"
```
下载到 scratchpad 目录下的临时子文件夹（比如 `<scratchpad>/yt/`），不要下载到项目
目录里。

## 二、抽帧 + 裁字幕条 + 拼大图（核心步骤，决定效率）

**不要一帧一帧单独用 Read 工具看**——几分钟的视频按1秒1帧抽出来就是几百张图，
一张张看会把 context 打爆。正确做法是"抽帧 → 裁出字幕条 → 拼成大图 → 一张大图看
一次"，能把"读多少次图"压到个位数。

1. **先看一两张完整帧，确定字幕条的位置**（不同视频字幕位置、字号不一样，别直接
   假设固定坐标）：
   ```bash
   ffmpeg -i video.mp4 -vf "fps=1" -qscale:v 4 frames_full/f_%04d.jpg
   ```
   用 Read 工具看一两张 `frames_full/f_00XX.jpg`，目测字幕文字的大致 y 坐标范围，
   留够上下余量（比如字幕在 300~345px、总高 360px，裁 255~360 这一段，给两行字幕
   留余地）。

2. **按1秒1帧，裁出字幕条，同时烧录时间戳标签**（时间戳是后面对照"这句话大概在
   第几秒"、写文章时定位截图素材必需的）：
   ```bash
   ffmpeg -i video.mp4 -vf "fps=1,crop=<W>:<H>:<X>:<Y>,drawtext=fontfile='C\:/Windows/Fonts/arial.ttf':text='%{eif\:n\:d}s':fontcolor=yellow:fontsize=16:x=4:y=4:box=1:boxcolor=black@0.5" -qscale:v 3 sub_crops/c_%04d.jpg
   ```
   **`drawtext` 必须显式传 `fontfile`**——这台机器的 Windows ffmpeg 构建没配置
   fontconfig，不传 `fontfile` 直接让 ffmpeg 立刻 segfault（`Fontconfig error:
   Cannot load default config file`），不是命令语法错了，换一个真实存在的 Windows
   字体路径（`arial.ttf`）就行。

3. **用 `tile` 滤镜把字幕条拼成网格大图**，一张大图放 25 帧（5x5），能大幅减少
   之后要读的图片数量：
   ```bash
   ffmpeg -i sub_crops/c_%04d.jpg -vf "tile=5x5" -vsync 0 -qscale:v 4 sheets/sheet_%02d.jpg
   ```
   一个225秒的视频，1秒1帧=225帧，25帧一张=9张大图，只需要9次Read调用就能看完全部
   字幕，而不是225次。**不要用 ImageMagick 的 `convert`/`montage` 命令拼图**——
   Windows 自带一个同名的磁盘转换工具 `C:\Windows\system32\convert.exe`，
   `command -v convert` 会返回这个无关程序而不是报"命令不存在"，容易误判环境里
   装了 ImageMagick，实际调用会跟磁盘转换语法完全对不上；`ffmpeg` 自带的 `tile`
   滤镜就能满足拼图需求，不需要额外依赖。

4. **逐张读大图，边看边听写**，把每张里能读到的字幕（每格左上角有烧录的秒数
   标签）按顺序转成一段连续文字。同一句话通常会连续出现在好几个格子里（字幕在
   屏幕上停留数秒），去重、拼接成完整句子，遇到明显的错别字/拼音谐音（这类视频
   字幕经常是语音识别自动生成，比如把"Claude Code"识别成"cloude code"）按语义
   自行纠正，不要机械照抄错别字。

## 三、挑几张配图截图（"图文并茂"）

正文里除了嵌入视频本身，通常还需要在对应段落插入几张视频截图——但第二步裁出来的
字幕条图分辨率很低（360p 的一部分），直接拿来当博客配图会模糊。做法：

1. 先写完文字稿、确定文章分几个段落、每段对应视频里大致哪个时间点。
2. 对每个想配图的时间点，**只下载那几秒钟的高清片段**（不要为了截几张图重新下载
   整条高清视频，既慢又没必要）：
   ```bash
   python -m yt_dlp -f <720p或以上format_id> --download-sections "*<start>-<end>" -o "clip_<start>.%(ext)s" "<watch_url>"
   ```
   这个环境访问 YouTube 有时会被限速到个位数 KB/s，几秒钟的小片段哪怕限速也能在
   合理时间内下完，几分钟的完整视频用同样的限速下载会等很久。
3. 从每段小片段里抽1帧看效果，**如果人物眼睛闭着/表情别扭，换同一小段里的另一个
   帧号重抽一次**（同一句话说话过程中会有好几帧可选，不用将就第一次抽到的）：
   ```bash
   ffmpeg -i clip_<start>.mp4 -vf "select=eq(n\,<frame_idx>)" -vframes 1 -qscale:v 2 shot_x.jpg
   ```
4. 满意的截图存到 `docs/images/`，文件名用"文章slug-描述"的命名规则（比如
   `ai-reversal-shot-claude-code.jpg`），不要用无意义的 `shot1.jpg` 之类。
5. 如果视频里出现了值得单独放大看的静态画面（比如活动海报、架构图，不是"人在
   说话"这种镜头），同样用"短片段高清下载"的方式单独截一张，不用凑合用1fps那批
   低分辨率截图。

## 四、写正文、嵌入视频、配图、更新索引

这一步开始跟其它来源（txt/pptx）共用同一套规范，直接照抄 `BLOG_CONVERT.md`：
- **HTML模板/前言（front matter）格式**：见 `BLOG_CONVERT.md` 第四节——注意
  现在博客用的是 Jekyll `layout: post` + front matter 的新格式（`title`/
  `description`/`date`/`tags`/`nav_active`/`render_with_liquid: false`），
  正文只需要 `<div class="post-body">...</div>`，不用像旧模板那样手写
  nav/footer/script 标签，`_layouts/post.html` 会自动包一层。参考任意一篇
  `docs/blog/posts/*.html` 里日期较新的文件，照抄 front matter 结构。
- **语气/人称**：第一人称，短句、口语化，配合作者已经写过的其它文章保持一致的
  吐槽/自嘲风格——如果这条视频是某篇旧文章的后续/反转，**开头呼应一下旧文章**
  （检查 `docs/blog/posts/` 里有没有讲同一件事的更早文章，读一遍抄相似的用词和
  梗，不要另起一套语气）。
- **视频嵌入**：用 `.post-video` 这个响应式 16:9 容器 class（`docs/css/style.css`
  里已有，跟 `.post-img` 是同一套视觉语言），内嵌 YouTube iframe：
  ```html
  <div class="post-video">
    <iframe src="https://www.youtube.com/embed/<VIDEO_ID>" title="<视频标题>" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>
  </div>
  ```
  放在开头引言之后、正文详细展开之前，不要放在文章最后（读者应该先看到能点开看
  的视频，再往下读文字版）。
- **截图配图**：用现成的 `.post-img` class（`<figure class="post-img"><img
  .../><figcaption>...</figcaption></figure>`），穿插在对应段落**之间**（读到
  哪一段配哪一段的图），不要全部堆在文章末尾。
- **更新三处索引**（`BLOG_CONVERT.md` 第五节）：`docs/blog/index.html`（列表页
  顶部插入）、`docs/index.html`（首页只保留最新2篇，把最旧的一篇顶掉）、
  `docs/blog/posts.json`（数组顶部插入，`tags` 跟 `post-subtitle` 保持一致）。

## 五、发布前必须给用户看一遍

**这篇文章的文字内容是 Claude 从字幕截图听写、按作者语气改写出来的，不是作者自己
写的原文**——发布前必须先把内容摘要/全文给用户过一遍，问清楚"有没有理解错的地方、
想不想改措辞"，得到明确确认（哪怕只是简单一句"push"/"可以"）之后才能 `git push`
到 `main`（这个仓库是 GitHub Pages，push 到 main 就是直接上线）。`git commit`
可以先做（本地、可逆），但不要在没有用户确认的情况下把内容推送成对外可见的"作者
本人说的话"。

## 六、常见坑

- `yt-dlp -f "best[height<=480]/best"` 这类猜测式格式选择器，遇到某些视频会报
  `Requested format is not available`——先 `--list-formats` 再选具体 format id，
  不要盲猜。
- ffmpeg 的 `drawtext` 滤镜在这台机器上不传 `fontfile` 会直接 segfault（见上面
  第二节），不是语法错误，是这台机器的 ffmpeg 构建缺 fontconfig 默认配置。
- `command -v convert` 在 Windows 上会命中系统自带的磁盘转换工具，不是
  ImageMagick——判断有没有 ImageMagick 要用 `command -v magick`，拼图优先用
  ffmpeg 自带的 `tile` 滤镜，不依赖 ImageMagick。
- 抽帧截图选中的那一帧可能刚好是眨眼/说话中间的别扭表情——同一小段视频多抽
  一两个不同帧号对比着选，不要只抽一帧就定稿。
- 这个环境访问 YouTube 有被限速到个位数 KB/s 的情况，下载配图截图只下几秒钟的
  片段（`--download-sections`），不要为了几张图下载整条高清视频。
