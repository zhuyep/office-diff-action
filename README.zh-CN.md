# Office Diff Action

**在合并前，看清 Word 和 PowerPoint 到底改了什么。**

[English](README.md) · 简体中文

[![Test](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml/badge.svg)](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

GitHub 可以保存 `.docx` 和 `.pptx`，但普通代码差异无法告诉审阅者：文字是否发生了重排、
某一页是否多出来了、幻灯片版式是否错位，或者文档是否已经无法正常渲染。

Office Diff 会把每个发生变化的页面或幻灯片生成为“修改前 / 修改后 / 差异”三联图，
同时输出从 Office Open XML 中提取的文字差异，以及便于自动处理的结构化报告。
新增的 **preflight 预检模式尚未发布**，可在安装或运行渲染器之前检查提取文本、
字体声明和环境证据。

![Office Diff 演示](assets/demo/page-001.png)

## 一个命令试用预检

在当前源码目录中，使用 **Python 3.9 或更新版本**运行：

```bash
python examples/preflight_demo.py
```

不需要 pip 安装、Pillow、LibreOffice、Poppler、API Key 或服务器。
随后用浏览器打开任一报告：

- `examples/generated/preflight/text-change/index.html`：观测环境相同，文本发生变化。
- `examples/generated/preflight/environment-drift/index.html`：文档相同，目标字体清单发生变化。

下载源码后，也可直接双击保存好的[文本变化示例](assets/preflight-demo/text-change/index.html)
或[环境变化示例](assets/preflight-demo/environment-drift/index.html)。
**两份示例都使用合成文档和明确标注的合成环境；它们不是本机环境实测，也没有渲染 Office 页面。**

## 预检自己的文档

以下功能属于当前源码中的未发布实现，没有更改已发布的 Action 镜像或包版本。
如果已在本地安装此源码，可执行：

```bash
office-diff doctor --output current-environment.json
office-diff preflight before.docx after.docx \
  --environment current-environment.json \
  --baseline-environment baseline-environment.json \
  --output preflight-report
```

`baseline-environment.json` 应是在基准文档对应环境中运行 `doctor` 后保存的快照。
没有基准快照时，去掉 `--baseline-environment` 即可，报告会明确说明未比较环境变化。
同样支持输入两个 `.pptx` 文件。

如果不想安装任何依赖，可以直接在仓库根目录运行：

```bash
PYTHONPATH=src python -m officediff doctor --output current-environment.json
PYTHONPATH=src python -m officediff preflight before.docx after.docx --output preflight-report
```

在 PowerShell 中，先执行 `$env:PYTHONPATH = "src"`，再用
`python -m officediff` 加上同样参数。Python 版本须不低于 3.9。

| 参数 | 行为 |
|---|---|
| `doctor` | 向标准输出打印 JSON 环境快照。 |
| `doctor --output NEW.json` | 写入新文件；目标文件已存在时拒绝覆盖。 |
| `preflight --environment CURRENT.json` | 使用指定的当前环境快照；省略时采集本机环境。 |
| `preflight --baseline-environment BASE.json` | 比较基准与当前环境观测，并用基准快照检查修改前文档。 |
| `preflight --output DIRECTORY` | 生成 `index.html`、`summary.json` 和 `environment.json`；默认目录为 `office-preflight-report`。 |
| `preflight --fail-on-warning` | 写完报告后，只要存在警告就返回退出码 1。 |

预检默认在成功生成报告后返回 0，即使证据不完整或存在警告；输入无效、输出失败时返回 2。
没有基准快照时，两版文档都按当前环境检查。缺失的渲染工具会记录在报告中，
不会阻止 `doctor` 或 `preflight` 运行。

### 怎样理解报告

- **字体声明不等于实际使用的字体。** 声明可能来自未使用的样式。主题引用尚未解析，
  主题字体候选表和字体目录不会直接判成缺失字体。
- **没有字体证据时，结论是未知。** 字体清单不可用或不完整时，报告不会把它当作
  “字体全部缺失”。某个声明字体不在完整清单中，只表示可能存在替换风险，不证明
  已发生替换；字体家族可用也不证明覆盖全部字形或已被渲染器选中。
- **指纹只覆盖观测字段，不能保证确定性渲染。** 指纹包含平台字段、已发现工具的版本、
  字体家族和观测到的字体文件哈希；没有完整覆盖 fontconfig 规则、Office 设置、
  locale 等依赖。指纹相同不保证页面相同，指纹不同也不证明它就是视觉变化的原因。
- **预检不渲染页面。** 提取文本相同不代表文档等价：格式、图片、图表和部分字段不在
  检查范围内。PPTX 文本当前仍按部件文件名排序，不是实际播放顺序。

公开问题说明了诊断的价值：[pdf-diff #56](https://github.com/JoshData/pdf-diff/issues/56)
报告的是算法导致的差异标记误报，不是字体问题；
[Docxodus #379](https://github.com/JSv4/Docxodus/issues/379) 记录了区分字体环境变化
与渲染器回归的需求。后者已关闭并解决，这里仅作为需求证据，不声称仍是功能空白，
也不据此断言 Office Diff 存在字体错误。

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
- 保存在 `environment.json` 和 `summary.json` 中的环境快照，及 HTML、Markdown
  可视化报告中的观测指纹和限制说明；
- GitHub Actions 运行摘要。

报告目录结构如下：

```text
office-diff-report/
├── index.html          # 可视化审阅报告
├── report.md           # 可移植的 Markdown 报告
├── summary.json        # 便于自动处理的摘要
├── environment.json    # 观测到的渲染环境
└── documents/
    └── .../
        ├── base/       # 修改前页面
        ├── current/    # 修改后页面
        └── diff/       # 三联差异图
```

## 在本地渲染可视化差异

本机需要安装 LibreOffice 和 Poppler，并确保它们位于 `PATH` 中：

```bash
python -m pip install .
office-diff compare before.pptx after.pptx --output office-diff-report
```

渲染失败时命令会返回非零状态。文字提取会尽可能继续执行，让报告保留已有证据，
而不是悄悄忽略失败。
`compare` 和 `action` 的原有参数与退出码行为保持兼容；新增环境快照用于诊断，
字体风险不会直接改变原 Action 的成功或失败状态。本次预检 MVP 尚未完成本地
真实 Office 文档的完整渲染验证。

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
  但 Dockerfile 没有锁定 LibreOffice、Poppler 和字体的 apt 包版本，因此独立重建
  可能得到不同环境。后续容器版本也可能改变结果；复杂文档在 LibreOffice 与桌面版
  Microsoft Office 中仍可能出现分页差异。
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
- 在字体声明预检之外，补充实际字体选择与替换证据；
- 幻灯片移动的语义匹配；
- 只有在真实用户提出需求后才考虑 XLSX。

## 参与贡献

渲染问题最需要的是体积小、可公开、能稳定复现的样例文件。请阅读
[中文贡献指南](CONTRIBUTING.zh-CN.md)。参与本项目即表示同意遵守
[行为准则](CODE_OF_CONDUCT.md)。

## 开源协议

[MIT](LICENSE)
