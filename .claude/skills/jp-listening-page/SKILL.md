---
name: jp-listening-page
description: Turn a Japanese audio recording (meeting recording, JLPT listening test, etc.) into a password-protected, unlisted listening-practice page on this site — sentence-level clips with furigana, Chinese translation, grammar notes, a blog-style TOC sidebar, and three-level (sentence / question / section) play+loop controls. Use when the user gives you a Japanese audio file and asks for a listening drill page, a "N级听力" page, or to "把这段录音做成听力页面".
---

# 日语听力精听页生成

给一段日语录音，生成一个密码保护、不进导航的**逐句**精听页面：假名注音 + 中文翻译 +
语法笔记，配三层播放控制（逐句 / 小题整体 / 大题整体，每层都能单次播放和循环），
页面结构复用博客文章同款的目录侧栏（`toc.js`），方便手机上浏览。

## 参数

这个 skill 的输入参数是**音频文件路径**（必填，位置参数）。调用时把音频文件的完整路径
作为 `args` 传入，比如：

```
/jp-listening-page C:\Users\xxx\Downloads\2021年7月N2.mp3
```

开工前仍然要跟用户确认标题、密码、输出 slug（用来定输出目录名 `docs/private/<slug>/`）、
是否公开进导航——见下面"0. 先问清楚"。这些不是 args 的一部分，是对话里问。

## 已跑过的真实案例

- `docs/private/dingliehui-260327/` — 一段嘈杂的工作会议录音，14句精选片段，早期版本，
  还是扁平卡片结构，没有分组/没有三层播放，仅供参考对比，没有按新版重新生成过（内容
  简单，其实不太需要分组/目录，扁平卡片够用）。
- `docs/private/n2-listening/2021-07/` — 一套完整 JLPT N2 听力真题，**已按下面这版流程
  跑通**：308 句、29 个小题、5 个大题，`h2`/`h3` + `toc.js` 目录、三层播放控制全部验证
  可用。下面第 2~3 步描述的"两轮 Agent"做法就是从这个案例里跑出来的最佳实践。

## 工具在哪

`tools/listening/` 下已有的脚本，**都已按当前设计实现完毕**：

- `transcribe.py` — chunked Whisper 转写（绕开 VAD 在长静音/嘈杂片段整段吞掉或产生幻觉
  的问题）。
- `add_furigana.py` — 简单流程（内容零散、无分组、不需要目录）用的老脚本，纯逐句转
  furigana，产出的 enriched.json 没有 `mondai`/`question`/`answer` 分组信息，配合
  `build_page.py` 时所有句子会被归到一个默认分组下，不会生成 `h3`/目录/整题整段播放——
  内容简单（十几句、没有天然的题号结构）时用这个就够了。
- `merge_groups.py` — 结构化流程用的合并脚本，输入是 `raw_sentences.json`（原始转写片段，
  含 raw_id/mondai/question/start/end/text）+ 若干个 Agent 产出的分组翻译结果（每项标注
  `raw_ids` 归属哪些原始片段），自动反查时间戳、生成假名注音、按 mondai+question 合并
  小题总览，输出 `enriched.json`（`{"sentences":[...], "questions":[...]}`）。
- `build_page.py` — 生成最终页面：`.post-body` + `h2`(問題N)/`h3`(小题) 结构、动态注入
  `/js/toc.js`（密码验证通过后才注入，见下面"常见坑"）、三层播放控制 JS、密码门、
  `noindex`。输入是 `merge_groups.py`（或 `add_furigana.py`）产出的 `enriched.json`。
- `README.md` — 环境安装说明。

## 整体流程

### 0. 先问清楚，别自己假设

开工前必须跟用户确认这几件事：

1. **这段录音是谁的内容？** 不是用户本人原创的（官方真题、他人会议录音等），要提示
   版权/隐私风险：公开仓库里，密码门只挡"随便点进网站的人"，挡不住"直接翻 GitHub
   仓库文件列表的人"。用户拍板要不要继续。
