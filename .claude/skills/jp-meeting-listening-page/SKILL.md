---
name: jp-meeting-listening-page
description: Turn a real Japanese workplace meeting/call recording (定例会 etc., not a JLPT test) into a password-protected, unlisted listening-practice page on this site — a flat list of hand-picked credible sentences with furigana, Chinese translation, grammar notes, word-level read-along highlighting, and the shared floating mini-player. Use when the user gives you a Japanese meeting/call recording and asks for a listening drill page, or references "定例会"/"会议录音" listening material. For JLPT-style structured test audio (問題1〜5 with tabs), use the jp-listening-page skill instead.
---

# 日语会议录音精听页生成

给一段真实的日语工作会议/电话录音，生成一个密码保护、不进导航的**扁平列表**精听页面：
从嘈杂的原始转写里筛出真正可信、值得当学习材料的句子，配假名注音 + 中文翻译 + 语法
笔记，播放时逐词跟读高亮，右下角常驻悬浮迷你播放器统一控制播放/暂停/循环/停止。

这个 skill 是 `jp-listening-page` 的姊妹篇，**工具链、页面结构、密码门/SSO、跟读高亮
全部直接复用**，不重新实现。区别只在于内容性质和处理流程：

- `jp-listening-page` 处理的是结构化的 JLPT 真题（問題1〜5 口播编号、tab 切换、
  答案解析），核心难点是"边界识别 + 两轮 Agent 按大题产出标准答案"。
- 这个 skill 处理的是**没有结构、充满噪音的真实录音**（串话、电话保留音、跟内容
  无关的闲聊、Whisper 幻觉），核心难点不是分组，而是**从转写里挑出哪些句子真正
  可信、值得保留**——所以流程里没有 tab、没有 mondai 分组、没有"两轮 Agent"，
  换成一道**筛选**工序。

工具/页面结构的完整文档（`transcribe.py`/`refine_boundaries.py`/`validate_
boundaries.py`/`build_page.py`/`private-gate.js`/枢纽页 SSO 等）见 `jp-listening-page`
skill 的"工具在哪"和"枢纽页与单点登录"两节，这里不重复，只写这个 skill 特有的默认值
和流程。

## 参数

输入参数是**音频文件路径**（必填，位置参数），比如：

```
/jp-meeting-listening-page C:\Users\xxx\定例会260714.m4a
```

标题、密码、输出 slug、是否进枢纽页——默认直接按下面"0. 默认值怎么定"处理，不用
逐项跟用户确认。

## 已跑过的真实案例

- `docs/private/dingliehui-260327/` — 第一个案例，也是这个 skill 流程的原型（当时
  还没有独立 skill，是在 `jp-listening-page` 的"简单流程"分支里跑的）。一段嘈杂的
  工作会议录音，从约50段原始转写里人工筛出14句可信内容，无 mondai/question 分组，
  扁平列表。这14句在原录音里彼此不相邻（中间隔着大量被筛掉的嘈杂闲聊），处理时给
  每句一个独立的 question 标签、当成14个独立单句"题目"分别跑 `refine_boundaries.py`
  （千万不能当成一个连续整体对齐，会把中间大段无关内容也拖进对齐计算，边界会跑偏），
  生成页面前统一清空 question 标签，让它们渲染成一个扁平列表。已按当前标准（SVG
  图标、贴底迷你播放条、跟读高亮、外边界重定位）重新生成过。已加入枢纽页。
