# 日语听力精听页生成工具

给一段日语录音，生成一个密码保护、逐句可播放/重放/循环的听力页面（假名注音 + 中文翻译 + 语法笔记）。

> 完整流程（包括内容零散 vs 结构化两种情形、多 Agent 并行翻译、常见坑）见
> `.claude/skills/jp-listening-page/SKILL.md`。这份 README 只讲脚本本身怎么用。

## 环境准备（只需一次）

```bash
python -m pip install --user -r requirements.txt
```

不需要单独安装 ffmpeg，`imageio-ffmpeg` 会自带一个可执行文件。

## 使用流程

语音转写和音频切分是脚本自动完成的；但**转写质量取决于录音本身**（嘈杂/多人交叉发言的会议录音效果会明显下降），所以中间需要人工（或找 Claude）复听筛选、补充翻译和语法笔记——这一步无法完全自动化。

### 1. 转写

```bash
python transcribe.py 录音.m4a transcript.json --model medium
```

输出每句话的起止时间戳和识别文本。**大录音建议后台跑**，medium 模型处理 11 分钟录音大约需要 10 分钟左右（CPU）。

### 2. 人工筛选

打开 `transcript.json`，删掉明显跑偏/幻觉的句子（嘈杂录音里 Whisper 经常会编出一些不知所云的话），只保留听得懂、语义通顺的句子，另存为 `curated.json`（数组，每项保留 `start`/`end`/`text` 即可）。

### 3. 补充假名注音

```bash
python add_furigana.py curated.json enriched.json
```

会给每句话加上 `<ruby>` 假名注音，并预留空的 `zh`（中文翻译）、`notes`（语法/发音笔记）字段。

### 4. 填写翻译和语法笔记

打开 `enriched.json`，给每一条填上 `zh` 和 `notes`。这一步建议直接让 Claude 读 `enriched.json` 帮忙写，比纯脚本靠谱。

> 内容如果是结构化的（比如 JLPT 真题分成問題1~5），条目一多建议改用多个 Agent 按分组
> 并行翻译，再用 `merge_groups.py <items.json> <输出enriched.json> <分组结果1.json> ...`
> 合并（会自动按 id 对齐 group/start/end 并生成假名注音）。详见 SKILL.md。

### 5. 生成最终页面

```bash
python build_page.py 录音.m4a enriched.json ../../docs/private/<slug> \
  --title "日语听力精听：xxx" \
  --subtitle "来源说明……" \
  --password sairai
```

会在 `docs/private/<slug>/` 下生成 `index.html`（密码门 + `noindex`）和 `audio/seg-NN.mp3` 逐句音频片段。

## 注意事项

- **不要**把生成的页面加进 `docs/blog/index.html`、`docs/index.html`、`docs/blog/posts.json` 或任何导航——保持"不公开链接"，只有拿到直链的人能访问。
- 这是**公开仓库**。密码门只能挡住随便浏览的人，挡不住知道/猜到直链、或直接在 GitHub 仓库页面翻文件的人，也挡不住搜索引擎收录整个仓库文件列表的可能性。真正敏感的录音不建议走这条路径。
- 密码用 SHA-256 存在页面里做客户端校验，view-source 看不到明文，但仍然是"防君子不防小人"级别的保护，不是真正的访问控制。
