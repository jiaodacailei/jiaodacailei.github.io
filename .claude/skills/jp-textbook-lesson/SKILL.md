---
name: jp-textbook-lesson
description: Turn a Japanese textbook lesson (photographed/screenshotted vocab list + dialogue + main text, each with its own audio recording, e.g. 《标准日本语》中级) into a password-protected, unlisted practice page on this site — three tabs (会话/课文/生词) with furigana, Chinese translation, grammar notes, word-level read-along highlighting, dictation (默写) and fill-in-blank (填空) practice modes, and the shared floating mini-player. Use when the user gives you a directory of textbook lesson material (screenshots + audio, organized in per-section subfolders) and asks to build a practice page or skill from it.
---

# 教材课文精听/默写练习页生成

给一套教材课文材料（截图 + 音频，按"会话/课文/生词"分文件夹），生成一个密码保护、
不进导航的练习页：三个 tab（会话/课文/生词），假名注音 + 中文翻译 + 语法笔记，
播放时逐词跟读高亮，支持默写/填空练习模式，右下角悬浮迷你播放器。

这个 skill 复用 `jp-listening-page`/`jp-meeting-listening-page` 的全部工具链和页面
基建（`transcribe.py`/`refine_boundaries.py`/`validate_boundaries.py`/`build_page.py`/
`listening-page.css`/`listening-page.js`/`private-gate.js`/默写填空练习模式），**跟
它们的核心区别**：

- 那两个 skill 处理的是**录音本身就是唯一信源**，日语原文靠 Whisper 转写再人工/
  Agent 校对得到，有"转写不可靠、需要核对/筛选"的问题。
- 这个 skill 处理的是**教材**——日语原文已经印在书上、截图里，是 100% 准确的
  ground truth，不需要"校对 Whisper 转写"这一步，Whisper 只用来给已知文本配
  时间戳（打时间戳草稿 + `refine_boundaries.py` 精修边界）。这让流程明显变简单：
  没有"两轮 Agent 产出标准答案"，也没有"筛选可信句子"。
- 教材音频通常拆成**多个独立文件**（会话/课文/生词各一段），不是一份连续录音，
  页面却要合成一个（tab 切换、悬浮播放器统一控制）。见下面"多段音频怎么合成一个
  页面"。

## 已跑过的真实案例

- `docs/private/textbook-sjp-zg-l10/` — 第一个案例，《标准日本语》中级第10课
  （スケジュール／温泉大国、日本／约99个生词，来自 `C:\Users\leicai\Documents\
  標準日本語\中级第10课`）。这个 skill 建立时的原型，下面所有默认值/坑都来自
  这次的实际经验。

## 参数

输入参数是**一个目录路径**，形状约定为：

```
<课程目录>/
  会话/    （或"對話"等，取决于教材命名——按实际文件夹名识别，不强求这个字面值）
    *.jpg/*.png     课本截图（可能不止一张，按文件名顺序读，但见下面"截图排序坑"）
    *.m4a/*.mp3     这个部分的录音（应该只有一个）
  课文/
    ...同上结构...
  单词/
    ...同上结构...
```

有几个子文件夹、分别叫什么名字，直接读目录列出来，按文件夹名映射成 tab 标签
（不强制"会话/课文/单词"这三个字，教材不一样命名可能不同，比如"對話"/"本文"/
"語彙"，照抄实际文件夹名）。只出现其中一部分文件夹（比如没有"单词"）也正常处理，
tab 数量跟着文件夹数量走。

标题、密码、输出 slug——按下面"0. 默认值怎么定"处理。

## 0. 默认值怎么定

跟 `jp-listening-page`/`jp-meeting-listening-page`一致的原则：**有先例可循时不逐项
问，没有先例（新教材系列第一课）时要问**。

- **slug**：`textbook-<书名缩写>-<课号>`，缩写没有先例时问用户（第一个案例是
  `textbook-sjp-zg-l10`——sjp=标准日本语，zg=中级，l10=第10课）。同一本书后续课
  沿用同样的缩写规律，只换课号，不用再问。
- **密码**：复用全站统一密码哈希（跟 `docs/private/index.html` 枢纽页、N2 系列
  共用一份），从任意现有私有页面的 `<div id="gate" data-hash="...">` 摘，
  `build_page.py` 用 `--password-hash` 传。
- **枢纽页**：这个 skill 的默认值是**独立枢纽页**（`docs/private/textbook/
  index.html`），不混进 `docs/private/index.html`（第一个案例里用户明确要求
  "单独做一个枢纽页"，后续确认过"课程要有一个总的入口页，而不是每课一个"）——
  **不管哪本教材/哪个系列，都只用这一个枢纽页**，都加进同一份卡片列表，不用
  再问、也不再建新的枢纽页。