2. **要不要进站内导航？** 默认不进，只用 `noindex` + 密码门做"不公开链接"。
3. **密码是什么、标题是什么、输出目录 slug 用什么？** 都让用户定或确认，不要自己编。
4. **处理范围多大？** 音频越长后续步骤越慢（转写 + 逐句翻译 + 切片）。跟用户确认全部
   处理还是先做一段验证。
5. **逐句笔记的详略度**：默认只在真正有语法/词汇点的句子写笔记，"はい""そうですね"
   这类语气词/寒暄不用硬凑笔记（除非用户要求每句都写）。

### 1. 转写

```bash
python tools/listening/transcribe.py <音频文件> <输出.json> --model medium
```

- `run_in_background: true` 跑，音频超过几分钟就别等在前台。
- `--model medium`：安静清晰的录音室音质、嘈杂会议录音都用这个，`small` 在两次真实
  案例里质量都明显更差。
- 转写完先通读一遍结果，**不要假设转写是准的**——Whisper 会在安静片段幻觉出无关句子
  （比如编出"ご視聴ありがとうございました"这种视频结尾语），肉眼过一遍是必须的。

### 2. 找出小题/大题的时间边界（仅结构化内容需要）

内容有固定结构（比如 JLPT 按"問題1""1番""2番"…这类口播编号分段）的话，先通读转写文本，
找出每一题的起止时间戳，写一个一次性脚本构建 `items.json`：每项
`{"id":.., "mondai": "問題1", "label": "1番", "start":.., "end":..}`。

**每大题最后一题的结束时间要卡在下一大题的口播指示语开始之前**，否则"問題2ではまず
質問を聞いてください"这类过渡指示会被吞进上一题的片段里（真实案例踩过这个坑，参考
`build_items.py` 里 `MONDAI_INSTRUCTION_START` 式的硬边界写法）。

内容零散无固定结构的（会议录音等）跳过这步，直接进入第 3 步的简化版（见下面"简单流程"）。

### 3. 两轮 Agent：先按题产出"标准答案"，再拆成逐句

这是从 N2 真题案例里跑出来的最佳实践，比一步到位直接让 Agent 输出逐句结果准确得多——
因为逐句拆分需要同时处理"听写纠错"和"时间戳对齐"两件事，分两轮做，每轮只专注一件事，
Agent 出错率明显更低。

**第一轮——按大题产出整题的标准答案**（不追求逐句，先把内容彻底修正、翻译准确）：

用 `Agent` 工具按大题并行处理（每个"問題N"一个 Agent），一条消息发出全部调用以真正并行。
给每个 Agent 该分组所有题目的原始转写（把 `items.json` 边界内的 segments 拼成整段文本），
明确指出已知的同音字错误模式，要求输出 JSON 数组，每项
`{"id", "label", "text"（清理后加标点的完整日语原文）, "zh"（完整中文翻译）,
"notes"（这道题的听力技巧+语法点+正确答案推理）, "answer"（正确答案）}`。
每个 Agent 结果存成独立文件（如 `mondai1_result.json`）。

**中间步骤——提取原始逐句片段**：从 `transcribe.py` 的输出 + `items.json` 边界，为每道题
提取时间范围内的原始 segments，删掉纯语气词/空片段，得到 `raw_sentences.json`：数组，
每项 `{"raw_id":.., "mondai":.., "question":.., "start":.., "end":.., "text": "原始转写"}`
（一次性脚本，参考 `extract_raw_sentences.py` 的做法）。按 mondai 拆成 `raw_m1.json` ~
`raw_m5.json` 分别喂给下一轮的 Agent。

**第二轮——逐句拆分+对齐**：再次按大题并行开 Agent，这次让每个 Agent **读取两个文件**
（用 Read 工具，不要把内容整个塞进 prompt，量大会很长）：
1. `raw_mN.json` —— 原始逐句片段（有时间戳，但可能被切碎/切错边界）
2. `mondaiN_result.json` —— 第一轮产出的"标准答案"（内容准确，但没有时间戳）

