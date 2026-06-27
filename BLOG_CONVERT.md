# 博客转换流程

素材来源：`../red2/`

---

## 一、发布时间

优先使用 git 提交时间（最准确）：

```bash
git -C ../red2 log --diff-filter=A --format="%ad" --date=short -- "文件名"
```

- 如果文件是**单独提交**的，用该提交日期
- 如果文件在**批量提交**（如 2024-02-05 的大批量初始提交）中，则参考文件名/内容推断发布时间，或按内容中提到的时间点估算
- 实在无法确定的，用文件系统修改时间，或留当前日期

---

## 二、txt 文件转博客

### 格式特点
- `<<<` / `>>>` 是视频镜头提示，转博客时**全部删除**
- 口语化、碎片化，需适当补充过渡句，但保留原有语气和视角
- 部分文件只有大纲/要点（B/C 档），需扩写

### 转换步骤
1. 读取 txt 内容
2. 去除 `<<<` `>>>` 标记
3. 理清结构，拆分 H2 章节
4. 补写引言段（1-2 句点出主题）
5. 补写结尾段（总结或行动建议）
6. 生成 HTML，套用博客模板（见下方模板说明）
7. 更新 `docs/blog/index.html` 和 `docs/index.html` 首页预览

### 质量分级
| 档次 | 特征 | 处理方式 |
|------|------|---------|
| A 档 | 内容完整、有叙事弧线 | 直接转，少量润色 |
| B 档 | 有框架，内容偏薄 | 结合同主题 pptx 或其他 txt 补充 |
| C 档 | 仅要点/碎片 | 大幅扩写，或与其他文件合并 |

---

## 三、pptx 文件转博客

### 提取文字

```python
from pptx import Presentation
prs = Presentation("文件.pptx")
for i, slide in enumerate(prs.slides):
    for shape in slide.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                t = para.text.strip()
                if t and t not in ['Tokyo Chinese', 'TokyoChinese']:
                    print(f"[Slide {i+1}] {t}")
```

> 使用 Python 3.9：`C:\Users\leicai\AppData\Local\Programs\Python\Python39\python.exe`
> 输出时设置 `PYTHONIOENCODING=utf-8`

### 提取图片

```python
import os
from pptx import Presentation
prs = Presentation("文件.pptx")
os.makedirs("tmp_imgs", exist_ok=True)
for i, slide in enumerate(prs.slides):
    for j, shape in enumerate(slide.shapes):
        if shape.shape_type == 13:  # Picture
            img = shape.image
            fname = f"slide{i+1}_img{j}.{img.ext}"
            with open(f"tmp_imgs/{fname}", "wb") as f:
                f.write(img.blob)
```

### 图片处理
- 查看提取出的图片，判断是否有博客价值
- **可用**：架构图、流程图、对比图、AI 生成的配图
- **不可用**：纯装饰背景、模糊图、水印图、私人信息截图
- 可用的图片复制到 `docs/images/`，命名规则：`主题-描述.png/jpg`
- 在文章中用 `<figure class="post-img">` 包裹，附 `<figcaption>` 说明

---

## 四、HTML 博客模板

文件位置：`docs/blog/posts/文章名.html`
路径命名：英文短横线，如 `dispatch-architecture.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>文章标题 · 蔡磊</title>
  <meta name="description" content="一句话摘要" />
  <link rel="stylesheet" href="../../css/style.css" />
</head>
<body>

  <nav class="nav">
    <div class="nav-inner">
      <a href="../../index.html" class="nav-logo">蔡磊</a>
      <ul class="nav-links">
        <li><a href="../../index.html#about">关于</a></li>
        <li><a href="../../index.html#skills">技能</a></li>
        <li><a href="../index.html" class="active">博客</a></li>
        <li><a href="../../index.html#contact">联系</a></li>
      </ul>
    </div>
  </nav>

  <div class="post-page">
    <a href="../index.html" class="back-link">← 返回博客</a>

    <div class="post-page-header">
      <h1>文章标题</h1>
      <div class="post-author">
        <img src="../../images/photo-3.jpg" alt="蔡磊" class="post-author-avatar" />
        <div class="post-author-info">
          <span class="post-author-name">蔡磊</span>
          <span class="post-author-title">在日IT技术者 · 零代码开发</span>
        </div>
      </div>
      <div class="post-page-meta">
        <span>YYYY-MM-DD</span>
        <span class="post-tag">分类标签</span>
      </div>
    </div>

    <div class="post-body">
      <!-- 正文内容 -->
    </div>
  </div>

  <footer>
    <p>© 2026 蔡磊 · 用心记录，持续成长</p>
  </footer>

  <script src="../../js/float-photos.js" data-base="../../images/"></script>
</body>
</html>
```

---

## 五、更新索引

每篇文章发布后，同步更新两个文件：

### `docs/blog/index.html`
在 `.post-list` 中**顶部**插入新条目（最新的在最上面）：

```html
<a href="posts/文件名.html" class="post-item">
  <div class="post-date-badge">
    <span class="post-date-month">Jan</span>
    <span class="post-date-day">01</span>
  </div>
  <div class="post-info">
    <div class="post-title">文章标题</div>
    <div class="post-subtitle">分类 · 标签</div>
  </div>
  <span class="post-arrow">→</span>
</a>
```

### `docs/index.html`
首页只保留**最新 2 篇**预览，格式同上。

---

## 六、提交规范

```bash
git add docs/
git commit -m "Add post: 文章主题简述 (YYYY-MM-DD)"
git push origin main
```

---

## 七、已转换列表

| 文章 | 来源 | 发布日期 | 文件 |
|------|------|---------|------|
| AI+低代码：一场正在发生的「羊吃人」 | txt | 2026-06-25 | sheep-eating-people.html |
| 日本IT派遣的五层架构：你的钱是怎么被瓜分的？ | pptx | 2024-06-24 | it-dispatch-architecture.html |
| 三月退场潮：日本IT派遣的财政年度密码 | txt | 2024-03-08 | dispatch-exit-season.html |
| 日本IT技术者的三条出路：你选哪条？ | txt | 2024-05-16 | ultimate-goal.html |
| 前后端三十年战争：JavaScript 的逆袭之路 | txt | 2024-02-06 | frontend-vs-backend.html |
| 日本IT派遣技术栈全解：你该学什么？ | txt | 2024-02-05 | tech-stack-guide.html |
| 日本IT薪资水平，你达标了吗？ | txt | 2024-02-05 | salary-benchmark.html |
| 日本IT派遣面试潜规则：会社从来不告诉你的那些事 | pptx | 2024-02-05 | interview-secrets.html |
| 中日IT面试乱象：从灵魂拷问到拔出萝卜带出泥 | pptx | 2024-02-05 | interview-chaos.html |
| 2030年日本IT人才缺口79万：谁能抓住这波红利？ | pptx | 2024-02-05 | who-benefits-most.html |

## 八、待转换队列

red2 目录中已全部完成转换。如有新素材，按上述流程继续处理。