- **tab 顺序**：照抄源材料自己的 tab 顺序（第一个案例是 会话→课文→生词，来自
  app 截图里"会话/课文/语法与表达/生词/练习"的顺序，只取有材料的那几个）。
- **语法与表达/练习 tab**：如果用户没提供对应的文件夹，不生成这两个 tab，不用
  临时编内容凑数。
- **默写/填空练习模式**：直接继承共享 JS/CSS 里已有的默写/填空模式，不用为这个
  skill 单独实现——`docs/js/listening-page.js`/`docs/css/listening-page.css` 已经
  支持，`build_page.py` 生成的页面结构（`.seg-card`/`.seg-notes`）天然兼容。

## 整体流程

### 1. 读截图，抄下 ground-truth 原文

**不用 OCR 工具，直接用 Read 工具读图**（Claude 自带视觉能力，比接一个额外 OCR
依赖更可靠，尤其教材截图里经常混着日语/中文/假名读音，一般 OCR 分不清版式）。
按文件夹分别读：

- **会话/课文类**（整段对话/文章）：把每张截图里的文字原样抄下来，保留说话人
  标签、场景说明（通常是中文，用括号或斜体标出）。场景说明/中文旁白不当成日语
  听写句子（后面第3步会跳过，见"中文旁白怎么处理"）。
- **生词类**（词条列表）：每条格式通常是"假名（汉字）[词性] 中文释义"，抄的时候
  分开记：`text`（喂给 `ruby_html()` 生成假名注音用的原文——有汉字就填汉字形式
  比如"観光地"，纯假名/片假名词条就原样填比如"スケジュール"）、`zh`（连词性
  标签一起抄，比如`"[名] 观光胜地，旅游胜地"`，帮助记忆）。

**截图排序坑（已踩过）**：滚动截屏工具导出的文件名时间戳顺序**不一定**等于
滚动/阅读顺序——真实案例（textbook-sjp-zg-l10）里`单词/`文件夹三张图的文件名
序号是 489<490<491，但实际内容顺序是 489→491→490（490 结尾有"下一个生词表"
的过渡语，491 的内容明显接在 489 后面）。**不要假设文件名数字顺序=阅读顺序**，
每张截图读完后要看内容是否和上一张自然衔接（词条列表看是否跟前一张的最后一条
语义连贯、对话看是否是同一场景的下一句），衔接不上就重新排列，排完序在后面
第2步"跟 Whisper 粗转写核对顺序"那一步还有一次交叉验证的机会。

### 2. 每段音频跑 Whisper 打时间戳草稿

```bash
python tools/listening/transcribe.py <部分>/<音频文件> <输出.json> --model medium
```

多个部分（会话/课文/生词）**各自独立跑**，`run_in_background: true`（并行跑省
时间）。这一步的转写文本**不用来校对原文**（原文已经从截图抄下来了，比 Whisper
的转写准），只用来：

1. 交叉验证第1步排的顺序对不对——转写文本即使个别字听错，大体的词/句顺序应该
   跟截图抄下来的 ground-truth 顺序一致，如果对不上说明第1步排序或转写本身有
   问题，回去核对（真实案例里就是靠这一步确认了"489→491→490"这个顺序）。
2. 生词表：转写出来的 segment 数量应该约等于词条数量（真实案例：99个词条对
   100个 Whisper segment，多出来的1个是句尾静音处的典型 Whisper 幻觉"ご視聴
   ありがとうございました"，删掉后精确 1:1，位置索引对应即可拿到每个词的粗
   时间戳，不用跑 `refine_boundaries.py`——单词粒度不需要逐字符高亮，粗时间戳
   够用，省一大截处理时间）。segment 数量对不上时，回去听一下差异出现的位置，
   通常是某条截图抄漏/多抄，或者 Whisper 把两个词合并识别成一个 segment。
3. 会话/课文：粗时间戳只是给 `refine_boundaries.py` 当起点用的草稿，不需要精确
   到句——但**不要偷懒直接按"整段平均分"分配粗时间戳给每一句**，那样如果某句
   实际很长、某句很短，草稿边界可能整个偏到相邻句子的范围外，`refine_
   boundaries.py` 的算法是"以整道题（这里=整个 tab 内的一个 question 分组）的
   粗边界为窗口重新做一次转写"，草稿窗口偏差太大会导致窗口漏掉真实内容或包含
   进下一组的内容。做法：对照 Whisper 转写文本，把已知的句子在文字上跟转写
   片段做粗略比对，按转写片段的时间戳分配（一句可能跨好几个转写 segment，也
   可能好几句共享一个 segment，都要跟着转写内容手动split/合并着分配，不是纯
   算比例）——这一步麻烦但值得做，直接决定 `refine_boundaries.py` 那一步的
   輸入质量。