要求 Agent 把第一轮的准确文本拆成自然分句，并给每句标出对应第二份数据里的哪些
`raw_id`（因为一句话经常被原始转写切成两段、或者两句话被粘在一起，需要 Agent 按时间顺序
和文字内容做合理对齐，不用精确到字）。输出 JSON 对象：
```json
{
  "sentences": [{"raw_ids": [1,2], "question": "1番", "text": "..", "zh": "..", "notes": ".."}, ...],
  "questions": [{"question": "1番", "overview": "..", "answer": ".."}, ...]
}
```
`notes` **只在这句真正有语法/词汇点时才写**，寒暄/语气词留空字符串 `""`；`answer` 直接
照抄第一轮已经验证过的结果，不用重新分析。

**两轮都要注意**：Agent 返回的 JSON 里不要用英文直引号 `"` 做中文强调，改用「」或中文
弯引号，否则解析失败（真实案例踩过好几次，每次都要手动修）。每个结果存文件后立刻跑
`python -c "import json; json.load(open(...))"` 校验。

**简单流程**（内容零散、无分组，比如十几句话的会议录音）：不用两轮，直接一轮 Agent
（或量少的话自己写）把转写内容拆成逐句 `{"start":.., "end":.., "text": ".."}`，
再跑 `add_furigana.py` 生成 furigana + 空的 zh/notes 字段，自己填translation/notes即可。

### 4. 合并 + 生成假名注音

```bash
python tools/listening/merge_groups.py raw_sentences.json enriched.json sent_m1.json sent_m2.json ...
```

会按 `raw_ids` 反查每句的 start/end/mondai，生成 `<ruby>` 假名注音，按时间顺序排序，
输出 `{"sentences":[...], "questions":[...]}`。

### 5. 生成最终页面

```bash
python tools/listening/build_page.py <原始音频> enriched.json docs/private/<slug> \
  --title "标题" \
  --subtitle "副标题，说明来源和处理方式" \
  --password <用户指定的密码>
```

`build_page.py` 产出的页面结构：

- 整体外壳用 `.post-page > .post-page-header + .post-body` 结构（复用 `/css/style.css`
  里博客文章的样式），密码门 `#gate` 覆盖在最外层。`#content` 默认 `display:none`，
  密码验证通过后才 `display:block` **并动态创建 `<script src="/js/toc.js">` 注入到
  页面**——不能在 HTML 里静态写死 `<script src="/js/toc.js">`，因为 toc.js 是立即执行
  的 IIFE，如果页面刚加载、内容还被密码门藏着（`display:none`）就跑，量测到的
  `offsetTop` 全是 0，目录生成的滚动定位会全部错位。
- `h2`＝每个大题（問題1、問題2…），标题里嵌着"▶ 播放整个问题"和"⟲ 循环整个问题"
  两个按钮（`class="scope-btn m-play/m-loop"`），外层包一个
  `<section class="mondai-section" data-scope="mondai">`。
- `h3`＝每个小题（1番、2番…），这是目录里能点进去的第二级条目，标题里嵌
  "▶ 播放整题"/"⟲ 循环整题"按钮（`class="scope-btn q-play/q-loop"`），外层包
  `<div class="question-block" data-scope="question">`，下面先渲染 `overview`，
  `answer` 用 `<details class="seg-answer">` 折叠。
- 每个小题下面按顺序列出该题的每一句：`.seg-card` 小卡片，逐句"▶ 播放"/"↺ 重放"/
  "⟲ 循环"，配假名 + 中文翻译 +（如果有）笔记。

**三层播放控制的实现**（不需要额外切拼接音频文件，直接顺序播放已切好的逐句 `<audio>`）：

