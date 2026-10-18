---
name: lightroom-ai-grading
description: 用 AI 智能体通过 MCP 控制 Adobe Lightroom Classic 做单张精调——环境检查、建虚拟副本保护原片、看图、写入 Camera Raw 参数、用直方图量化诊断、迭代微调、直到导出成品。适用于用户给出照片文件名要求"调这张"、"调色"、"修图"、"做某个风格"的场景。包含 20 条已验证的坑位清单。
whenToUse: 用户要求用 Lightroom 调色/修图某张照片，或需要搭建/排查 Lightroom MCP 连接时
metadata:
  verified: "Lightroom Classic 15.3 (Windows) / @pired/lightroom-mcp 3.2.6"
---

# Lightroom AI 调色工作流

用 AI 直接操作**真实的** Lightroom Classic：看图 → 改参数 → 看结果 → 迭代 → 出图。

**原片永不修改**，所有效果存在虚拟副本上。

> 📖 **配套文档**（本 skill 的详细版，遇到问题先查这里）
> - [`docs/pitfalls.md`](docs/pitfalls.md) — **20 条实测坑位**。动手前至少读坑 9 / 10 / 19 / 20
> - [`docs/workflow.md`](docs/workflow.md) — 完整工作流与决策依据
> - [`docs/setup.md`](docs/setup.md) — 安装与故障排查
>
> 📂 **本文所有相对路径都以本仓库根目录（也就是本 skill 所在目录）为基准。**
> 即 `doctor.py` 和 `scripts/` 应该和 `SKILL.md` 在同一层。

---

## 一、开工前环境检查

```powershell
python doctor.py                                        # 一键体检，推荐

# 手动检查：
Get-Process Lightroom -ErrorAction SilentlyContinue | Select-Object Id,Responding
Get-NetTCPConnection -LocalPort 58763,58764 -State Listen |
  Select-Object LocalPort,OwningProcess
```

