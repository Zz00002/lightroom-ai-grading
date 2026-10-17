# Lightroom MCP 实现横向对比

> **本文信息核对于 2026-10-16。** 核对方式：本地 4 个 git 克隆 + 1 个 npm 包逐文件读取，加 GitHub / npm 公开 API。项目变化很快，**选型前请自行复核**。
>
> 标注约定：**「本地实测」**＝在本机克隆或已安装的包里直接读出来的事实；其余结论均给出链接；查不到的写**「未确认」**，不猜。

---

## 为什么需要这份对比

想让 AI 智能体通过 MCP 操作 Lightroom Classic，搜一圈会撞上至少 4 个名字极其相似的项目：`lightroom-mcp`（两个不同作者）、`lightroom-ai-bridge`、以及 npm 上一个换了名字的 fork。它们**架构看着几乎一样**——Lua 插件装进 Lightroom + Node/Python 的 MCP server 走本地 socket——但工具数量、平台支持、许可证、以及**实际能不能用**差得很远。

目前公开资料里几乎没有人把这几家放在一起比过。这份文档想填的就是这个空缺，尤其是最后一节：**我们自己在生产环境里踩到的、足以毁掉一次交付的那个 bug。**

---

## 总览

| | [Automaat/lightroom-mcp](https://github.com/Automaat/lightroom-mcp) | [par4987/lightroom-mcp](https://github.com/par4987/lightroom-mcp) | [aslanoov/lightroom-ai-bridge](https://github.com/aslanoov/lightroom-ai-bridge) | [synthet/lightroom-mcp](https://github.com/synthet/lightroom-mcp) |
|---|---|---|---|---|
| **角色** | 上游 / 事实标准 | Automaat 的 fork，**本仓库在用** | 独立实现 | 独立实现（最早的一个） |
| **语言 · 运行时** | TypeScript / Node ≥18 | TypeScript / Node ≥20 | **Python** 3.10+（MCP）／纯 stdlib（CLI） | **Python** 3.10+（FastMCP + Flask） |
| **MCP 工具数** | **28** | **56** | **46**（另称 7 个 `kb_*`）⚠️见下 | **47** |
| **需要 .lrplugin** | 是 | 是 | 是（`ClaudeBridge.lrplugin`） | 是 |
| **端口** | 58763 / 58764 | 58763 / 58764 | **49463 / 49464** | **8085 HTTP / 8086 socket** |
| **平台** | macOS + Windows | Windows 优先 | **仅 macOS**（LrC 15.3+） | Python 可跑，文档未声明限制 |
| **许可证** | MIT (c) 2026 Marcin Skalski | MIT (c) 2026 Marcin Skalski | MIT (c) 2026 Mustafa Aslanov | **无 LICENSE** ⚠️ |
| **★ / fork / issues** | 137 / 34 / 7 open | 1 / 0 / **0** | 2 / 0 / **0** | 8 / 2 / **0** |
| **最近提交（本地 HEAD）** | `8fee4b7` 2026-10-13 | `e51dc75` 2026-10-06 | `a38f878` 2026-09-26 | `9d83f63` 2026-02-18 |
| **活跃度** | 活跃（上游已推进到 PR #279） | 一次性冲刺后停更 | 1.0.0 发布后停更 | **已停滞约 8 个月** |

> 上表的工具数、端口、许可证、HEAD 均为**本地实测**（读 `server/src/tool-contracts.ts`、`mcp_server.py`、`server.py`、`ports.ts`、各插件 Lua 与 `LICENSE`）。★/fork/issues/归档状态来自 GitHub API（[Automaat](https://api.github.com/repos/Automaat/lightroom-mcp)、[par4987](https://api.github.com/repos/par4987/lightroom-mcp)、[aslanoov](https://api.github.com/repos/aslanoov/lightroom-ai-bridge)、[synthet](https://api.github.com/repos/synthet/lightroom-mcp)），读取日期 2026-10-16。四者**均未被 archived**。

### 安装方式

| 项目 | 分发 |
|---|---|
| Automaat | npm `@mskalski/lightroom-mcp` **v0.22.0**（本地实测）；另有 `.mcpb` 双击安装包、macOS/Windows 单文件二进制（Bun 编译） |
| par4987 | npm **`@pired/lightroom-mcp` v3.2.6**（本地实测）；tarball 自带 `.lrplugin`、DeepSeek harness、现成客户端配置 |
| aslanoov | **未上 PyPI**，从源码装（`uv run --directory <repo> lightroom-bridge`）；`lrc` CLI 另可 `pip install -e .` |
| synthet | 无包管理器分发，clone 后手工建 venv、装 `requirements.txt`、手动登记 MCP server |

---

## 逐个看

### Automaat/lightroom-mcp —— 上游，也是唯一「产品化」的一个

**定位**：面向不懂编程的摄影师。三条命令装完就能用，Claude Desktop / Claude Code / Codex / Cursor / Windsurf / VS Code 全覆盖，还有繁中 README。

**优点**
- 生态最成熟：137 ★、34 fork、7 个 open issue，是本组里唯一有真实外部贡献者和 issue 讨论的项目（[#279](https://github.com/Automaat/lightroom-mcp/issues/279) 由外部贡献者提交）。
- 分发最省心：`.mcpb` 双击安装，或 npm / 单文件二进制。
- 工程质量高：181 个 busted + 176 个 jest 测试，selene lint、tsc、eslint 全绿（[PR #219](https://github.com/Automaat/lightroom-mcp/pull/219)），CI 覆盖三大平台。
- 元数据/目录/预设三条线做得最深：GPS、IPTC 定位、关键词层级重命名、预设 diff 与版本化 checkpoint、`export_photo_metadata`。
- 安全模型清楚：插件生成 256-bit token，MCP server 每个请求都带（本地实测 token 文件默认 `~/.config/lightroom-mcp/token`）。

**缺点**
- **28 个工具，一个蒙版相关的都没有。** 没有 `add_ai_mask`、没有局部调整、没有点曲线之外的局部工具。想「选区调色」这条线走不通。
- 同上的另一面：**本仓库关心的那个 AI 蒙版 bug 在这个项目里根本不存在**，因为它没有这个功能。
- 文档语言是英文（有繁中），没有中文。

**适合谁**：主要做**素材管理**（评级、打标、关键词、收藏夹、导入导出、预设管理）而不是精修调色的人；或者想要「最不容易踩到坑」的默认选择的人。**如果你的核心诉求是选区调色，它满足不了。**

---

### par4987/lightroom-mcp（npm `@pired/lightroom-mcp`）—— 本仓库在用的那个

**定位**：功能最激进的分支。上游 18 个工具全部保留，再加 38 个，主打「AI 能做的都做」：AI 降噪、去污点、AI 蒙版、范围蒙版、色调曲线、Auto Tone/WB、进程版本、快照、JPEG 预览内联。

**优点**
- **工具数碾压：56 个**，是 Automaat 的两倍。本仓库调色工作流依赖的 `get_photo_preview`、`set_tone_curve`、`add_local_adjustment`、`read_local_adjustments`、`reset_develop`、`set_process_version`、`create_virtual_copies`、`get_photo_status`、`manage_view_filter` **全部只有它有**（对照 Automaat 的 28 个工具表，本地实测两者 `tool-contracts.ts`）。
- **自带「看图」闭环**：`get_photo_preview` 把渲染出的 JPEG 作为 MCP image block 内联返回，这是「编辑→看→再编辑」能成立的前提。上游没有这个工具。
- **本地调整走直写路径**：`add_local_adjustment` 用 `catalog:withWriteAccessDo` + `photo:applyDevelopSettings`，不碰 Develop 模块 UI（源码注释明确写 "NOT LrDevelopController (no Develop-module UI)"，`HandlerLocalAdjustments.lua:525`）。**这一点很重要，见「已知问题」。**
- 内置 DeepSeek harness（手写 MCP stdio 协议、零依赖）和现成客户端配置，`LIGHTROOM_MCP_TOOLS` 还能给 token 紧张的小客户端裁剪工具集。
- 测试扎实：Lua 侧有 20 多个 `*_spec.lua`（`HandlerDevelop_spec.lua` 单文件 57KB），TS 侧 jest + eslint + tsc 三重门禁。

**缺点**
- **健康度最差**：**1 star、0 fork、0 issue（含已关闭）**，GitHub 上 `fork: false` —— 它是重新建的独立仓库，不是 GitHub 网络里的 fork。2026-09-23 建仓，2026-10-06 之后停更。**意味着没有任何社区背书，出问题只能自己扛。**
- **Windows 优先**：README 明确写操作系统是 Windows 10/11（原生 AI 降噪靠 Windows 键盘自动化 SendKeys）。macOS 上 `ai_denoise` 会退化成手动降噪滑块。
- 文档是西班牙语（代码注释是英文）。
- 自报的工具数自相矛盾：仓库 README 说「18 原始 + 38 新增 = 56」，npm README 说「18 + 37 = 55」。**本地实测 `TOOL_CONTRACTS` 是 56 个** `name` 条目（`tool-contracts.ts` 第 500–1875 行）。
- 版本历史极短：npm 上从 3.1.0（2026-09-12）到 3.2.6（2026-10-06），**不到一个月发了 10 个版本**。速度快，但也说明 API 面在剧烈变动。

**适合谁**：**需要精修/选区调色、且用 Windows** 的人——也就是本仓库的场景。代价是你得自己读源码、自己写兜底，别指望社区。

---

### aslanoov/lightroom-ai-bridge —— 唯一把「看图迭代」写进设计理念的

**定位**：不是「MCP server」，而是 `lrc` CLI + daemon + MCP server + Claude Code skills + 知识库的整套方案。README 里那句 "The trick that makes it work: Claude can **see** the photo. Look, edit, look." 直接把方法论写在门口。

**优点**
- **工程诚实度最高**。`CLAUDE.md` / `AGENTS.md` 里成体系地记录了 SDK 的真实边界，而且都是「我们踩过所以你知道」的语气，例如：
  - AI 蒙版 `create` 之后 `local_*` 值**普遍落不到位**，必须 `mask adjust` 重新推一次，**而且一次是底线**，渲染看起来没变化**不代表**蒙版失败；
  - 蒙版**数值读回一律是 0**（`settings` 谎报），只能靠渲染验证；
  - `rangeMask luminance` 和 `aiSelection objects` 会**静默创建空蒙版**，`ok` 不等于创建成功；
  - 几何蒙版（径向/线性）**无法通过 SDK 定位**，只能落在 Lightroom 的默认位置，作者明确写「确认是死路，不要做 place 命令」。
- **知识库（`kb/`）是最独特的设计**：recall → apply → learn 循环，把用户的口味沉淀成 Markdown 卡片，**且刻意出厂为空**（"Taste is personal; someone else's cards would argue with you on every edit"）。这是本组里唯一试图解决「跨会话口味一致性」的项目。
- MCP server 与 CLI **共用同一个 daemon**，不会互相抢那个「一个端口只允许一个客户端」的插件。
- 入站命令用空沙箱 `loadstring` 解析为**数据而非代码**，安全边界写得明白。

**缺点**
- **仅 macOS**，且要求 **Lightroom Classic 15.3+**。Windows 用户直接出局。
- **依赖 Lightroom 15.4+ 的部分功能**（`mask list` 拿 id 是 15.4 才有的；15.3 上「永远返回 `[]`」）。
- 未上 PyPI，只能从源码装。
- **2 star、0 fork、0 issue**，同样没有任何社区规模。1.0.0 发布后即停更。
- 工具数自报与实测不一致：README 和 CHANGELOG 都说「46 tools + seven `kb_*` tools」，但**本地实测 `mcp_server.py` 里是 46 个 `@mcp.tool` 装饰器，其中 7 个是 `kb_*`**（即 39 个调色/目录工具 + 7 个知识库工具）。**这是本地实测与项目自称冲突的地方，请以你实际 `list_tools` 的结果为准。**
- 附带一整套 Python helper（contact sheet、两级筛片、倾斜测量、注意力层级检查），**对只想接个 MCP 的人来说是额外负担**。

**适合谁**：**macOS + 重视「AI 真的能看到图再决定」的工作流 + 愿意投入时间建知识库**的人。如果你认同本仓库「用数据而不是感觉来判断」的思路，这个项目的哲学跟你最接近。

---

### synthet/lightroom-mcp —— 最早，也是唯一没有许可证的

**定位**：Python 路线的先行者。Lua 插件 + Flask broker + FastMCP server 三层，broker 还带一个 `http://localhost:8085` 的 dashboard 能看连接状态。

**优点**
- **出现最早**（2026-01-24 建仓），比 Automaat 还早两周。
- 47 个工具，覆盖面广：EXIF / IPTC / XMP / 综合元数据、GPS 读写、按路径/文件名/**MD5 哈希**找照片（`find_photo_by_hash` 是别家没有的）、快照、虚拟副本、模块与视图切换、`find_photos` 智能集合式查询。
- **自带 `get_photo_preview(width, height, save_path)`**，可以把预览直接存盘——比 base64 塞进对话更实用。
- 体系结构文档齐全：`SDK_INTEGRATION.md` 专门讲 LrSDK 集成，插件还有自己的单元测试（`tests/TestCommandHandlers.lua`）。

**缺点**
- **没有 LICENSE 文件。** GitHub API 的 `license` 字段是 `null`（本地实测：仓库根目录无任何 `LICENSE*` 文件）。README 末尾写 "See repository license file"，但那个文件不存在。**法律上这是「保留所有权利」，公开仓库不等于可以随便用。** 这是本组唯一一个不能安心用于商业场景的项目。
- **已停滞**：最后一次 push 是 2026-02-19，CHANGELOG 停在 0.3.2（2026-02-18），**距今约 8 个月**。GitHub 的 `updated_at` 是 2026-06-29，但代码没有新提交。
- **文档自相矛盾**：README 说 broker 是 socket 8086 + HTTP 8085（本地实测 `Server.lua` 确认 8085/8086），但 `AGENTS.md` 和 `CLAUDE.md` 都写「插件监听 localhost:54321」。**54321 是过时文档**，照它排查会白费时间。
- 安装最麻烦：手工 venv + `pip install -r requirements.txt` + 手写 MCP 配置，没有任何打包。
- 无蒙版、无局部调整能力（47 个工具里没有 mask 相关的）。

**适合谁**：偏向 Python 技术栈、需要**哈希查重/文件级元数据**这类特殊能力、且能接受「无许可证 + 无人维护」的人。**商业用途建议直接排除。**

---

## 血统关系

真正有血缘关系的只有一对：**Automaat → par4987**。另外两个是独立实现（虽然架构神似）。

```
 rsjaffe/MIDI2LR ── 硬件旋钮→Develop 滑块的 LrSocket 双端口模式
        │            （架构被参考，连默认端口 58763/58764 都照抄）
        ▼
 Automaat/lightroom-mcp      2026-02-07 建仓
 TS+Node · 28 工具 · MIT · 137★
        │  fork（package.json 自述 "Fork of Automaat/lightroom-mcp"，
        │        author 写 "pired (fork), Marcin Skalski (original)"）
        ▼
 github.com/pired/lightroom-mcp     ← npm 3.1.0 ~ 3.2.0 指向这里
        │  迁仓 / 改名（npm 3.2.1 起 homepage 与 repository 改写）
        ▼
 github.com/par4987/lightroom-mcp        2026-09-23 建仓
 +38 工具 = 56 · MIT · 1★ · GitHub 上 fork:false（非网络 fork）
        │  npm publish
        ▼
 npm  @pired/lightroom-mcp 3.2.6   ← 本仓库在用的版本（最新版，未再更新）

 ── 以下两个与本链无关，是独立实现 ────────────────────────────
 synthet/lightroom-mcp         2026-01-24 建仓（本组最早）
 Python+FastMCP+Flask · 47 工具 · 8085/8086 · 无许可证 · 已停滞
 aslanoov/lightroom-ai-bridge  2026-09-20 建仓
 Python+lrc CLI+daemon · 46(+7) 工具 · 49463/49464 · 仅 macOS
```

**两点容易搞混的地方，本地实测确认：**

1. `par4987/lightroom-mcp` 在 GitHub API 里 **`"fork": false`** —— 它是重新建的独立仓库，不是 GitHub 网络意义上的 fork。但它的 `package.json` 自述是 fork，且作者署名保留原作者。所以「血统」是真的，「GitHub fork 关系」是断的。
2. npm 上 3.1.0 / 3.1.1 / 3.1.2 / 3.2.0 的 `homepage` 和 `repository` 都指向 **`github.com/pired/lightroom-mcp`**，从 **3.2.1** 起才改成 `github.com/par4987/lightroom-mcp`。**如果你在老教程里看到 `pired/lightroom-mcp` 这个仓库地址，那是同一个项目迁移前的旧地址。**

---

## 选型建议

| 你的情况 | 建议 |
|---|---|
| 主要做素材管理（评级/关键词/收藏夹/导入导出/预设），要稳 | **Automaat**。生态最大、分发最省心、唯一有真实社区 |
| 要精修调色、选区和局部调整，用 **Windows** | **par4987 / `@pired/lightroom-mcp`**——但**务必读下面「已知问题」并禁用 `add_ai_mask`** |
| 用 **macOS**，且认同「AI 必须先看到图」的迭代式工作流 | **aslanoov**。文档诚实度最高，但要求 LrC 15.3+，且功能面窄于 par4987 |
| Python 技术栈，需要按哈希/路径查照片这类特殊能力 | **synthet**——但**先解决许可证问题**，否则不要用于任何商业场景 |
| 要长期维护、上生产 | **只有 Automaat 有社区冗余**。其余三家的 bus factor 都是 1，停更风险已经部分变成现实 |

**一句话**：如果你要的是**调色**而不是**管库**，实际可选项只有 par4987 和 aslanoov 两家；而这两家分别把「Windows / macOS」写死在前提条件里——**平台其实先替你做了选择。**

---

## 已知问题：`@pired/lightroom-mcp` 3.2.6 上实测到的两个严重问题

以下是本仓库的**一手实测结论**，验证环境：**Lightroom Classic 15.3 (Windows) · `@pired/lightroom-mcp` 3.2.6 · Canon EOS R8 CR3**。详细复现记录见 [`pitfalls.md` 坑 9](pitfalls.md#pit-9)。

### 问题 1：`add_ai_mask` 会把 Lightroom 的目录写锁卡死

**症状**：调用一次 `add_ai_mask` 之后，**任何**写操作全部失败——不只是这一个工具，而是全局性的：

```
LrCatalog:withWriteAccessDo: could not execute action '...'.
It was blocked by another write access call, and no timeout parameters were provided.
```

受影响范围包括 `set_develop_settings`、`set_mask_adjustments`，**甚至用户在 Lightroom 里手动拖滑块**也一样失效。

**而且不会自愈。** 等 100 秒、确认 Lightroom CPU 完全空闲、重启 MCP 桥进程——统统无效。**只有重启 Lightroom 能恢复。** 日志（`<文档>\LrClassicLogs\LightroomMCP.log`）可以坐实因果：`addAIMask('subject')` 成功那一行之后，紧接着所有写操作开始报 blocked。

### 问题 2：`add_ai_mask` 返回的 `mask_id` 可能是错的

实测它**返回了同一张照片上另一个人脸蒙版的 ID**。如果直接拿这个 id 去写参数，就会**覆盖用户自己的人像修图**（磨皮、眼白、虹膜、牙齿）。

### 源码层面的解释（本地实测）

这两条不是玄学，在用的 3.2.6 版本里能直接读出机制：

- **`add_ai_mask` 是唯一一个靠驱动 Develop 模块 UI 来实现的工具。** 它必须 `LrApplicationView.switchToModule("develop")` → `catalog:setSelectedPhotos` → `goToMasking()` → `selectTool("masking")` → 再进一个带 `LrTasks.sleep` 的轮询重试循环（`HandlerAIMasks.lua:487–549`）。**模块切换 + 窗口工具切换 + 反复 yield**，全部发生在写锁生命周期附近。
- 作者自己在同一文件里写了（`HandlerAIMasks.lua:699–705`）：创建批次 yield 太多次之后，任务**已经不再满足 `withWriteAccessDo` 的「必须在 LrTask 内调用」检查**，所以第二阶段只能另起一个 `startAsyncTask`。**说明这条调用路径上的写门禁本来就是脆的。**
- 作者在 `AGENTS.md` 里还记录过另一条相关事实：把 `LrDevelopController` 命令套进 `withWriteAccessDo`，Lightroom **每一次**都会用「blocked by another write access call」拒绝——**deterministic, not intermittent**，而且这个错「已经发布过三次」。
- **`mask_id` 是「推导」出来的，不是 `createNewMask` 返回的。** 代码注释明说该 build 下 `createNewMask` 即使成功也返回 `nil`，于是走 `latestMaskIdFromList(masks, beforeCount)` —— 它取的是 **`getAllMasks()` 列表的最后一项**（`masks[#masks].Tools[1].ID`），**没有任何「这是我刚创建的那个」的身份校验**。一旦新建的蒙版不在末位、或计数增量是假阳性，拿到的就是别人的 ID。
  - 旁证：上游 Automaat 在 [PR #219](https://github.com/Automaat/lightroom-mcp/pull/219) 里实测记录「Lightroom 每次 `getSetting` 调用都会重新生成 `CorrectionID` 和 `MaskID`」——`MaskID` 本身就不是稳定标识符。

### 为什么 `add_local_adjustment` 没有这个问题

`add_local_adjustment`（线性/径向渐变）走的是**完全不同的路径**：`catalog:withWriteAccessDo("Add Local Adjustment")` + `photo:applyDevelopSettings`，即**直接写目录**。源码注释原话（`HandlerLocalAdjustments.lua:525`）：

> `via photo:applyDevelopSettings — the same direct-XMP-write path addLocalAdjustment uses, NOT LrDevelopController (no Develop-module UI)`

**不切模块、不动工具栏、不进重试循环、不碰 UI。** 所以规避方案是明确的：

### 规避清单

1. **不要使用 `add_ai_mask`。** 需要局部调整就用 `add_local_adjustment`（线性/径向渐变）。
2. 如果已经调过 `add_ai_mask` 并出现 blocked 报错：**唯一解是重启 Lightroom**，不要浪费时间等它自愈。
3. 万一必须用 `add_ai_mask`：**写参数前先用 `list_masks` 核对蒙版名字**，确认 id 是不是你想动的那个。
4. 顺手记一条相关的：`add_ai_mask` 反正是不可靠的——该项目的 skill 文档自己写着「`add_ai_mask` is unreliable on this build — the underlying call returns nil even when it works from the UI」，并要求用 `list_masks` 复核，**绝不能凭返回值就宣布蒙版创建成功**。

---

## 上游是否已经知道 / 修了？

**结论：针对「`add_ai_mask` 卡死目录写锁且不可自愈」和「`mask_id` 返回错误」这两个具体问题，未找到任何上游记录。**

核对过程与结果（全部于 2026-10-16 通过 GitHub API 查询）：

| 仓库 | issue 总数（含已关闭） | 相关记录 |
|---|---|---|
| **Automaat**（上游） | 有（PR 编号已到 #279） | **不存在这个问题——它根本没有 AI 蒙版工具**（28 个工具里无任何 mask 相关）。对它的 issue/PR 搜 "mask" 只命中 4 条，全部是无关的偶然词（如 "masking the bug"、"every masked preset"） |
| **par4987**（在用的） | **0** | 未找到相关记录。**该仓库 issue 数、fork 数、已关闭 issue 数全部为 0** |
| **aslanoov** | **0** | 未找到相关记录 |
| **synthet** | **0** | 未找到相关记录 |

**但有两点必须说清楚，避免误判：**

1. **同一个错误字符串在上游出现过，原因不同。** Automaat 的 [#279](https://github.com/Automaat/lightroom-mcp/issues/279) 和 [PR #278](https://github.com/Automaat/lightroom-mcp/pull/278) 都描述了 `"blocked by another write access call"`：大目录上扫描耗时约 90–119 秒，**超过 server 端 30 秒超时**，客户端放弃等待但 Lightroom 仍在写，于是下一次写入撞上它。那是**瞬态碰撞**（针对 `set_keywords` 和按路径传 `photo_id`），**不是永久卡死**，也跟蒙版无关。**不能拿它当作「上游已知此 bug」。**
2. **3.2.6 那个 `LrTasks.pcall` 修复不是修这个。** commit message 是「Release 3.2.6: the LrTasks.pcall fix, which 3.2.5 shipped without」。本地核对：`LrTasks.pcall` 只出现在 `LrTasks.execute`（`HandlerAI.lua`、`HandlerOrganization.lua`、`HandlerAIMasks.lua` 的截图/SendKeys 路径）和 dispatcher（`PluginInfoProvider.lua:369`）——解决的是「`LrTasks.execute` 会 yield，而普通 `pcall` 是 C 调用、无法跨边界 yield」的问题。**与目录写锁无关，所以 3.2.6 并没有修掉本文记录的问题。**

换句话说：**在用的这个版本之后，par4987 只比本地 HEAD 更新过 0 次提交**（npm 上 `latest` 仍是 3.2.6，与该克隆 HEAD `e51dc75` 完全一致），所以**没有任何「新版已修」的可能**。至于 Automaat 是否会在未来把蒙版能力加进来并顺带解决——**未确认**，它目前没有这个功能。

---

## 附：自己复核的命令

所有「本地实测」的数字都可以用下面几条命令复现：

```powershell
# 先把 $tools 指向你存放这些克隆的位置
$tools = "$env:USERPROFILE\lightroom-mcp-src"

# 各项目暴露了多少个 MCP 工具
([regex]'\bname:\s*"').Matches(
  (Get-Content "$tools\par4987\server\src\tool-contracts.ts" -Raw)).Count   # → 56
# automaat 同法 → 28；aslanoov 数 mcp_server.py 的 @mcp.tool → 46（含 7 个 kb_*）；
# synthet 数 mcp-server\server.py 的 @mcp.tool → 47

# 在用的包支不支持颜色分级 / 分离色调（答案：不支持，无输出即无此键）
Select-String -Path "$tools\node_modules\@pired\lightroom-mcp\dist\tool-contracts.js" `
  -Pattern 'ColorGrade|SplitToning'

# 监听端口（在用版本应为 58763/58764）与许可证有无
Get-NetTCPConnection -LocalPort 58763,58764 -State Listen | Select LocalPort,OwningProcess
foreach ($r in 'automaat','par4987','aslanoov','synthet') { "$r : " + (Test-Path "$tools\$r\LICENSE") }
# synthet → False，其余 True
```

> ⚠️ **一个方法论提醒**：本机那 4 个克隆**全部是浅克隆（shallow，depth 1）**，所以 `git log --oneline -15` 在每一个里**都只会输出 1 条提交**——它反映的是克隆时的 HEAD，**不是完整提交历史**。上面表格里的「活跃度」判断因此额外用了 GitHub API 的 `pushed_at` / PR 编号 / issue 数量交叉验证，而不是只看本地 git log。

---

## 信息核对声明

- **核对日期：2026-10-16。**
- 本地事实来自 4 个浅克隆（`automaat` / `par4987` / `aslanoov` / `synthet`）与 npm 包 `@pired/lightroom-mcp` 3.2.6，逐文件读取。网络事实来自 GitHub REST API 与 npm registry，链接已内联。
- **未能确认的项**：各项目的真实用户量（仅 star 数可用）；Automaat 未来是否会加入蒙版能力。
- **本文不含任何未经来源支撑的数字。** 若某处与现状不符，说明项目已经变化——**请以你手上的版本为准**，并欢迎提 PR 修正。
