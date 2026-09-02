# Office Diff Action

**在合并前，看清 Word 和 PowerPoint 到底改了什么。**

[English](README.md) · 简体中文

[![Test](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml/badge.svg)](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

GitHub 可以保存 `.docx` 和 `.pptx`，但普通代码差异无法告诉审阅者：文字是否发生了重排、
某一页是否多出来了、幻灯片版式是否错位，或者文档是否已经无法正常渲染。

Office Diff 会把每个发生变化的页面或幻灯片生成为“修改前 / 修改后 / 差异”三联图，
同时输出从 Office Open XML 中提取的文字差异，以及便于自动处理的结构化报告。

![Office Diff 演示](assets/demo/page-001.png)

## 它能解决什么问题

- 在 Pull Request 中审查 Word、PowerPoint 的可视化变化；
- 发现文字重排、页数变化、版式漂移和渲染失败；
- 为评审、归档或后续质量门禁保留 HTML、Markdown 和 JSON 证据；
- 全程在 GitHub runner 内处理，原始文档不会发送给第三方服务。

目前支持 `.docx` 和 `.pptx`。本项目只负责审查差异，不编辑或生成 Office 文档。

## 在 Pull Request 中使用

在你的仓库中新建 `.github/workflows/office-diff.yml`：

```yaml
name: 审查 Office 文档变化

on:
  pull_request:
    paths:
      - "**/*.docx"
      - "**/*.pptx"

permissions:
  contents: read

jobs:
  office-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: 生成 Office 差异报告
        uses: zhuyep/office-diff-action@v1
        with:
          base-ref: ${{ github.event.pull_request.base.sha }}
          head-ref: ${{ github.event.pull_request.head.sha }}

      - name: 上传可视化报告
        uses: actions/upload-artifact@v4
        with:
          name: office-diff-report
          path: office-diff-report
```

工作流完成后，下载 `office-diff-report` 构件并打开其中的 `index.html` 即可审阅。

## 输出内容

- 无需服务器即可打开的静态 HTML 报告；
- 每页或每张幻灯片的修改前、修改后和差异三联图；
- 直接从 Office Open XML 提取的统一文字差异；
- 可供后续规则或脚本读取的 JSON 摘要；
- GitHub Actions 运行摘要。

报告目录结构如下：

```text
office-diff-report/
├── index.html          # 可视化审阅报告
├── report.md           # 可移植的 Markdown 报告
├── summary.json        # 便于自动处理的摘要
└── documents/
    └── .../
        ├── base/       # 修改前页面
        ├── current/    # 修改后页面
        └── diff/       # 三联差异图
```

## 本地使用

本机需要安装 LibreOffice 和 Poppler，并确保它们位于 `PATH` 中：

```bash
python -m pip install .
office-diff compare before.pptx after.pptx --output office-diff-report
```

渲染失败时命令会返回非零状态。文字提取会尽可能继续执行，让报告保留已有证据，
而不是悄悄忽略失败。

## 参数

| 参数 | 默认值 | 作用 |
|---|---|---|
| `base-ref` | 必填 | 基准提交或 Git 引用 |
| `head-ref` | `HEAD` | 待审查提交或 Git 引用 |
| `output-dir` | `office-diff-report` | 报告输出目录 |
| `dpi` | `110` | 渲染分辨率 |
| `pixel-threshold` | `16` | 忽略轻微像素渲染噪声 |
| `allow-render-errors` | `false` | 出现渲染错误时是否仍让工作流成功 |

## 设计原则

- **渲染结果是证据，不是绝对真值。** 同一次比较的两侧使用同一发布容器，
  但复杂文档在 LibreOffice 与桌面版 Microsoft Office 中仍可能出现分页差异。
- **原始文档不离开 runner。** Action 不把输入文件上传给任何第三方服务；
  是否上传生成后的报告，由你自己的工作流决定。
- **正常修改不会让工作流失败。** Office 文件在 PR 中发生变化是正常行为；
  只有渲染或提取失败才默认返回错误，质量门禁可以读取 `summary.json` 自行判断。
- **先提供可复核证据，再考虑评分。** 本项目不会用不透明的 AI 分数替代人工审阅。

## 当前限制

- 报告以工作流构件形式提供，还不是 PR 内联图片画廊；
- 暂不支持 Git LFS 中的 Office 文件、加密文件和旧版 `.doc`/`.ppt`；
- 容器中缺失的字体会被替换；
- 页面和幻灯片目前按位置匹配，尚不能识别语义上的移动；
- LibreOffice 的分页结果可能与桌面版 Microsoft Office 不完全一致；
- 单次最多处理 20 个变更文档，每个文档最多 200 页或幻灯片；
- 渲染 DPI 限制为 36–300，并设有文件、像素和总报告体积上限，以约束不可信 PR 的资源消耗。

如果遇到渲染问题，请使用不含敏感信息的最小示例文档提交 Issue。

## 路线图

- 可选的 PR 评论和报告链接；
- 页数、幻灯片数量变化规则；
- 字体替换清单；
- 幻灯片移动的语义匹配；
- 只有在真实用户提出需求后才考虑 XLSX。

## 参与贡献

渲染问题最需要的是体积小、可公开、能稳定复现的样例文件。请阅读
[中文贡献指南](CONTRIBUTING.zh-CN.md)。参与本项目即表示同意遵守
[行为准则](CODE_OF_CONDUCT.md)。

## 开源协议

[MIT](LICENSE)
