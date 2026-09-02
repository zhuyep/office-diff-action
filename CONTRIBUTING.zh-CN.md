# 参与贡献

[English](CONTRIBUTING.md) · 简体中文

感谢你帮助大家更可靠地审查 Office 文档变化。

## 提交代码前

新增功能请先创建 Issue。渲染缺陷可以直接提交 Pull Request，但需要附带一个能够稳定复现问题的最小文档。

不要提交机密文件、客户文件或单位内部文件。请重新制作一个小型合成样例，并移除作者姓名、批注、修订历史、
自定义 XML、嵌入文件和外部链接。

## 开发环境

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
```

理想的提交应同时包含实现、测试、必要的说明，以及在适用时提供的小型复现文件。

## Pull Request 检查清单

- [ ] 新行为已有测试覆盖；
- [ ] 面向用户的变化已经写入文档；
- [ ] 测试文档完全由合成内容生成，可以安全公开；
- [ ] 生成报告不包含本地路径或机密内容；
- [ ] `ruff check .` 和 `ruff format --check .` 通过；
- [ ] `python -m unittest discover -s tests -v` 通过。