- `docs/private/dingliehui-260714/` — 这个独立 skill 建立后跑的第一个案例。302段
  原始转写、23分钟仓库机器人运维会议，专业术语密度比260327高得多，筛选时把充满
  内部系统黑话、转写本身也经常出错的大段技术细节全部剔除，只保留三段完全能听懂
  的自然对话场景（账号登录被锁、日程延期确认、工时填报办公室拌嘴），22句、3个
  question 分组（组内相邻句子共享分组，组间跨场景不共享）。同事真实姓名（石井/
  阿部/鈴木/慎太郎）按默认策略原样保留未脱敏。**过程中发现并修好了一个共享工具
  的真 bug**：`add_furigana.py` 输出的是不带 `sentences`/`mondai`/`question`
  包装的裸数组，直接喂给 `refine_boundaries.py`/`build_page.py` 会因为取不到
  `data["sentences"]`/`s["mondai"]` 而报错——这两个 skill 的文档都描述过"跟下游
  格式兼容"，但从 `build_page.py` 改成按 mondai+question 分组渲染之后就没再
  更新过，一直没人真正跑过这条路径。已修好（见下面"常见坑"），现在
  `add_furigana.py` 输出的就是正确的 `{"sentences":[...],"questions":[]}`
  格式，可以直接接 `refine_boundaries.py`。已加入枢纽页。

## 整体流程

### 0. 默认值怎么定

不逐项跟用户确认，除非内容/风险明显超出下面这些默认值覆盖的范围：

- **slug**：`dingliehui-<YYMMDD>`，日期从文件名里解析（"定例会260714.m4a" →
  `dingliehui-260714`）。文件名不含日期或格式对不上时才问用户。
- **标题**：`日语听力精听：定例会 <YYMMDD>`；**副标题**：注明来源文件名 + 筛选方式
  （原始约N段，保留M段）+ 功能点（假名注音/中文翻译/语法笔记/跟读高亮/悬浮播放器），
  照抄 dingliehui-260327 的文案风格替换数字即可。
- **密码**：复用全站统一的密码哈希（跟枢纽页、N2 系列共用一份），从 `docs/private/
  index.html` 里 `<div id="gate" data-hash="...">` 摘，`build_page.py` 用
  `--password-hash` 传，不用问用户要明文。
- **进枢纽页**：默认**加入**（这条从 dingliehui-260327 开始固定为这个 skill 的
  默认值，不用每次问——跟 `jp-listening-page` 里"要不要问"的默认策略不同，那边默认
  不问是因为处理的是官方真题，这边默认加入是因为已经有明确先例、用户已经表态这类
  内容就是要放进枢纽页）。
- **敏感信息（同事姓名/客户名/具体项目细节/金额）**：默认**保留原文，不脱敏**——
  这是用户明确确认过的默认值，密码门 + 不进站内导航 + `noindex` 已经是默认的隐私
  防线，不用额外脱敏。如果某次录音明显涉及需要格外谨慎的内容（比如客户抱怨、人事
  纠纷、未公开的商业决策），生成完之后主动跟用户提一句，让用户自己决定要不要在
  commit 前手动改，而不是默认帮用户改。
- **处理范围**：默认全部转写、全部通读筛选，不用先跑一段"试跑"再问。
- **笔记详略度**：跟 `jp-listening-page` 一样，只在真正有语法/词汇点的句子写笔记，
  寒暄/语气词留空。

### 1. 转写

```bash
python tools/listening/transcribe.py <音频文件> <输出.json> --model medium
```

`run_in_background: true` 跑。真实会议录音比 JLPT 录音更嘈杂（多人交叉说话、电话
保留音、环境噪音），Whisper 幻觉概率更高，转写完**必须**通读一遍，不要假设转写准确。

### 2. 筛选（这个 skill 的核心步骤，取代 jp-listening-page 的"两轮 Agent"）

通读转写全文，标出真正可信、值得当学习材料保留的句子——排除：明显的 Whisper 幻觉
（安静片段编出的无关句子）、无法辨识的串话/重叠语音、纯口头禅或过短的语气词、跟
主题无关的插科打诨（除非确实是自然口语值得学的表达）。这一步可以自己通读判断，也
可以丢给一个 Agent 辅助初筛、自己复核最终名单——录音量不大（十几分钟到几十分钟）
时人工通读往往比写筛选 prompt 更快更准。

筛选结果记录成一个列表，每项 `{"start":.., "end":.., "text": "原始转写（待人工订正）"}`
（时间戳来自转写结果，先不用管准不准，第4步会重新精修）。跟 dingliehui-260327 一样，
预期这些句子在原录音里大概率不相邻。