### 3. 中文旁白怎么处理

会话类材料里常见的中文场景说明/旁白（比如"（王风和山田坐在沙发上，翻开日程
表。）"）**不当成一句要听写的日语**，从 `enriched.json` 的 `sentences` 里直接
跳过（连对应的音频时间段也不切）——这段旁白占的音频时长依然存在于原始录音里，
只是不给它生成 `.seg-card`，播放时这段时间就是两句真实日语对话之间的一小段
空白，不影响功能。**不要**为了保留旁白硬凑一个"没有日语原文"的卡片，那会破坏
默写/填空模式假设"每个 `.seg-card` 都有 `.seg-ja`"的前提。

### 4. 组装 `enriched.json`（会话/课文用 `refine_boundaries.py`，生词跳过）

会话/课文两段：按"每道题=一个 question 分组"的结构（可以按场景/段落分
question，比如会话分"商量行程"/"电话预订"两组，课文按自然段分"第1段"~"第4段"
——这样侧栏导航更有用），`mondai` 统一填这一段对应的 tab 标签（比如"会话"），
写好 `text`（截图抄下来的原文）/`zh`（自己翻译，教材通常没有逐句翻译，跟其它
听力页一样的翻译尺度——信达为主不追求文学化）/`notes`（只在真正有语法点的
句子写，寒暄/短句留空，跟 `jp-listening-page` 一样的详略度标准），然后：

```bash
python tools/listening/refine_boundaries.py <这段音频> enriched_raw.json enriched_refined.json
python tools/listening/validate_boundaries.py enriched_refined.json enriched_final.json
```

生词表：不跑 `refine_boundaries.py`，直接用第2步里 Whisper 粗 segment 的时间戳
（去掉幻觉 segment 后按顺序一一对应），`char_times` 留 `null`（单词没有逐字符
跟读高亮，`ruby_html()` 退化成纯 furigana 展示，不影响使用）。`mondai` 统一填
"生词"，`question` 可以按教材自己的分组（比如"生词表1"/"生词表2"……）—照抄源
材料自己的分组标签，不用发明新的。

### 5. 多段音频怎么合成一个页面

`build_page.py` 只接受**一个** `audio_path` 参数（`cut_segments()` 对着这一个
文件用 `ffmpeg -ss/-t` 切每句），但教材天然是每个部分一份独立音频。做法：**先
把几段音频顺序拼接成一个文件**（用 ffmpeg 的 `concat` filter，不是 `concat`
demuxer——后者要求几个文件编码参数完全一致，比较脆弱，filter 版本更稳）：

```bash
ffmpeg -i 会话.m4a -i 课文.m4a -i 单词.m4a \
  -filter_complex "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]" -map "[out]" -b:a 128k \
  combined.m4a
```

拼接顺序要跟最终 tab 顺序一致。然后**把每段各自跑完 `refine_boundaries.py`/
`validate_boundaries.py` 产出的 `enriched_final.json`（这些文件里的时间戳都是
各自原始音频的本地坐标系，从0开始）按各自在 `combined.m4a` 里的偏移量整体平移**
（`start`/`end`/`char_times` 都要加上偏移量，偏移量＝前面几段音频的时长总和，
用 `ffmpeg -i <文件> 2>&1 | grep Duration` 量出来），平移完合并成一份
`enriched_combined.json`、重新分配连续 `id`，喂给 `build_page.py` 的 `<原始音频>`
参数就传 `combined.m4a`。

**关键原则：`refine_boundaries.py` 必须对着每段各自的原始音频单独跑，不能对拼接
后的 `combined.m4a` 跑**——那个脚本内部会对着传入的音频文件重新截取一段做
word-level 转写，如果传的是拼接文件、时间戳却是本地坐标系（没先平移），会截到
完全无关的音频位置；反过来如果先平移了时间戳再传拼接文件去跑 `refine_
boundaries.py`，则该脚本本身没有"平移量"的概念，同样会出问题。正确顺序是「各自
原始音频 + 本地时间戳」→跑完精修→平移→合并→拼接音频只在最后 `build_page.py`
这一步登场。

### 6. 生成页面

```bash
python tools/listening/build_page.py combined.m4a enriched_combined.json docs/private/<slug> \
  --title "标准日本语中级第N课：<课文主题>" \
  --subtitle "来源：《标准日本语》中级第N课（会话/课文/生词）。逐句配假名注音、中文翻译与语法笔记，播放时逐词跟读高亮，支持默写/填空练习，悬浮迷你播放器支持暂停/继续/循环。" \
  --password-hash <摘的哈希>
```