- 不是靠 `data-mondai`/`data-question` 属性去全局筛选 `<audio>`，而是靠 DOM 嵌套：
  播放整题时 `document.querySelectorAll('.question-block[data-scope="question"]')`
  里每个 block 自己 `querySelector("audio")` 拿到区块内的所有音频（DOM 顺序即播放顺序）；
  播放整个大题同理，作用域换成 `.mondai-section`。这样不用额外打标签，容器嵌套关系
  本身就是作用域。
- 用一个 `playSequence(audios, loop, btn)` 函数统一处理"播放整题"和"播放整个问题"：
  维护一个 `idx`，靠每个 `audio.onended` 驱动播放下一个；循环模式下放完最后一个跳回
  `idx=0` 继续；提供 `stop()` 方法清空所有 `onended` 监听并暂停。
- **全局只允许一路播放**：模块级变量 `activeSeq`（当前序列播放）和 `activeSingle`
  （当前单句播放），任何新播放动作开始前先调用 `stopEverything()` 清掉这两者、
  重置所有按钮的文案/`active`样式。

生成后：
1. 用 `Start-Process` 打开本地文件，自己检查：密码门、目录侧栏（桌面宽屏 / 手机窄屏
   都看一下）、逐句播放/重放/循环、小题整体播放/循环、大题整体播放/循环、循环之间
   互不冲突。
2. **不要**加进 `docs/blog/index.html`、`docs/index.html`、`docs/blog/posts.json`
   或任何导航——除非用户明确要求公开。
3. `git status` 确认没有把原始长音频文件（用户桌面/下载目录里的源文件）带进
   staging，只应该有 `docs/private/<slug>/` 下的短音频片段和页面文件。
4. 提交前问用户要不要 commit/push——这类内容涉及隐私/版权，不要自作主张推送。

## 笔记怎么写

- 只在真正有语法/词汇点的句子上写，寒暄/语气词（"はい""そうですね"之类）留空。
- 有内容的笔记大致包含：这句话/这个表达的用法要点、1~2 个值得学的语法点，不用每条
  都写成一段小作文。
- 小题级别的 `overview`/`answer`：概括这道题在问什么 + 正确答案 + 推理依据，没有官方
  答案来源的要注明是分析推理，不是确认过的官方答案。

## 常见坑

- Whisper 幻觉：安静/嘈杂片段容易编出"ご視聴ありがとうございました"之类的视频结尾语，
  跟内容毫无关系，务必人工核对后删除。
- VAD 吞内容：`transcribe.py` 已经用固定分块绕开了这个问题，但如果自己改用别的转写
  方式遇到大段内容消失，先怀疑 VAD。
- 分段边界：结构化材料里，大题之间的过渡口播（"問題2ではまず…"）容易被吞进上一大题
  最后一句的时间范围里，切每句音频前要单独核实边界，选项编号（"1""2""3"）容易被
  单独识别成一句，记得合并回对应内容。
- Agent 返回的 JSON 里用直引号 `"` 做中文强调会导致 JSON 解析失败，写文件前处理掉。
- 三层播放控制要做好"停止其它正在播放的序列"，否则容易叠音。
- `toc.js` 只有 `.post-body` 内 `h2`/`h3` 合计 ≥2 个才会生成目录，页面结构一定要用
  真正的 `h2`/`h3` 标签，不能用别的元素模拟标题。
- `toc.js` 必须在密码验证通过、内容变为可见之后才动态注入执行，不能在页面加载时
  静态引入，否则它量测标题位置时内容还是 `display:none`，目录点击跳转的位置全错。
- 一句话如果被 Agent 判定为对应同一个原始 `raw_id`（比如两个很短的寒暄语被 Whisper
  合并识别成了一段），最终会共享同一段时间戳、切出同一段音频——这是原始转写粒度的
  限制，不是 bug，不用强行拆开。
- 公开仓库 = 没有真正的访问控制，密码门只是"防随便看"，不是"防有心人"，动手前把这个
  风险跟用户说清楚。
