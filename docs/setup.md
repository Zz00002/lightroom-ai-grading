# 环境搭建与故障排查

从零把 Lightroom Classic 接上 AI 智能体。

> **实测环境**：Lightroom Classic **15.3** (Windows) · Node.js **24.14.0** · `@pired/lightroom-mcp` **3.2.6**
> 装完先跑 `python doctor.py`，它会告诉你哪一步没通。

---

## 一、先决条件

| 组件 | 要求 | 实测 |
|---|---|---|
| Adobe Lightroom Classic | 13+ | **15.3** |
| Node.js | 20+ | **24.14.0** |
| Python | 3.9+（带 numpy、Pillow） | 3.12 |
| 操作系统 | **Windows 10/11**（部分功能依赖 Windows API） | Windows |
| AI 客户端 | 支持 MCP | 见第三节 |

**检查**：

```powershell
node --version
python -c "import numpy, PIL; print('deps ok')"
Test-Path "C:\Program Files\Adobe\Adobe Lightroom Classic\Lightroom.exe"
```

---

## 二、安装 MCP 服务 + Lightroom 插件

用的包：**`@pired/lightroom-mcp`**（`par4987/lightroom-mcp` 的 npm 发布版，**56 个工具**）。

> 选型理由和其他候选的对比见 [`mcp-comparison.md`](mcp-comparison.md)。简单说：它是少数同时具备「渲染预览给模型看」「读写 Camera Raw 参数」「建虚拟副本保护原片」这三项关键能力的版本。

### 步骤 1：装包到固定位置

```powershell
$tools = "$env:USERPROFILE\lightroom-mcp"     # 换成你喜欢的位置
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Set-Location $tools

# 若 npm 报 EPERM（缓存目录无权限），把缓存也指到可写位置：
npm --cache "$tools\.npm-cache" install @pired/lightroom-mcp --no-audit --no-fund
```

**验证**：

```powershell
node "$tools\node_modules\@pired\lightroom-mcp\dist\index.js" --help
```

应输出 `MCP bridge to Adobe Lightroom Classic`。

### 步骤 2：安装 Lightroom 插件

```powershell
node "$tools\node_modules\@pired\lightroom-mcp\dist\index.js" install-plugin
```

输出 `Installed plugin: ...\Adobe\Lightroom\Modules\LightroomMCP.lrplugin`。

**手动兜底**：直接把 `dist\LightroomMCP.lrplugin` 复制到 `%APPDATA%\Adobe\Lightroom\Modules\`（目录不存在就创建）。

### 步骤 3：启动 Lightroom

**必须重启 Lightroom**（它只在启动时扫描 Modules 目录）。

> ### ⚠️ 关键一步：按 `G` 切到「图库」模块
>
> 插件设了 `LrForceInitPlugin = true`，但**强制初始化必须有一个菜单项作为触发点**，而这个插件只注册了**图库**菜单（`LrLibraryMenuItems`）。
>
> **如果 Lightroom 启动后停在「修改照片」模块，插件永远不会加载**，端口一直不监听。
> 详见 [坑 14](pitfalls.md#pit-14)。

**验证连接**：

```powershell
Get-Process Lightroom | Select-Object Id,StartTime
Get-NetTCPConnection -LocalPort 58763,58764 -State Listen |
  Select-Object LocalPort,OwningProcess
```

两个端口都有 `Listen`，且 `OwningProcess` = Lightroom 的 PID → **成功**。

> **注意**：这个插件**不会出现在「增效工具管理器」的插件列表里**。它没有自定义面板、不是导出/发布服务，所以列表是空的属正常现象。
> 它的入口在 **文件 → 增效工具额外信息 → "Lightroom MCP — Show Status"**。别因为列表空就以为没装上。

---

## 三、接入你的 AI 客户端

### 通用配置格式

大多数 MCP 客户端（Claude Desktop / Claude Code / Cursor / 自研客户端等）用的是同一套 JSON 结构：

```json
{
  "mcpServers": {
    "lightroom": {
      "command": "node",
      "args": ["<绝对路径>/node_modules/@pired/lightroom-mcp/dist/index.js"]
    }
  }
}
```

`args` 里的路径**必须是绝对路径**——用 `$tools\node_modules\...` 展开后的完整路径。

> 把 `toolCallTimeoutMs` 之类的超时调到 **120000ms** 以上。Lightroom 的有些操作（导出、AI 降噪）本来就慢，默认超时太短会误判为失败。

### DSH 的配置方式（实测环境）

DSH 用 `@deepseek-ai/dsh-mcp-client` 挂载外部 MCP 服务，配置文件是**用户补丁层**：

```
%USERPROFILE%\.dsh\profiles\web\cordis.patch.yml
```

该文件是**顶层 YAML 数组**，两种条目：

| 形式 | 作用 |
|---|---|
| `- id: <已有条目id>` + 其他字段 | **覆盖**已有条目。id 不存在会警告 `entry "x" not found` 并跳过 |
| `- insert:` + 列表 | **新增**顶层条目 |

> ⚠️ **新增 MCP 服务必须用 `insert:`**，直接写条目会因 "not found" 被**静默跳过**。

```yaml
- insert:
    - id: mcp-lightroom
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: lightroom
        transport: stdio
        command: node
        args:
          - '<绝对路径>\node_modules\@pired\lightroom-mcp\dist\index.js'
        toolCallTimeoutMs: 120000