### 7. 本地测试、建/更新独立枢纽页、确认提交

1. `python -m http.server 8000`（`docs/` 目录下，`run_in_background: true`），
   打开 `http://localhost:8000/private/<slug>/` 检查：密码门、三个 tab 都能
   正常切换、点句卡片播放、跟读高亮、悬浮迷你播放器、右下角设置面板里的
   "練習モード"三个选项（跟读/默写/填空）都能用——默写按小题顺序解锁、填空
   能正确从 `notes` 里的「…」抓到语法点挖空（生词条目大概率不会被挖空，因为
   没有 `notes`，这是预期行为，不是 bug）。
2. `docs/private/textbook/index.html`——第一次跑这个 skill 时新建（复用
   `listening-page.css` 的 CSS 变量、`private-gate.js` 的密码门 SSO，参考
   `docs/private/index.html` 现有枢纽页的结构，但完全独立、不共用同一个
   HTML 文件），后续同系列教材的课直接在这个文件里加一张卡片。
3. `git status` 确认只有 `docs/private/<slug>/`、`docs/private/textbook/
   index.html` 的 diff，工作目录 `tools/listening/work/<slug>/` 下的中间产物
   （截图抄下来的 ground-truth 文本、Whisper 转写草稿、`enriched_*.json` 各
   阶段版本、`combined.m4a` 拼接音频）**不要提交**——这些是脚手架，历史上
   `tools/listening/work/` 下的内容从来没进过 git，这个 skill 也一样。
4. 提交前问用户要不要 commit/push——这是新 skill 的第一次真实运行，没有先例
   确认默认值，按"没有先例可循时要跟用户逐项确认"的通用规则来，跟
   `jp-meeting-listening-page` 处理真实录音时一样谨慎，不要假设"教材=官方
   内容=可以直接默认不问"。

## 常见坑

- **`refine_boundaries.py`/`validate_boundaries.py` 在 Windows 上打印非日语
  汉字（简体中文）的 mondai/question 标签会崩溃**——这两个脚本原本没有
  `transcribe.py` 那样的 `sys.stdout.reconfigure(encoding="utf-8")` 保护，
  Windows 控制台默认 cp932（Shift-JIS）编码，日语假名/汉字（比如"問題1"/
  "1番"）大多能编码，但简体中文特有字形（比如"话"的简体写法，繁体/日语写作
  "話"）不在 cp932 字符集里，一旦 mondai/question 标签用简体中文（这个
  skill 的 tab 标签"会话"/"课文"/"生词"就是简体中文，跟 JLPT/会议录音那两个
  skill 一直用的日语标签"問題1"/"会議"不一样），`print()` 到控制台直接
  `UnicodeEncodeError` 崩溃，即使对齐计算本身没问题——已经在两个脚本里补上
  跟 `transcribe.py` 一致的 UTF-8 stdout/stderr reconfigure，一次性修好，
  以后同类中文标签不会再触发。
- **截图导出文件名的时间戳顺序不等于阅读顺序**——见上面第1步，滚动截屏工具
  可能因为截了两张离得很近/回滚重截等原因导致文件名序号跟真实滚动位置不同步，
  排完序一定要跟第2步的 Whisper 粗转写做一次内容连贯性交叉验证，不要只信
  文件名排序。
- **中文旁白/场景说明不能当成 `.seg-card`**——默写/填空模式的实现假设了"每个
  `.seg-card` 一定有 `.seg-ja`"，硬塞一个没有日语原文的卡片会在这两个模式下
  表现异常（默写模式会要求用户"听写"一句空白/占位文本）。
- **生词条目不需要 `refine_boundaries.py`**——单词粒度的逐字符跟读高亮价值
  很低（一个词通常只有一两个音节，高亮意义不大），而 `refine_boundaries.py`
  对每个 question 分组要重新跑一次 word-level 转写，几十上百个单词逐一处理
  会明显拖慢流程；直接用 Whisper 粗转写的 segment 时间戳（去掉幻觉 segment
  后按顺序一一对应）就够用。
- **多段音频不能直接把 `enriched.json` 时间戳按比例硬凑**——见上面第5步，
  必须先在各自本地坐标系里跑完 `refine_boundaries.py`，再统一平移合并，
  顺序不能反。
- 其余（跟读高亮实现、迷你播放条样式、密码门/SSO 设计、`build_page.py` 的
  mondai+question 分组渲染规则、默写/填空练习模式的具体交互）跟另外两个
  skill 完全共用同一套工具代码和共享 JS/CSS，遇到问题直接查那两份 SKILL.md
  的"常见坑"一节，不在这里重复。