端口 **58763/58764** 有 `Listen`、OwningProcess = Lightroom 的 PID，**只说明插件加载了，不代表桥能应答**——桥僵死时端口照样在监听、连接照样 `ESTABLISHED`，但每条调用都报 `not answering`（[坑 20](docs/pitfalls.md#pit-20)）。真判据是插件日志里有没有你这次调用的 `Request id=` 行。

**连不上先做这三件事**：
1. 确认 Lightroom 停在**「图库」模块**（按 `G`）——插件只在图库模块强制初始化，见 [坑 14](docs/pitfalls.md#pit-14)
2. 看插件日志有没有新行：`<我的文档>\LrClassicLogs\LightroomMCP.log`
3. 报 `Connected to the Lightroom plugin's ports, but it is not answering` → **先杀桥**（[坑 20](docs/pitfalls.md#pit-20)），别急着重启 Lightroom——会丢掉正在多选的照片

---

## 二、调色主循环（核心）

严格执行这 10 步，**不要跳步**：

```
 1. 定位    search_photos(filename="IMG_XXXX")     → 拿到 id
 2. 看图    export_photos + read_image             → 先看清内容再动手（必做）
 3. 读参数  get_develop_settings(id)               → 理解用户原有思路
 4. 建副本  create_virtual_copies([id])            → 拿到新 id，原片不动
 5. 选中    select_photos([新id])                  → 复位前必须做
 6. 归零    reset_develop(新id, scope="all")       → 或显式写 0（见坑 3）
 7. 调色    set_develop_settings(新id, {...})      → 工具会回读验证
 8. 出图    全尺寸导出 → read_image                → 见坑 2，不要用 get_photo_preview
 9. 诊断    跑直方图 → 用数据判断，不靠肉眼
10. 迭代    改 1-3 个参数 → 回到 8；满意 → 交付验证
```

### 第 2 步：看图（不可跳过）

**不看就调必翻车**——光线条件、构图、内容决定风格可行性。

- 用 `export_photos` 导出到固定目录 + `read_image` 读文件
- `get_photo_preview` 经常 90s 超时，**不要用**（[坑 2](docs/pitfalls.md#pit-2)）

### 第 3 步：读参数，理解用户原来的思路

用户原有参数**暴露了他的审美意图**。照搬不行（他可能就是不满意才让你调），**完全无视更糟**。

先读懂，再问：「延续你原来的方向」还是「基本重调」。

### 第 4-6 步：保护原片

```
create_virtual_copies([源id])      → 返回新 id
select_photos([新id])              ← 必须！复位只作用于"当前活动照片"
reset_develop(新id, scope="all")
```

**复位失败的识别**：响应里每个参数的 `before` 和 `after` 一模一样 → 没生效。
**别信 `success`，看 diff。**（[坑 3](docs/pitfalls.md#pit-3)）

### 第 7 步：写参数

响应里的 `verified` 就是 Lightroom 实际存下的值。**只用允许列表内的键**（[坑 1](docs/pitfalls.md#pit-1)）。

**风格实现的正确手段（按威力排序）**：

1. **色调曲线分通道** ← 最强，做冷暖分离的唯一有效手段
   - 蓝通道：暗部抬 + 高光压 → 暗部偏青蓝、亮部去蓝
   - 红通道：暗部压 + 高光抬 → 阴影去红、高光转暖
   - 绿通道：暗部微抬 → 让阴影落在青绿而非纯蓝
2. **HSL 八区** ← 精准打击特定颜色（压霓虹、保肤色）
   - 💡 若某主体独占一种颜色，**只调这个颜色的 HSL ≈ 免蒙版局部调整**
3. **基础滑块**（曝光/高光/阴影/黑阶/对比）
   - ⚠️ **`Dehaze` 慎用**——对阴天天空是灾难，实测 +12 让死白从 6.2% 涨到 12.4%
4. **白平衡** ← **慎用**！影响全局肤色，风格化优先靠曲线

> ⚠️ **色温必须显式写死数值。** `{"WhiteBalance": "As Shot"}` **不会**还原色温（[坑 10](docs/pitfalls.md#pit-10)）。
> 正确写法：`{"WhiteBalance": "Custom", "Temperature": 4800, "Tint": 7}`

### 第 8-9 步：出图 + 数据诊断

```powershell
# 导出（不要传 width/height，见坑 12）
export_photos(destination="<临时目录>", format="jpeg",
              on_existing="overwrite", photo_ids=[新id])

# 轮询等文件落盘（见坑 5），然后 read_image
# 再跑直方图：
python scripts/lr_catalog.py hist "<导出的.jpg>"
```

**用数字判断，不要靠肉眼感觉。** 判读标准：

| 指标 | 健康范围 | 说明 |
|---|---|---|
| 死白 ≥250 | **< 8%** | 超过说明高光推爆了 |
| 纯白 254+ | < 2% | 越高越不可逆 |
| 死黑 ≤12 | **1–8%** | 0% 说明黑场丢了、画面发飘 |
| 亮度 p50 | **110–160** | 白天街头；夜景可更低 |
| 目标区 R−B | 按风格定 | 负=冷，正=暖；**验证风格落地的硬指标** |

> ⚠️ **p50 > 180 就是过曝，先修曝光再谈风格。** 在发白的底子上刷冷调只会越调越糟（[坑 15](docs/pitfalls.md#pit-15)）。

### 第 10 步：迭代原则

- **一轮只改 1-3 个参数**，否则不知道是哪个在起作用
- 每次改完**重新出图 + 重跑直方图**，用前后数字对比
- 迭代 4-5 轮后收益递减，该收敛
- **别把"电影感"理解成"压暗"**——实测最常犯的错。压暗 ≠ 氛围

---

## 三、绝对不要做的事

| ❌ 禁止 | 原因 |
|---|---|
| **`add_ai_mask`** | **一次调用就卡死目录写锁，只有重启 Lightroom 能恢复**。且返回的 mask_id 可能是错的，会覆盖用户自己的修图。见 [坑 9](docs/pitfalls.md#pit-9) |
| 用 `get_photo_preview` 看图 | 经常 90s 超时，改用 `export_photos` + `read_image` |
| 传 `WhiteBalance: "As Shot"` 想还原 | 不会生效，色温会卡在旧值上静默污染后续调整 |
| 导出传 `width`/`height` | 会变成 1000px，改用全尺寸导出 + 本地缩放 |
| 改蒙版前不核对 id | 必须先用 `list_masks` 核对名字 |
| 只看 `success` 判断成败 | 看 `before`/`after` diff |

**局部调整的正确顺序**：HSL 颜色选择 → `add_local_adjustment`（线性/径向）→ ~~`add_ai_mask`~~（禁用）

**确实需要 AI 蒙版时**：让用户在 Lightroom 里手动建好 → `list_masks` 读真实 id → `set_mask_adjustments` 改参数。

---

## 四、交付（最容易出事的一步）

### 4.1 全尺寸导出

```
export_photos(destination="<成品目录>", format="jpeg", quality=100,
              on_existing="overwrite", photo_ids=[新id])
```

不传 `width` 即为全尺寸。用 `scripts/imgsize.py` 核实尺寸。

> `quality` 参数实际无效，但**输出本来就是最高画质**（DQT 量化表 ≈ 画质 100），**不要再花时间修它**（[坑 11](docs/pitfalls.md#pit-11)）。

### 4.2 与参照文件做 MAD 比对 ← **不可跳过**

**每次用户点头时，把当次导出另存到一个不会被覆盖的路径**，作为唯一真相来源。交付前逐张比对：

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

| MAD | 含义 | 先查什么 |
|---|---|---|
| `0.00` | 逐像素一致 ✅ | — |
| `2 ~ 10` | 有明显差异 | **先查色温**（坑 10） |
| 尺寸不同 | 裁切/角度被动过 | `CropAngle` **和** `CropTop/Left/Bottom/Right` 都要恢复 |

> ⚠️ **为什么必须做**：用户在 Lightroom 里点一下快照就会**静默回退**照片，而 SDK **无法检测**（不能列快照、读不到当前快照）。我们因此交过三张错图。见 [坑 19](docs/pitfalls.md#pit-19)。
>
> 同时：**回退用的快照要命名为 `⚠️废弃-勿点-*`**，只有 `*-final` 系列是安全的。

### 4.3 提醒用户改名

导出默认沿用原文件名，**拷回原目录会覆盖原片**——每次都要提醒。

---

## 五、沟通原则

1. **调之前先问方向**，别自己假设。用具体选项让用户选（延续原风格 / 青橙 / 黑白 / 清爽日系…）
2. **主动报告诊断数据**，别只说"调好了"。用户看得到数字才有判断依据
3. **调错了要直说**，并说明**是哪个参数导致的、怎么改**
4. **交付时说清楚**：成品路径、尺寸、原片是否安全、效果存在哪个虚拟副本
5. **每次交付后提醒改名**

---

## 六、快速参考

### 色相锚点表（HSL / 颜色分级用）

| 颜色 | 色相 | 常见用法 |
|---|---|---|
| 橙（暖高光/肤色） | 40 | 高光 Sat 15~30 |
| 黄 | 60 | 路面标线、暖点缀 |
| 绿 | 120 | 植被、招牌 |
| **青绿 teal** | 190 | 阴影 Sat 20~30 |
| **青蓝 cyan** | 195~215 | 天空、玻璃、路面 |
| **蓝 blue** | 220~240 | 阴影 Sat 25~40 |
| 紫 | 280 | — |
| 洋红 | 320 | 霓虹 |

### 风格配方（都已实测）

**冷青电影都市感**（白天/阴天街头）
```
Temperature 5300 | Highlights −70 | Exposure −0.45 | Blacks −20
ToneCurve:     [0,0, 44,40, 128,128, 208,210, 255,255]
ToneCurveBlue: [0,0, 64,70, 192,192, 255,255]   ← 抬暗部+压高光 = 冷
ToneCurveRed:  [0,0, 64,58, 192,202, 255,255]   ← 压暗部+抬高光 = 暖
SaturationAdjustmentBlue +30 | HueAdjustmentBlue +22 | HueAdjustmentAqua +15
Saturation −5 | Vibrance 8 | Vignette −20
```
> ⚠️ **不要用 `Dehaze`**——实测 +12 让死白从 6.2% 涨到 12.4%。

**青橙电影感**（黄昏/夜景）
```
ToneCurveBlue: [0,0, 64,70, 192,184, 255,255]   ← 暗部更青、高光更去蓝
ToneCurveRed:  [0,0, 64,56, 192,208, 255,255]   ← 高光更暖
SaturationAdjustmentAqua +12 | Blue +18 | Orange +15 | Yellow +10
LuminanceAdjustmentOrange +10 | HueAdjustmentOrange −6
Saturation −2 | Vibrance 20
```

**蓝调**（适合本身偏冷的场景）
```
Temperature 4650 | SaturationAdjustmentBlue +25 | Aqua +18
LuminanceAdjustmentBlue −8 | Magenta −20 | Purple −15
```

### 工具速查

| 目的 | 工具 |
|---|---|
| 定位照片 | `search_photos` |
| 看图 | `export_photos` + `read_image` |
| 读/写参数 | `get_develop_settings` / `set_develop_settings` |
| 保护原片 | `create_virtual_copies` / `create_snapshot` |
| 曲线 | `set_tone_curve` / `get_tone_curve` |
| 局部调整 | `add_local_adjustment` / `set_mask_adjustments` / `list_masks` |
| ~~AI 蒙版~~ | ~~`add_ai_mask`~~ ⛔ **禁用，见坑 9** |
| 存预设 | `create_develop_preset` / `export_develop_preset` |
| 清理 | `reset_develop` / `add_spots` / `ai_denoise` |

### 配套脚本（`scripts/`）

| 脚本 | 用途 |
|---|---|
| `lr_catalog.py` | **直读 `.lrcat`**：`list` 概览 / `show <id>` 看动过的参数 / `dump <id>` 完整参数 / `style` 归纳风格分布 / `hist <jpg>` 直方图分析 |
| `histo.py` | 直方图分析（独立版） |
| `imgsize.py` | 核实导出图片的尺寸和大小 |
| `mcp-probe.mjs` | 探针：握手 + 列出所有工具（排查连接） |
| `lr-test.mjs` | 端到端实测某个工具调用 |
| **`make_compare.py`** | **前后对比图**：上原片 / 下修后。给用户看效果的必备工具 |
| **`contact_sheet.py`** | **多图横排对比**：N 张候选并排，同一高度 |
| **`crop_image.py`** | 按归一化边界裁切，支持 `--rotate` |
| **`grid_overlay.py`** | 叠加参考网格 —— **判断倾斜的可靠办法** |
| **`jpeg_quality.py`** | 解析 JPEG 量化表，反推真实画质 |
| `level_check.py` | ⚠️ 倾斜估算 —— **标定失败，不要据它下结论** |
| `estimate_tilt.py` | ⚠️ 倾斜估算 —— **已废弃，同样标定失败** |

```powershell
python scripts/lr_catalog.py style               # 归纳整个目录的风格分布
python scripts/lr_catalog.py hist "photo.jpg"    # 直方图分析
```

> ⚠️ **直读目录的时机限制**：Lightroom **运行时不会实时把新照片写回 `.lrcat`**。
> - **Lightroom 开着** → 用 MCP 的 `get_develop_settings` 读当前状态
> - **Lightroom 关着** → 直读 `.lrcat` 才完整可靠

---

## 七、环境搭建与故障排查

首次安装、或连接出问题 → [`docs/setup.md`](docs/setup.md)