拿到筛选名单后，参考原始转写通读订正每句的日语原文（修掉明显的同音字错误），补上
完整中文翻译、语法笔记（只在真正有语法点时写）——量少的话自己写，量大的话可以丢给
一个 Agent 批量处理，输出 JSON 数组：
`{"start":.., "end":.., "text"（订正后的日语原文）, "zh"（中文翻译）, "notes"（语法/
词汇笔记，没有就留空字符串）}`。

**如果筛出来的两句在原录音里紧挨着、内容上也是连续的一段对话**（比如同一个人一句话
被转写切成两段，或者一问一答紧挨着），可以合并成一句或者保留为相邻两句——不强制
拆到"一句一题"的粒度，但**不相邻的句子之间绝不能共享同一个 question 分组**，见
下一步。**遇到不确定的专业术语/内部系统黑话（不是明显的同音字错误，而是真的听不
准、猜不出该怎么写的行业黑话）时直接从筛选名单里剔除，不要硬猜——猜错了比漏选
更糟**（dingliehui-260714 案例：一段仓库机器人运维内部会议，充斥着大量内部系统
术语和机器人操作黑话，转写本身也经常在这些术语上出错，最终决定只保留三段能完全
听懂、跟专业黑话无关的自然对话场景——账号登录被锁、日程延期确认、关于填报工时的
办公室拌嘴——302 段原始转写里最终只留了22句，比 dingliehui-260327 约28%的保留率
更低，这是内容本身专业术语密度决定的，不代表流程有问题）。

### 3. 每句当独立单句"题目"，精修边界

给筛出来的每一句分配一个**唯一的 question 标签**（比如按顺序编号 `"1"`,`"2"`,...），
`mondai` 字段随便给一个固定值（比如 `"会議"`，反正最后会清空不显示）。这是从
dingliehui-260327 踩出来的硬性要求：**不相邻的句子如果共享同一个 question 分组，
`refine_boundaries.py` 会把它们当一段连续对话整体对齐，中间被筛掉的大段无关内容
也会被拖进对齐计算，边界跑偏**（真实反馈："每句话前面/后面都有一大段空白，根本
没对齐"）。

组装出 `enriched.json`（`{"sentences":[{"mondai":"会議","question":"1","start":..,
"end":..,"text":..,"zh":..,"notes":..}, ...], "questions":[]}`，questions 数组留空
即可，这个流程不需要按题概览/答案）。有了假名注音需求的话可以复用 `merge_groups.py`
里的 `to_ruby_html()` 逻辑，或者直接调 `add_furigana.py`（见 `jp-listening-page`
skill 工具列表，输出格式跟这里兼容）。

然后照常跑精修 + 校验：

```bash
python tools/listening/refine_boundaries.py <原始音频> enriched.json enriched_refined.json
python tools/listening/validate_boundaries.py enriched_refined.json enriched_final.json
```

跑完之后，**把每句的 `question` 字段统一清空成空字符串**（或者跟 dingliehui-260327
一样的处理方式），让 `build_page.py` 把它们渲染成一个扁平列表而不是带小题标题的
分组——具体清空方式：读 `enriched_final.json`，遍历 `sentences` 数组把每项的
`question` 改成 `""`，`mondai` 也可以统一改成空或者一个不显示的占位值（`build_page.py`
按 `(mondai, question)` 分组渲染 `h2`/`h3`，全部句子给同一个空分组就只会渲染一层
`.seg-card` 列表，不产生 `h2`/`h3`/tab/目录）。

### 4. 生成页面

```bash
python tools/listening/build_page.py <原始音频> enriched_final.json docs/private/<slug> \
  --title "日语听力精听：定例会 <YYMMDD>" \
  --subtitle "来源：<原始文件名> 自动转写后人工筛选出可信段落（原始约N段，保留M段）。逐句配假名注音、中文翻译与语法笔记，播放时逐词跟读高亮，悬浮迷你播放器支持暂停/继续/循环。" \
  --password-hash <从 docs/private/index.html 摘的哈希>
```

### 5. 本地测试、加入枢纽页、确认提交

