# 博客转换队列

> 本文件记录 `../red2/` 中所有素材的转换状态。
>
> **转换规范**：参见 `BLOG_CONVERT.md`
> **HTML 模板**：同上，路径 `docs/blog/posts/`

---

## 转换进度统计（截至 2026-06-27）

- ✅ 已完成：**64 篇**
- 🚫 跳过：约 15 个（非博客内容，见下方跳过列表）
- ⬜ 待转：**0 篇**（red2 目录已全部处理完毕）

---

## 已完成（64篇）

按批次记录，详细文件名见 `docs/blog/posts/` 目录。

### 批次 1（初始 10 篇）
| 源文件 | 发布日期 | 输出文件 |
|--------|---------|---------|
| 日本IT派遣【羊吃人】.txt | 2026-06-25 | sheep-eating-people.html |
| 日本IT派遣架构.pptx | 2024-06-24 | it-dispatch-architecture.html |
| 日本IT派遣退场季.txt | 2024-03-08 | dispatch-exit-season.html |
| 日本IT派遣前后端的爱恨情仇.txt | 2024-02-06 | frontend-vs-backend.html |
| 日本IT派遣技术栈比较.txt | 2024-02-05 | tech-stack-guide.html |
| 日本IT的终极目标.txt | 2024-05-16 | ultimate-goal.html |
| 日本IT薪资水平，你达标了吗.txt | 2024-02-05 | salary-benchmark.html |
| 日本IT派遣面试潜规则.pptx | 2024-02-05 | interview-secrets.html |
| 中日IT面试乱象.pptx | 2024-02-05 | interview-chaos.html |
| 什么人来日本做IT价值增量最高.pptx | 2024-02-05 | who-benefits-most.html |

### 批次 2–6（追加 54 篇）
涵盖 geek/、十月待机/、根目录 txt、pptx 独立转换等全部素材。
输出文件完整列表：`docs/blog/posts/` 目录下所有 `.html` 文件。
数据索引：`docs/blog/posts.json`（64 条，含 slug / title / tags）。

---

## 跳过列表（不适合转为博客）

| 文件 | 原因 |
|------|------|
| 十月待机/自我介绍.txt | 求职自我介绍模板，非博客内容 |
| 十月待机/日本IT派遣：自我介绍详解.pptx | 同上 |
| 上流工程/ 全部 | 日文系统设计培训教材，非博客定位 |
| job/ 全部 | 招聘JD/数据库职位描述 |
| IT培训及日本就业合同.docx | 合同文件 |
| 反模式.docx | 技术参考文档 |
| report/日本IT.xlsx | 数据表格 |
| 2014本命年 | 个人文件 |
| geek/早餐.txt | 内容太短/过于日常 |
| geek/如何省钱（目录）| 目录为空 |
| geek/社长哭了（目录）| 目录为空 |
| IT入场培训.pptx / IT入场培训2.pptx | 内部培训材料，非公开博客内容 |
| README.md / README.en.md | 项目说明文件 |

---

## 新素材处理

如有新素材（新的 txt / pptx），按以下流程：

1. 参照 `BLOG_CONVERT.md` 转换
2. 新文章加入 `docs/blog/posts.json` 顶部
3. 更新 `docs/blog/index.html` 和 `docs/index.html` 首页预览
4. 在本文件"已完成"表格中追加记录