```

工具会以 `mcp__lightroom__<工具名>` 出现。**改完配置必须重启 DSH**（MCP 服务在启动时加载）。

**验证桥进程被拉起**：

```powershell
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object { $_.CommandLine -match 'lightroom-mcp' } |
  Select-Object ProcessId,CreationDate
```

看到 `node ...lightroom-mcp\dist\index.js` = 客户端已自动拉起桥。

---

## 四、端到端验证

用仓库里的探针脚本确认整条链路：

```powershell
# 1. 握手 + 列出所有工具（应显示 56 个）
node scripts\mcp-probe.mjs "<绝对路径>\node_modules\@pired\lightroom-mcp\dist\index.js"

# 2. 实测调一个工具（id 换成你目录里真实的照片 id）
node scripts\lr-test.mjs get_photo_status '{"photo_ids":[12345]}'
```

`lr-test.mjs` 成功会返回真实目录数据（照片路径、评分等）。

---

## 五、故障排查

> 💡 先跑 `python doctor.py`，它覆盖了下面大部分检查。

### 症状：所有工具都超时 / 报「连不上」

按顺序查三件事：

1. **端口在不在** — `Get-NetTCPConnection -LocalPort 58763,58764 -State Listen`
   - **无输出** → 插件没启动。**先确认 Lightroom 停在「图库」模块**（按 `G`），然后重启 Lightroom。
2. **桥进程在不在** — `Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -match 'lightroom-mcp' }`
   - **无输出** → 客户端没挂载。检查 MCP 配置语法，然后重启客户端。
3. **锁文件有没有残留** — `%USERPROFILE%\.config\lightroom-mcp\bridge-*.lock`
   - 残留的锁会让新桥一直等待（日志出现 `Waiting for the previous Lightroom MCP bridge (pid N)`）。结束残留的 `node` 进程即可。

### 症状：插件日志完全没有新行

**这是最有用的判据。** 日志在 `<我的文档>\LrClassicLogs\LightroomMCP.log`。

- **有新行** → 插件活着，问题在别处（多半是某个具体动作被阻塞）
- **完全没新行**（连 `PluginInfoProvider loaded` 都没有）→ **插件压根没被加载**，不是端口冲突

后者的排查方向和前者完全不同。见 [坑 14](pitfalls.md#pit-14)。

### 症状：只有某个工具超时，其他正常

说明插件活着、**那个动作被阻塞**。

**实测 `get_photo_preview` 就是这种情况**（连续两次 90 秒超时）。
→ 改用 `export_photos` 导出到文件再读（[坑 2](pitfalls.md#pit-2)）。

### 症状：`select_photos` 返回 "Selected 0 of N"

照片不在 Lightroom 当前视图里。**让用户手动点左侧「目录」→「所有照片」**。

MCP **没有**切换视图源的工具（`manage_view_filter` 只管过滤器）。见 [坑 4](pitfalls.md#pit-4)。

### 症状：`create_virtual_copies` 报 `attempt to index a boolean value`

**同一个根因**（视图源）。因为它先选中源照片再克隆，选不中就克隆了个空选择，插件内部拿到空结果后崩。

报错信息完全指不到真正的原因——**先解决视图源问题**。

### 症状：npm install 报 EPERM

npm 缓存目录（`%LOCALAPPDATA%\npm-cache`）不可写。
→ `npm --cache "<可写路径>" install ...`

---

## 六、直读目录文件的限制（重要）

`scripts/lr_catalog.py` 可以直接读 `.lrcat`（加了 `immutable=1`，**不与 Lightroom 抢锁**），但**有时机限制**：

> **Lightroom 运行时不会实时把新照片写回目录文件。**

实测：刚建的虚拟副本，在 `Adobe_images` / `Adobe_imageDevelopSettings` 里**根本查不到**。新建的照片（含虚拟副本）**只存在 Lightroom 内存里**，直到落盘（退出时、或它的定期写入点）。

**正确用法**：

| 场景 | 用什么读 |
|---|---|
| Lightroom 开着，要读**当前**状态 | MCP 的 `get_develop_settings` |
| Lightroom 关着 | 直读 `.lrcat`（完整可靠） |
| 归纳历史风格分布 | 直读 `.lrcat`（已落盘的历史数据够用） |

**排查技巧**：想知道某张图是否已落盘，比对它的 id 和目录里的 `MAX(id_local)`：

```sql
SELECT MAX(id_local) FROM Adobe_images;
```

id 大于这个值 → 还没落盘。

---

## 七、端口与鉴权

- **端口**：`58763`（请求）、`58764`（响应），**仅监听 127.0.0.1**
- **鉴权**：`%USERPROFILE%\.config\lightroom-mcp\token`，由插件与桥自动协商，**无需手工配置**
- 桥的锁文件：`%USERPROFILE%\.config\lightroom-mcp\bridge-58763-58764.lock`
- `get_photo_preview` 的输出：`%USERPROFILE%\.config\lightroom-mcp\previews\`
