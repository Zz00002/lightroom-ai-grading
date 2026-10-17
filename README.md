# Lightroom AI Grading

**让 AI 智能体直接操作真实的 Adobe Lightroom Classic 来调色 —— 而不是在另一个 App 里重新发明修图。**

> **English**: An agent skill + toolkit for driving **Adobe Lightroom Classic**
> through the Model Context Protocol (MCP). The agent sees the photo, writes
> real Camera Raw parameters, looks at the result, and iterates — with
> histogram data as the feedback signal instead of vibes. Originals are never
> modified. Includes a hard-won pitfalls list (19 entries, all reproduced on
> real photos) and a `doctor.py` environment check.
> Docs are in Chinese; the scripts and skill are self-explanatory. PRs welcome.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4)
![Requires: Lightroom Classic](https://img.shields.io/badge/Adobe-Lightroom%20Classic-31A8FF)

---

## 为什么做这个

现在「AI 修图」基本有两种形态：独立的 AI 修图 App，或者云端一键滤镜。

但真正在拍照的人的痛点不在这。痛点是你已经有 Lightroom 了，你的库、你的预设、你的十年照片全在里面。你不想为了用 AI，把照片导出到一个陌生 App，调完再导回来——**那等于放弃 Lightroom 的一切**。

所以我们换了个方向：**不重做 Lightroom，而是让 AI 学会用 Lightroom。**

它的运作方式很朴素：

```
看懂照片  →  写入真实参数  →  导出看结果  →  用直方图量化诊断  →  改 1~3 个参数  →  再来一轮
```

和人在 Develop 模块里做的事一模一样，只是快得多，而且**每一次判断都有数字支撑**。

---

## 这套东西包含什么

| | 内容 | 说明 |
|---|---|---|
| 🧠 | **[`SKILL.md`](SKILL.md)** | 给 AI 看的「大脑」：10 步调色主循环、参数手法、判读标准 |
| ⚠️ | **[`docs/pitfalls.md`](docs/pitfalls.md)** | **19 条实测踩出来的坑**——这是本仓库最有价值的部分 |
| 🔧 | **[`scripts/`](scripts/)** | 12 个辅助脚本：直读 `.lrcat`、直方图、对比图生成、裁切、画质反查… |
| 🩺 | **[`doctor.py`](doctor.py)** | 环境自检。装完先跑它 |
| 📊 | **[`docs/mcp-comparison.md`](docs/mcp-comparison.md)** | 市面上几个 Lightroom MCP 实现的横向对比与选型 |
| 📁 | **[`presets/`](presets/) · [`recipes/`](recipes/) · [`profiles/`](profiles/)** | 预设、配方存档、个人风格档案——**真正能共享的修图成果** |

---

## 快速开始

### 0. 前置条件

- **Adobe Lightroom Classic**（AI 蒙版功能需要 12.4+，本体建议 13+）
- **Node.js** 20+
- **Python** 3.9+，带 `numpy` 和 `Pillow`
- 目前**部分高级功能仅 Windows**（进程控制类的操作依赖 Windows API）

### 1. 装 MCP 桥

```powershell
# 1) 装依赖（版本已在本仓库锁定）
npm install

# 2) Lua 插件装进 Lightroom
#    把 node_modules\@pired\lightroom-mcp\dist\LightroomMCP.lrplugin 复制到：
#    %APPDATA%\Adobe\Lightroom\Modules\
```

### 2. 让插件加载

启动 Lightroom Classic。**然后按 `G` 切到「图库」模块。**

> 这一步不是可选的。插件用 `LrForceInitPlugin` 强制初始化，但强制初始化**必须有一个菜单项作为触发点**，而这个插件只注册了图库菜单。如果 Lightroom 启动后停在「修改照片」模块，插件**永远不会加载**，端口一直不通。
> 详见 [坑 14](docs/pitfalls.md#pit-14)。

### 3. 体检

```powershell
python doctor.py
```

全部 `[ OK ]` 就可以开工了。有 `[FAIL]` 就照着提示修。

### 4. 接上你的 AI 智能体

把 [`SKILL.md`](SKILL.md) 作为 skill 装进你的 agent（Claude Code / DSH / 任何支持 skill 或 system prompt 的客户端），然后直接说：

> 「把 IMG_0031 调成黄昏暖调，先给我看一版」

详细安装与排查见 [`docs/setup.md`](docs/setup.md)。

---

## 四条设计原则

这不是随手攒的脚本集合，有几条原则是被真实的失败教出来的：

### 1️⃣ 原片永不修改

所有编辑都发生在**虚拟副本**上。原片保持原样——这不是洁癖，是因为你随时可能想推翻重来。

### 2️⃣ 先修曝光，再谈风格

**这条是用一整轮白干换来的。**

曾经把一张照片调成「冷青电影感」，肉眼觉得「差不多了」，但直方图显示死白 **12.4%**、天空的 R−B 只有 **−4**（基本中性）——**风格根本没落地**。

根因是那张照片本身 **p50 = 195**，即一半画面比 195 还亮，早就过曝了。**在发白的底子上刷冷调，只会从「干净的白」变成「浑浊的灰白」。**

所以：**先看 p50 把曝光修到 110~160，再谈风格。** 对比度和黑阶只能修暗的那一端，动不了占画面大头的亮部。

### 3️⃣ 用数据判断，不用感觉

每一轮迭代都跑直方图，看这些数字：

| 指标 | 健康范围 | 说明 |
|---|---|---|
| 死白 ≥250 | **< 8%** | 超过说明高光推爆了 |
| 死黑 ≤12 | **1–8%** | 0% 说明黑场丢了、画面发飘 |
| 亮度 p50 | **110–160** | 白天街头；夜景可更低 |
| 目标区 R−B | 按风格定 | 负=冷，正=暖。**验证风格有没有落地的硬指标** |

### 4️⃣ 一轮只改 1~3 个参数

一次改一堆，你就不知道是哪个在起作用。迭代 4~5 轮后收益递减，该收敛了。

---

## 交付前必须做的验证

我们**差点把三张错的照片当成成品交出去**。

当时的验证方式是「文件大小 + JPEG 画质」——两项都正常，但内容其实是**会话早期的废弃版本**。原因是用户在 Lightroom 里**点开了旧快照**，而快照会**静默覆盖所有调整**，且 SDK **完全无法检测**（既不能列出快照，也读不到「当前应用了哪个快照」）。

所以现在的规矩是：**每次用户点头，就把当次导出另存到一个不会被覆盖的路径作为参照**；交付前把新导出和参照做**逐像素比对**：

```python
import numpy as np
from PIL import Image

def load(p, w=1200):
    im = Image.open(p).convert('RGB')
    return np.asarray(im.resize((w, round(w*im.height/im.width)), Image.LANCZOS), dtype=np.float32)

a, b = load(current_export), load(approved_reference)
print('尺寸一致' if a.shape == b.shape else f'尺寸不同 {a.shape} vs {b.shape}')
print(f'MAD = {np.abs(a-b).mean():.2f}')   # 接近 0 才算一致
```

**判读**：`0.00` = 逐像素一致；`2~10` = 有明显差异（**先查色温**）；尺寸不同 = 裁切或角度被动过。

> 💡 全部 19 条坑见 **[`docs/pitfalls.md`](docs/pitfalls.md)**。建议至少把坑 9、10、19 读一遍——那三条能直接救你一次事故。

---

## 仓库结构

```
lightroom-ai-grading/
├── SKILL.md              # 给 AI 智能体看的核心指令（本仓库的「大脑」）
├── doctor.py             # 环境自检 —— 装完先跑这个
├── package.json          # 锁定 MCP 依赖版本（npm install 即可）
├── docs/
│   ├── setup.md          # 从零安装 MCP 桥 + 插件 + 排错
│   ├── workflow.md       # 单张精调的完整工作流与决策点
│   ├── pitfalls.md       # ⚠️ 19 条实测坑位
│   └── mcp-comparison.md # 几个 Lightroom MCP 实现的横向对比
├── scripts/              # 12 个辅助脚本（直方图/对比图/裁切/画质反查…）
├── presets/              # Lightroom 预设（.xmp，纯文本、可 diff）
├── recipes/              # 成品参数存档（一张一个 YAML）
├── profiles/             # 个人风格档案 —— 把「引擎」和「口味」分开
├── CONTRIBUTING.md       # 协作约定（含一条硬底线：照片绝不进仓库）
└── CHANGELOG.md          # 每次改动让另一个人 pull 之前知道
```

---

## 关于协作

这个仓库是给**两个人**用的，但原则对更多人也成立：

**能进 git 的**：流程、参数知识、脚本、`.xmp` 预设、配方存档。全是纯文本，能 diff、能 review、能回滚。

**不能进 git 的**：照片、`.lrcat` 目录、导出成品。原因有三个——体积、隐私、以及一个很多人不知道的事实：

> **Lightroom Classic 的目录（`.lrcat`）无法合并。**
> 两个人**不可能共用一个目录**，只能各修各的。

所以「实时同步」的真实含义是：**同步方法和预设，不是同步照片库。** 这个预期一开始就摆正，比三个月后发现要好。

协作方式见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

---

## 已知局限（不粉饰）

- **有依赖外部 MCP 的风险**：实际执行操作的是第三方项目。我们实测在其 3.2.6 版本上发现两个严重 bug（AI 蒙版会卡死目录写锁、返回错误的 mask id），已在 [坑 9](docs/pitfalls.md#pit-9) 记录并给出规避方案。
- **有些操作需要 Lightroom 在前台**：依赖 UI 自动化的功能（如 AI 降噪）会占用你的鼠标键盘。
- **不能列出或读取快照**：Adobe SDK 的限制，我们无法绕过，只能靠命名规范防御。
- **`add_ai_mask` 目前建议不要使用**：见上。
- **自动化测量必须先标定**：我们写过两个倾斜估算器，**都没通过标定**（人为旋转 ±2°，读数只动 0.15°）。结论是要用参考网格叠加图 + 人眼。见 [坑 16](docs/pitfalls.md#pit-16)。

---

## 致谢

- [`lightroom-mcp`](https://github.com/par4987/lightroom-mcp) 及其上游项目——真正干活的工具
- [Model Context Protocol](https://modelcontextprotocol.io/)——让这一切成为可能的协议
- 以及那六张被反复调了十几版的照片，和愿意把不满意说出口的摄影师

## 许可证

[MIT](LICENSE)。本仓库只包含原创的文档、知识和辅助脚本，不包含任何第三方源码。
