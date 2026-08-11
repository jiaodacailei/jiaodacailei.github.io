# textbook-sjp-zg-l14 操作日志

补记（本文件是后来才建立的，以下是根据当天会话回溯整理的记录，格式不如
后续条目详细）。

## 生成与初次发布

- 源材料：《标准日本语》中级第14课（恩師、日本の就職活動），会话/课文/
  生词/単語テスト四个tab，88个生词条目。这一课源材料截图首次自带官方
  中文翻译（会话/课文），直接采用，未自行翻译。
- 生词表沿用 l13 的"整段word-level转写 + 一次性 `align_group()` 对齐"流程。
- furigana 全量复核（`audit_furigana.py --all`）发现3处新读音坑（"の日"→ひ、
  "後にする"→あと、"1次/2次/3次"→じ），已修入 `build_page.py` 的
  `_resolve_hira()`。

## 会话/课文边界修复（多轮）

- 用户反馈多处边界问题（王さん开头被切、これ开头被切、広告代理店の仕事
  开头被切、いいえ开头被切、まだ开头被切等），逐一用 RMS 能量剖面
  （10ms帧）+ word-level 转写核实修复。
- 发现原始卡片切分粒度过粗（一张卡片装了多句），改成严格按语法句
  （"。"/"？"/"！"）切分，重新走了一遍第2~6步（17句→32句→30句会话，
  10句→19句课文）。
- 拆分重建后同一批边界bug复现（"これ"再次开头被切），确认"拆句本身不能
  自动修复对齐算法的系统性偏差"。
- 发现"ええ"这个应答词被反复漏判/误判两轮，最终靠 word-level 转写核实
  真实身份才定位到位置。
- 手动订正边界在后续重新跑 `refine_boundaries.py` 时被静默覆盖回错误值
  两次（id1/id2、id7）——由此建立 `apply_manual_overrides.py` 机制。

## 工具建设

- 新增 `tools/listening/audit_boundaries_rms.py`（RMS边界审计工具）。
- 新增 `tools/listening/apply_manual_overrides.py`（人工订正边界持久化，
  防止重新对齐时静默覆盖）。
- 新增 `tools/listening/patch_sentence_tokens.py`（批量重算 data.js 里
  句子的跟读高亮 tokens）。
- 新增 `tools/listening/recut_clips.py`（按 id 直接从合并音频重切单个
  片段，避免手工换算偏移量出错）。

## 生词表音频边界问题（发布后多轮反馈）

- 用户报告"ごく/焦る/ブラック/海面"4个生词边界不准，逐一用 RMS+word-level
  核实修复，其中"ごく"是 `align_group()` 真实对齐偏差，其余3个确认是
  `trim_clip_silence.py` 裁剪过猛导致内容缺失。
- 用户报告"採用試験"边界不准，修复时顺藤摸瓜用 `faster_whisper` 的
  `info.duration` 发现磁盘文件时长跟 `enriched_combined.json` 记录的原始
  边界大范围对不上——**88条生词里86条被 `trim_clip_silence.py` 动过**，
  批量转写+带上下文交叉核实后确认十几条内容被真的裁没。
- 修复方式：83条（排除已单独修正精确边界的5条）直接用 `recut_clips.py`
  从合并音频按 `enriched_combined.json` 记录的原始（裁剪前）边界重新切，
  跳过再次裁剪静音。
- 新增 `tools/listening/check_clip_drift.py`（磁盘文件实际时长 vs
  `enriched.json` 期望时长比对工具），把这次的诊断步骤固定成可复用命令。
- 修复"茶色い"注音被截断成"ちゃ"的bug（`_split_kana_segments()` 对"色"
  这类2拍训读字的送假名锚点搜索起点算错），补进 `_KANJI_MIN_MORA` 表。
- 发现并修复 `audit_furigana.py` 对生词表长期零覆盖的bug（读的是
  `--data-driven` 模式下根本不会被用到的 `furigana` 字段）——这个bug
  也解释了为什么"茶色い"这类问题此前的全量复核都没抓到。
