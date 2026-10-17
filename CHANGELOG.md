# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

> **写给它看的人**：每次有实质改动加一行，让另一个人在 `git pull` 之前知道会有什么变化。
> 新增一条坑用 `pit:` 前缀。

---

## [未发布]

### 待办 / TODO

- [ ] 从 `lightroom-mcp` 上游确认 [坑 9](docs/pitfalls.md#pit-9)（`add_ai_mask` 卡死写锁）是否已修，更新 [`docs/mcp-comparison.md`](docs/mcp-comparison.md)
- [ ] 补几份真实的 `recipes/` 存档
- [ ] 导出第一批 `presets/*.xmp`
- [ ] 如果 macOS 上有人跑通了，把 `docs/setup.md` 的平台限制改掉

---

## [0.1.0] — 2026-10-14

首次公开。内容来自一次真实的六张照片精调项目——**所有条目的都是在那次里踩出来的，不是推测。**

### 新增

**核心**

- `SKILL.md` —— 给 AI 智能体的调色指令：10 步主循环、参数手法、判读标准、禁用清单
- `doctor.py` —— 环境自检。装完先跑它
- `docs/workflow.md` —— 单张精调的完整工作流与决策依据

**知识**

- `docs/pitfalls.md` —— **19 条实测坑位**，每条含「症状 / 根因 / 怎么发现 / 怎么办」
  - 其中三条 🔴 级：坑 9（AI 蒙版卡死目录写锁）、坑 19（快照静默回退）、坑 10（`As Shot` 不还原色温）
- `docs/setup.md` —— 从零安装 MCP 桥 + 插件 + 完整故障排查
- `docs/mcp-comparison.md` —— 几个 Lightroom MCP 实现的横向对比

**脚本（12 个）**

- `lr_catalog.py` —— 直读 `.lrcat`：概览 / 参数导出 / 风格归纳 / 直方图
- `histo.py`、`imgsize.py`、`jpeg_quality.py` —— 量化验证
- `make_compare.py`、`contact_sheet.py` —— 前后对比图、多图并排
- `crop_image.py`、`grid_overlay.py` —— 裁切试探、倾斜参考网格
- `mcp-probe.mjs`、`lr-test.mjs` —— 连接排查
- `estimate_tilt.py`、`level_check.py` —— ⚠️ **标定失败的反面教材**，保留用于警示

**协作载体**

- `presets/` —— Lightroom 预设（`.xmp` 纯文本，可 diff、可合并）
- `recipes/` —— 成品参数存档模板
- `profiles/` —— 把「引擎」和「口味」分开的个人风格档案

### 已知问题

- `add_ai_mask` 在当前使用的 `@pired/lightroom-mcp` 3.2.6 上**不可用**（卡死目录写锁，只有重启 Lightroom 能恢复）
- 部分功能（AI 降噪等依赖 UI 自动化的操作）**仅 Windows**
- 无法列出或读取 Lightroom 快照——Adobe SDK 限制，只能靠命名规范防御
- 两个倾斜估算脚本标定失败，已在文档中标注弃用

---

## 发布约定

- **`0.x`** —— 内容还在长，格式可能变
- **新增坑位不改变版本语义**，直接进 `[未发布]`
- **只要有人照着 `docs/setup.md` 跑通了一次，就可以发 `1.0.0`**
