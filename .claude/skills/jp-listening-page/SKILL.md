---
name: jp-listening-page
description: Turn a Japanese audio recording (meeting recording, JLPT listening test, etc.) into a password-protected, unlisted listening-practice page on this site — segmented clips with furigana, Chinese translation, grammar notes, and per-clip play/replay/loop controls. Use when the user gives you a Japanese audio file and asks for a listening drill page, a "N级听力" page, or to "把这段录音做成听力页面".
---

# 日语听力精听页生成

给一段日语录音，生成一个密码保护、不进导航的逐句精听页面：假名注音 + 中文翻译 + 语法笔记 +
可单独播放/重放/循环的音频片段。已经在两个真实案例上跑通：一段嘈杂的工作会议录音
（`docs/private/dingliehui-260327/`）和一套完整的 JLPT N2 听力真题
（`docs/private/n2-listening/2021-07/`）。

## 工具在哪

`tools/listening/` 下已有的脚本：

- `transcribe.py` — chunked Whisper 转写（绕开 VAD 在长静音/嘈杂片段整段吞掉或产生幻觉的问题）
- `add_furigana.py` — 给简单流程（单一说话人/无需分组）用：转写结果直接转 furigana + 空的 zh/notes 字段
- `merge_groups.py` — 给结构化流程（有分组，多个 Agent 并行翻译）用：按 id 合并多份翻译结果 + 生成 furigana
- `build_page.py` — 切音频片段 + 生成最终密码门页面（支持可选的分组小标题 `group` 字段和可折叠答案 `answer` 字段）
- `README.md` — 环境安装说明（`pip install --user -r requirements.txt`，已在本机装过）

## 整体流程

### 0. 先问清楚，别自己假设

开工前必须跟用户确认这几件事（不要跳过，两次真实案例都因为没提前说清楚而返工过）：

1. **这段录音是谁的内容？** 如果不是用户本人的原创录音（比如 JLPT 官方真题、他人的会议录音），
   要明确提示版权/隐私风险：这是公开仓库，即使页面加了密码，仓库里的文件本身（音频、
   转写文本）对任何拿到仓库地址的人都是可见的——密码只挡"随便点进网站的人"，挡不住
   "直接翻 GitHub 仓库文件列表的人"。让用户自己拍板要不要继续。
2. **要不要进站内导航？** 默认不进——不加进 `blog/index.html`、`docs/index.html`、
   `blog/posts.json`，只用 `<meta name="robots" content="noindex, nofollow">` +
   密码门做"不公开链接"。除非用户明确说要公开栏目。
3. **密码是什么？** 让用户指定，不要自己编。
4. **处理范围多大？** 音频越长，转写+人工整理的时间成本越高（11分钟录音的 chunked 转写
   约需 10-15 分钟后台任务，43 分钟的完整 N2 真题实测跑了近 30 分钟）。跟用户确认是要
   全部处理还是先做一小段验证流程。

### 1. 转写

```bash
python tools/listening/transcribe.py <音频文件> <输出.json> --model medium
```

- 用 `run_in_background: true` 跑，音频超过几分钟就别等在前台。
- `--model`：安静清晰的录音室音质（比如官方考试录音）用 `medium` 效果就很好；
  嘈杂的会议录音同样用 `medium`，`small` 在两个真实案例里质量都明显更差
  （大段静音/嘈杂片段直接被吞掉或编出无关内容）。
- 转写完先自己通读一遍结果，**不要直接假设转写是准的**——两次真实案例里都出现过
  Whisper 在安静片段幻觉出无关句子（比如编出"ご視聴ありがとうございました"这种
  视频结尾语），以及长静音段被 VAD 整段吞掉的问题。`transcribe.py` 已经用固定长度
  分块转写绕开了大部分 VAD 问题，但幻觉句子还是会出现，肉眼过一遍是必须的。

### 2. 判断内容类型，选简单流程还是结构化流程

**类型 A：内容零散、无固定结构**（会议录音、聊天录音等）

直接走"筛选可用句子"的简单流程：

1. 通读转写结果，只保留听得懂、语义通顺的句子，丢掉明显跑偏/幻觉的部分
   （参考案例：50段里保留了14段可用的）。存成一个 JSON 数组
   `[{"start":.., "end":.., "text": ".."}, ...]`。
2. `python tools/listening/add_furigana.py 筛选后.json enriched.json`
3. 打开 `enriched.json`，给每条填 `zh`（中文翻译）和 `notes`（语法/发音笔记），
   笔记风格参考下面"笔记怎么写"一节。内容不多的话（十几条）直接自己写，不用开 Agent。
4. 跳到第 4 步生成页面。