1. `python -m http.server 8000`（在 `docs/` 目录下，`run_in_background: true`），
   打开 `http://localhost:8000/private/<slug>/` 检查：密码门、扁平列表渲染正常（
   没有意外出现 tab/h2/h3）、点句卡片播放、跟读高亮、悬浮迷你播放器全部功能、
   手机宽度下播放条贴底贴边。
2. 按"0. 默认值怎么定"里的规则加进 `docs/private/index.html` 枢纽页卡片列表（不用
   跟用户确认，这是这个 skill 的固定默认值）。**不要**加进 `docs/blog/`、
   `docs/index.html` 或站内导航——枢纽页之外仍然保持不公开。
3. `git status` 确认没有把原始录音文件（用户本地路径下的源文件）带进 staging，
   只应该有 `docs/private/<slug>/` 下的短音频片段、页面文件、枢纽页的 diff。
4. 提交前问用户要不要 commit/push——真实工作会议录音涉及的隐私风险比 JLPT 官方
   真题更高（真实同事的声音和发言内容），这一步不能因为"已经有默认值"就跳过，
   跟 `jp-listening-page` 一样必须每次问。

## 笔记怎么写

跟 `jp-listening-page` 一样：只在真正有语法/词汇点的句子上写，寒暄/语气词留空；
有内容的笔记大致包含用法要点 + 1~2 个值得学的语法点，不用写成小作文。这个流程没有
"小题概览/答案"（`questions` 数组留空），不用像 JLPT 场景那样额外写 `overview`/
`answer`。

## 常见坑

- **不相邻的句子不能共享 question 分组**——见上面第3步，这是这个流程最容易踩的坑，
  后果是边界大范围跑偏（真实反馈"每句前后一大段空白"），不是小偏差。
- Whisper 幻觉在嘈杂会议录音里比 JLPT 录音室音质更常见，筛选阶段本来就是要把这些
  过滤掉，但精修阶段（`refine_boundaries.py`）如果传进去的筛选名单里混进了幻觉句，
  产出的页面会播放一句根本不存在的话——筛选环节的通读核对不能省。
- **专业术语/内部系统黑话不要硬猜着"订正"**——`jp-listening-page` 那边"修掉明显
  同音字错误"的前提是听得懂原意、只是字形被听岔了（比如"問題2"听成"問題に"）；
  真实工作会议里大量出现的是说话人自己内部系统的专有名词、黑话、缩写，这类内容
  连原文本身是什么都不确定，硬着头皮"订正"等于编造，筛选阶段直接从名单里剔除
  （真实案例见 dingliehui-260714，一段仓库机器人运维会议里这类内容占了绝大部分，
  最终保留率只有约7%，明显低于 dingliehui-260327 的28%，是内容性质决定的，不是
  筛选标准变严了）。
- **`add_furigana.py` 曾经输出格式跟下游不兼容，已修好**：旧版本输出一个不带
  `sentences`/`mondai`/`question` 包装的裸 JSON 数组，`refine_boundaries.py` 按
  `s["mondai"]`/`s["question"]` 分组、`build_page.py` 读 `data["sentences"]`都会
  直接报错取不到字段——这是 `build_page.py` 改成按 mondai+question 分组渲染之后
  遗留的文档/实现不同步，两个 skill 的 SKILL.md 都写了"输出格式兼容"但从没人真的
  跑过这条路径验证过（`jp-listening-page` 案例走的都是两轮 Agent + `merge_
  groups.py`，没人用过 `add_furigana.py` 这条简化路径）。现在 `add_furigana.py`
  已经改成输出正确的 `{"sentences":[...], "questions":[]}`，`mondai`/`question`
  没传就给统一占位值，直接能接 `refine_boundaries.py`。
- 其余踩过的坑（`refine_boundaries.py` 的对齐算法演进史、`word_at()` 越界修复、
  切分点偏置、外边界重定位、跟读高亮实现、迷你播放条样式、密码门/SSO 设计）跟
  `jp-listening-page` 完全共用同一套工具代码，遇到问题直接查那份 SKILL.md 的
  "常见坑"一节，不在这里重复。
