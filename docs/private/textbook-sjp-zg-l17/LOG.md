# 第17课制作日志

来源：《标准日本语》中级第17课（会话「日本取材の成果」/课文「北京の顔」/生词），
会话/课文/生词各一段独立录音，来自截图+音频材料。

## 流程

1. 读截图抄原文（会话30句、课文21句7段、生词137个词，id 1-51为会话+课文，52-188为生词）。
2. `transcribe.py` 打时间戳草稿；生词表因语速较快，沿用 l13/l14 建立的"整段
   word-level转写 + 一次性 `align_group()` 对齐全部生词"方案，一次对齐成功。
3. `refine_boundaries.py` 精修边界。课文7段草稿窗口最初按手工估算的粗跨度切分，
   3处（第3/4/6段）因窗口太紧被切错，改成对所有题目分组统一做"两端各加宽
   5~6秒、clamp到音频总长"的防御性扩窗后重新对齐修复——这个通用修法一次性
   抓出了3处，而不是只修最初注意到的那一处。
4. `validate_boundaries.py` 清理，`audit_boundaries_quietpoint.py --fix` 批量修正
   静音点边界（会话/课文/生词三段分别跑，报告见 `quietpoint_dialogue.txt`/
   `quietpoint_text.txt`/`quietpoint_vocab.txt`）。生词表因词间停顿短，136个
   内部边界里28处被标记"可疑"（rise>6dB且at_B>-40dB），发布前抽样用拼接
   相邻内容重新转写核实，确认切分点跟真实内容对得上，不是误切。
5. `merge_sections.py` 合并三段音频+enriched.json。
6. 合并后发现会话 id7「これは，就職活動を…」附近的中文旁白是**有声播出**的
   （不是静音，这一课的新场景），`align_group()` 把 id7 末尾标点错误对齐到
   旁白音频里，导致 `end` 边界把旁白吃进了片段。用50ms精细RMS能量剖面+
   前后片段重新转写定位真实起止，手动订正 `end` 为24.80并clamp `char_times`，
   `recut_clips.py` 单独重切这一个片段，`patch_sentence_tokens.py` 同步
   `data.js`。
7. `audit_furigana.py`（高危字扫描 + `--all` 全量）人工复核。发现并修了
   `tools/listening/build_page.py` 的 `_resolve_hira()` 一个系统性bug：用
   "返回值是否等于pykakasi默认读音"来判断"规则有没有生效"，在规则的正确
   答案恰好和默认值一样时会误判成"没生效"（这一课的触发场景是"29本/459本"
   这类"数字+本"的量词读音——本该按结尾数字2/4/5/7/9固定读ほん，但当默认值
   碰巧也是ほん时判断逻辑会出错）。改成显式 `None` 哨兵值，`audit_furigana.py`
   的 `_scan_live_text()` 同步更新。全站689句回归测试（git stash A/B对比
   `tokenize_ja()` 输出）确认0处影响，不影响已发布内容。
8. `build_vocab_quiz_data.py` 生成 `quiz_data.json`（137条）。
9. `build_page.py --data-driven --quiz-json` 生成页面。
10. 生成后人工复核发现两处遗留问题并直接改 `data.js`：
    - 「銭市胡同」「磨刀胡同」这两个中文地名，生词条目按中文音读（チェンシー/
      フートン、モータオ/フートン）跟会话里的读音手工统一。
    - 补充 `clauseBounds`（供"选段复读"功能用）——18句有多个语法小句的句子，
      从 `enriched_combined.json` 算好的分句时间戳写回 `data.js`。

## 发布前验证

- `verify_clips.py` 全量188条：EMPTY 5、LOW_SIMILARITY 27、LEAD_SILENCE 5。
  抽样13条（覆盖三类问题+quietpoint标记过的生词边界）用"拼接相邻内容重新
  转写"+部分RMS能量剖面核实，全部确认是Whisper对短促孤立生词/独立读音
  估算工具本身的局限造成的误报，没有发现真实的边界或内容错位问题。
- 全量188个音频文件磁盘实际时长 vs `enriched_combined.json` 期望时长逐一
  比对，0处偏差（排除"生成后被其它操作静默改过"的可能）。
- 本地起server人工测试：会话/课文/生词/単语テスト四个tab播放、跟读高亮、
  默写模式、填空模式、単语テスト的填空题/听音写假名题/对错计数都正常。
  选段复读功能点击选段、起播位置都正确；"是否精确停在小句边界"这一点受限于
  自动化浏览器测试环境（标签页在后台、`requestAnimationFrame`不触发）没能
  验证，代码逻辑本身检查过是对的。
- `git status` 确认只有预期改动（本课新增 + `build_page.py`/`audit_furigana.py`
  两个共享文件的furigana修复），没有意外改动。

## 遗留

- 本课没有发现需要修的真实bug，未发布任何已知问题。