**类型 B：内容有固定结构**（JLPT 听力真题、有明确分段的培训材料等）

1. 通读转写文本，找出每一题/每一段的起止时间戳（比如 JLPT 靠"問題1""1番""2番"…
   这类口播的编号锚点）。把结构手绘出来先——数一下总共有多少题，确认符合预期的
   题型结构（N2 听力固定是 問題1~5，共 5+6+5+11(或12)+2 题左右）。
2. 写一个一次性脚本构建 `items.json`：每项 `{"id":.., "group": "問題1", "label": "1番",
   "start":.., "end":..}`。**每大题最后一题的结束时间要卡在下一大题的口播指示语开始
   之前**，否则"問題2ではまず質問を聞いてください"这类过渡指示会被吞进上一题的片段里
   （踩过这个坑，记得设置 `MONDAI_INSTRUCTION_START` 式的硬边界）。
3. 用 `Agent` 工具按分组（比如每个"問題N"一个 Agent）并行处理，一条消息里发出全部
   Agent 调用以真正并行。每个 Agent 的 prompt 需要包含：
   - 该分组所有题目的原始转写文本（id/label/raw_text）
   - 明确指出转写里已知的同音字错误、幻觉句子模式，让 Agent 修正/删除
   - 输出格式要求：只输出合法 JSON 数组，每项 `{"id", "label", "text"（清理后加标点的
     日语原文）, "zh"（中文翻译）, "notes"（语法笔记，150~300字左右，讲清楚这类题型的
     听力技巧+2~4个语法点+正确答案和推理依据）, "answer"（正确答案及理由）}`
   - **明确要求 Agent 不要在 JSON 字符串里用英文直引号 `"` 做强调**，改用「」或中文弯引号，
     否则合并时会 JSON 解析失败（两次真实案例都踩过这个坑，返工修过）
4. 每个 Agent 返回后，把结果存成独立的 json 文件（比如 `group1_result.json`），存之前
   跑一次 `python -c "import json; json.load(open(...))"` 校验，坏了就手动修引号。
5. 全部分组做完后合并：
   ```bash
   python tools/listening/merge_groups.py items.json enriched.json group1_result.json group2_result.json ...
   ```

### 3. 笔记怎么写（不管走哪条流程）

参考两次真实案例里 Agent/自己写的笔记结构，每条 note 大致包含：

- 这道题/这句话在听力技巧上的要点（比如"課題理解要抓最后确定的动作，不要被中途
  被否定的选项迷惑"）
- 2~4 个值得学的语法点或惯用表达，挑贴近目标水平的（N2 就挑 N2 语法，不用讲 N5 基础）
- 如果有正确答案，给出答案+推理依据，不要只给答案不给理由
- 没有官方答案来源的（比如自己推理出的），在 notes 或 answer 里注明这是分析推理，
  不是确认过的官方答案

### 4. 生成最终页面

```bash
python tools/listening/build_page.py <原始音频> enriched.json docs/private/<slug> \
  --title "标题" \
  --subtitle "副标题，说明来源和处理方式" \
  --password <用户指定的密码>
```

输出 `docs/private/<slug>/index.html` + `docs/private/<slug>/audio/seg-NN.mp3`。

生成后：
1. 用 `Start-Process` 打开本地文件，自己检查一遍密码门、播放、重放、循环按钮，
   以及分组标题/答案折叠是否正常渲染，再报告给用户。
2. **不要**加进 `docs/blog/index.html`、`docs/index.html`、`docs/blog/posts.json`
   或任何导航——除非用户明确要求公开。
3. `git status` 确认没有把原始长音频文件（用户桌面/下载目录里的源文件）带进 staging，
   只应该有 `docs/private/<slug>/` 下的短音频片段和页面文件。
4. 提交前问用户要不要 commit/push——这类内容涉及隐私/版权，不要自作主张推送。

## 常见坑

- Whisper 幻觉：安静/嘈杂片段容易编出"ご視聴ありがとうございました"之类的视频结尾语，
  跟内容毫无关系，务必人工核对后删除。
- VAD 吞内容：`transcribe.py` 已经用固定分块绕开了这个问题，但如果自己改用别的转写方式
  遇到大段内容消失，先怀疑 VAD。
- 分组边界：结构化材料里，大题之间的过渡口播（"問題2ではまず…"）容易被吞进上一大题
  最后一题的音频片段里，切音频前要单独核实这段边界。
- Agent 返回的 JSON 里用直引号 `"` 做中文强调会导致 JSON 解析失败，写文件前处理掉。
- 公开仓库 = 没有真正的访问控制，密码门只是"防随便看"，不是"防有心人"，动手前把这个
  风险跟用户说清楚。
