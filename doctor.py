#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightroom AI Grading —— 环境体检脚本（doctor）

用法：
    python doctor.py

它会逐项检查这台机器能不能跑本仓库的工作流：
    Python 版本 / numpy / Pillow、Node.js、Lightroom 进程、
    MCP 通信端口 58763+58764、Lua 插件是否安装、插件日志是否新鲜、
    MCP server 是否找得到、以及 git 里有没有混进客户照片等隐私文件。

每一项输出一行，前缀含义：
    [ OK ]   正常
    [WARN]   能跑，但建议修
    [FAIL]   跑不起来，必须先修（FAIL 项下面会缩进给出修复建议）

退出码：有 FAIL 退出 1，否则退出 0（方便被其他脚本/CI 调用）。

设计约束（为什么这么写）：
  * 只用 Python 标准库，不 import psutil —— 用户是摄影师，不该为了体检再装依赖。
  * 不写死任何用户名/绝对路径 —— 一律 expanduser / %APPDATA% / SHGetFolderPath，
    这样别人 clone 下去直接能用。
  * numpy / PIL 的检测放在子进程里做 —— 体检脚本自己绝不能因为缺依赖而崩，
    而且导入第三方包可能执行任意代码，隔离在子进程更安全。
  * 端口用 socket.connect_ex 探测，不解析 netstat 文本，跨语言/跨区域更稳。
  * 非 Windows 优雅降级：跳过进程与端口检查，只说明原因，不报错。
"""

from __future__ import annotations

import codecs
import ctypes
import fnmatch
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MIN_PYTHON = (3, 9)  # 仓库里其他脚本用了 3.9 的语法特性
PLUGIN_DIR_NAME = "LightroomMCP.lrplugin"
PLUGIN_LOG_NAME = "LightroomMCP.log"
MCP_PACKAGE_REL = Path("node_modules") / "@pired" / "lightroom-mcp" / "dist" / "index.js"
PORT_PLUGIN_COMMAND = 58763  # Lightroom 插件 → MCP server
PORT_PLUGIN_EVENT = 58764    # MCP server → Lightroom 插件（事件回传）
SENSITIVE_PATTERNS = ("*.CR3", "*.cr3", "*.jpg", "*.jpeg", "*.lrcat", "*.lrdata", "*.log")
LOG_STALE_HOURS = 24  # 日志超过这个时间没更新，基本说明插件没被 Lightroom 加载
SUBPROCESS_TIMEOUT = 20  # 所有子进程硬超时，tasklist/netstat 卡住也不能让体检挂死
NETSTAT_TIMEOUT = 30  # netstat -ano 输出很大，给宽一点

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
STATUS_TAG = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[SKIP]"}

REPO_ROOT = Path(__file__).resolve().parent


def init_console_encoding() -> None:
    """强制中文输出用 UTF-8，避免 Windows 上一片乱码。

    为什么需要：中文 Windows 的控制台默认是 CP936(GBK)，而这个文件是 UTF-8。
    一旦终端和脚本的编码对不上，用户看到的就是「�ֿ�Ŀ¼」这种东西 ——
    对一个给摄影师用的体检脚本来说，输出乱码等于不可用。
    这里同时把「控制台代码页」和「Python 的 stdout」都掰到 UTF-8。
    """
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # UTF-8
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            # 被重定向/替换过的流没有 reconfigure，忽略即可
            pass


class Check:
    """一条检查结果。hint 只在需要用户动手时才填。"""

    def __init__(self, status: str, title: str, hint: str = "") -> None:
        self.status = status
        self.title = title
        self.hint = hint


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


def decode_output(raw: bytes) -> str:
    """把子进程输出解成文本。

    为什么这么啰嗦：中文 Windows 的 tasklist/netstat 输出是 GBK(CP936)，
    直接按 UTF-8 解会变乱码甚至抛异常。这里按 UTF-8 → 系统 ANSI → 宽松兜底依次尝试。
    """
    if not raw:
        return ""
    for enc in ("utf-8", "cp936" if os.name == "nt" else "utf-8", "mbcs" if os.name == "nt" else "utf-8"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # 最后一层：用系统首选编码宽松解码，保证绝不抛异常
    try:
        return raw.decode(codecs.getpreferredencoding(False) or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("latin-1", errors="replace")


def run_command(args: list[str], timeout: int = SUBPROCESS_TIMEOUT) -> tuple[int, str]:
    """跑一条外部命令，返回 (returncode, 输出文本)。失败一律返回 (-1, "")，绝不抛异常。"""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    combined = decode_output(proc.stdout) + decode_output(proc.stderr)
    return proc.returncode, combined.strip()


def timed_run(args: list[str], timeout: int = SUBPROCESS_TIMEOUT) -> tuple[int, str]:
    """同 run_command，但失败时把原因写成文本，方便在报告里说清楚。"""
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False, shell=False)
    except FileNotFoundError:
        return -1, "command not found"
    except subprocess.TimeoutExpired:
        return -2, "timeout"
    except OSError as exc:
        return -3, f"oserror: {exc}"
    return proc.returncode, (decode_output(proc.stdout) + decode_output(proc.stderr)).strip()


def shell_folder(name: str) -> Path | None:
    """用 SHGetFolderPathW 问 Windows「我的文档」到底在哪。

    为什么不用 ~/Documents 猜：很多人把「文档」重定向到了 OneDrive 或 D 盘，
    猜错会导致误报「插件日志不存在」。
    """
    if os.name != "nt":
        return None
    # CSIDL: 0x0005 = 我的文档, 0x001a = APPDATA
    csidl = {"documents": 0x0005, "appdata": 0x001A}.get(name)
    if csidl is None:
        return None
    try:
        buf = ctypes.create_unicode_buffer(260)
        # SHGFP_TYPE_CURRENT = 0
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except (AttributeError, OSError):
        return None
    return None


def appdata_dir() -> Path | None:
    """%APPDATA% 目录；环境变量缺失时退回到 shell 查询/家目录。"""
    env = os.environ.get("APPDATA")
    if env:
        return Path(env)
    found = shell_folder("appdata")
    if found:
        return found
    if os.name == "nt":
        return Path(os.path.expanduser("~")) / "AppData" / "Roaming"
    return None


def documents_dir() -> Path:
    """「我的文档」目录，找不到就退回家目录（不写死用户名）。"""
    found = shell_folder("documents")
    if found:
        return found
    return Path(os.path.expanduser("~")) / "Documents"


def human_age(seconds: float) -> str:
    """把秒数说成人话：刚刚 / N 分钟前 / N 小时前 / N 天前。"""
    if seconds < 0:
        seconds = 0
    if seconds < 90:
        return "刚刚"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} 分钟前"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} 小时前"
    return f"{hours / 24:.1f} 天前"


# ---------------------------------------------------------------------------
# 检查 1：Python 版本 + numpy / PIL
# ---------------------------------------------------------------------------


def check_python() -> list[Check]:
    """检查 Python 版本。

    为什么查：仓库里的 contact_sheet.py、histo.py 等脚本都要求 3.9+，
    版本太低会以各种奇怪的语法错误失败，用户根本看不懂。
    """
    version = ".".join(str(n) for n in sys.version_info[:3])
    if sys.version_info[:2] >= MIN_PYTHON:
        return [Check(OK, f"Python 版本 {version}（要求 ≥ {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）")]
    return [
        Check(
            FAIL,
            f"Python 版本 {version} 过低（要求 ≥ {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）",
            "去 python.org 装 3.9 或更高版本；Windows 装的时候勾上「Add python.exe to PATH」，"
            "装完重开一个终端再跑 python doctor.py。",
        )
    ]


def check_dependencies() -> list[Check]:
    """在子进程里试 import numpy / PIL。

    为什么放子进程：(1) 体检脚本自己绝不能因为缺依赖崩掉；
    (2) import 第三方包会执行它的代码，隔离掉更安全。
    """
    probe = (
        "import json\n"
        "r = {}\n"
        "for m in ('numpy', 'PIL'):\n"
        "    try:\n"
        "        mod = __import__(m)\n"
        "        r[m] = 'ok:' + str(getattr(mod, '__version__', '?'))\n"
        "    except BaseException as exc:\n"
        "        r[m] = 'err:' + type(exc).__name__\n"
        "print(json.dumps(r))\n"
    )
    exe = sys.executable or "python"
    rc, out = timed_run([exe, "-c", probe], timeout=60)
    if rc != 0:
        why = "解释器启动失败" if rc == -1 else ("超时" if rc == -2 else f"退出码 {rc}")
        return [
            Check(
                FAIL,
                f"numpy / Pillow 依赖检测失败（{why}）",
                "先确认 python 能正常启动；然后执行：python -m pip install --upgrade numpy pillow",
            )
        ]

    payload = out.splitlines()[-1] if out else "{}"
    try:
        data = json.loads(payload)
    except (ValueError, IndexError):
        return [
            Check(
                FAIL,
                "numpy / Pillow 依赖检测失败（无法解析检测结果）",
                "执行：python -m pip install --upgrade numpy pillow",
            )
        ]

    checks: list[Check] = []
    for module, label, why in (
        ("numpy", "numpy", "拼图/直方图/水平校正脚本要用它算像素"),
        ("PIL", "Pillow (PIL)", "读图、生成预览、导出对比图要用它"),
    ):
        value = str(data.get(module, "err:NotFound"))
        if value.startswith("ok:"):
            checks.append(Check(OK, f"依赖 {label} 可导入（{value[3:]}）"))
        else:
            checks.append(
                Check(
                    FAIL,
                    f"依赖 {label} 缺失或损坏（{value[4:]}）—— {why}",
                    f"执行：python -m pip install --upgrade {label.split()[0].lower()}"
                    "（装完重跑 python doctor.py 确认）",
                )
            )
    return checks


# ---------------------------------------------------------------------------
# 检查 2：Node.js
# ---------------------------------------------------------------------------


def check_node() -> list[Check]:
    """检查 node 在不在。

    为什么查：MCP server（@pired/lightroom-mcp）是 Node.js 程序，
    没有 node 就没有这台「桥」，AI 完全连不上 Lightroom。
    """
    rc, out = timed_run(["node", "--version"])
    if rc == 0 and out:
        first = out.splitlines()[0].strip()
        m = re.search(r"v?(\d+)\.(\d+)", first)
        if m and int(m.group(1)) >= 18:
            return [Check(OK, f"Node.js 已安装（{first}）")]
        if m:
            return [
                Check(
                    WARN,
                    f"Node.js 版本偏旧（{first}，建议 ≥ v18）",
                    "去 https://nodejs.org 装 LTS 版覆盖安装，然后重开终端。",
                )
            ]
        return [Check(OK, f"Node.js 已安装（{first}）")]
    if rc == -1 or "not found" in out:
        return [
            Check(
                FAIL,
                "Node.js 未安装（找不到 node 命令）",
                "去 https://nodejs.org 下载 LTS 版装上；安装时保持默认选项，"
                "装完必须重开一个终端（PATH 才会生效），再跑 python doctor.py。",
            )
        ]
    return [
        Check(
            FAIL,
            f"Node.js 存在但无法执行（退出码 {rc}）",
            "在终端里手动执行 node --version 看具体报错；若是权限/杀软拦截，把 node.exe 加入白名单。",
        )
    ]


# ---------------------------------------------------------------------------
# 检查 3：Lightroom 进程
# ---------------------------------------------------------------------------


def process_names() -> dict[str, str]:
    """返回 {pid: 进程名}。Windows 用 tasklist（带超时 + 编码兜底）。"""
    table: dict[str, str] = {}
    if os.name != "nt":
        return table
    rc, out = timed_run(["tasklist", "/FO", "CSV", "/NH"])
    if rc != 0:
        return table
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            table[parts[1]] = parts[0].strip('"')
    return table


def check_lightroom_process() -> list[Check]:
    """检查 Lightroom Classic 在不在跑。

    为什么查：插件跑在 Lightroom 进程内部。Lightroom 没开，
    端口、日志、全部调色操作都不可能工作 —— 这是所有问题的第一嫌疑。
    """
    if os.name != "nt":
        return [Check(SKIP, "Lightroom 进程检查已跳过（当前不是 Windows）")]
    procs = process_names()
    if not procs:
        return [
            Check(
                WARN,
                "无法枚举进程（tasklist 执行失败）",
                "在终端手动执行 tasklist 看看是否被安全软件拦截；不影响其余检查结果。",
            )
        ]
    hits = {pid: name for pid, name in procs.items() if name.lower().startswith("lightroom")}
    if hits:
        detail = ", ".join(f"{name} (PID {pid})" for pid, name in sorted(hits.items()))
        return [Check(OK, f"Lightroom Classic 正在运行（{detail}）")]
    return [
        Check(
            FAIL,
            "Lightroom Classic 没有运行",
            "先打开 Adobe Lightroom Classic，等它完全启动、进入图库模块（按 G），"
            "再重新跑 python doctor.py。插件只在 Lightroom 运行时才活着。",
        )
    ]


# ---------------------------------------------------------------------------
# 检查 4：端口 58763 / 58764
# ---------------------------------------------------------------------------


def probe_tcp(port: int, timeout: float = 2.5) -> int:
    """用 connect_ex 探测端口，返回 0 表示连上了。

    为什么用 socket 而不是解析 netstat：netstat 的输出会随系统语言变，
    解析文本很脆；connect_ex 是直接问操作系统「这个端口有人接吗」，最可靠。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port))
    except OSError:
        return -1
    finally:
        sock.close()


def port_owners() -> dict[int, tuple[str, str]]:
    """返回 {端口: (进程名, PID)}。优先 Get-NetTCPConnection，失败再退回 netstat。

    说明：这一步只是为了在报告里说清「端口到底是谁占的」，探测本身用 socket。
    """
    owners: dict[int, tuple[str, str]] = {}
    if os.name != "nt":
        return owners
    pids = process_names()
    ps = (
        "Get-NetTCPConnection -State Listen,Established -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -in 58763,58764 } | "
        "ForEach-Object { \"$($_.LocalPort),$($_.OwningProcess)\" }"
    )
    rc, out = timed_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=NETSTAT_TIMEOUT)
    if rc == 0 and out:
        for line in out.splitlines():
            bits = line.strip().split(",")
            if len(bits) == 2 and bits[0].isdigit() and bits[1].isdigit():
                owners[int(bits[0])] = (pids.get(bits[1], "未知进程"), bits[1])
        if owners:
            return owners

    rc, out = timed_run(["netstat", "-ano"], timeout=NETSTAT_TIMEOUT)
    if rc == 0:
        for line in out.splitlines():
            bits = line.split()
            # 形如: TCP  127.0.0.1:58763  0.0.0.0:0  LISTENING  1234
            if len(bits) >= 4 and bits[0].upper() == "TCP":
                addr, pid = bits[1], bits[-1]
                if ":" not in addr or not pid.isdigit():
                    continue
                port_txt = addr.rsplit(":", 1)[1]
                if port_txt.isdigit() and int(port_txt) in (PORT_PLUGIN_COMMAND, PORT_PLUGIN_EVENT):
                    owners[int(port_txt)] = (pids.get(pid, "未知进程"), pid)
    return owners


def check_ports() -> list[Check]:
    """检查插件与 MCP server 之间的两个端口。

    为什么查：这是判断「Lua 插件到底加载成功没有」最硬的指标 ——
    插件加载后会在 58763 上等命令，MCP server 连上它，58764 用于事件回传。
    端口不通 = AI 永远连不上 Lightroom，无论你怎么点。

    探测结果有三种，必须区分开（真实踩坑）：
      * connect_ex == 0      → 通了，端口活着
      * 连接被拒绝(WSAECONNREFUSED) → 没人在听，插件没加载
      * 超时(WSAEWOULDBLOCK) → 端口上已有连接在通信，而 Windows 对同一台机器
                               到「已建立连接」的端口发起的二次连接会直接短路，
                               于是新探测连接超时。这时端口其实是好的，不能误报成 FAIL。
    判据是 netstat：看到 58763/58764 处于 ESTABLISHED 只证明**连接存在**，
    不证明桥会应答 —— 桥僵死时连接照样在，但每条调用都超时（见 docs/pitfalls.md 坑 20）。
    端口一旦被人占用，临时探测连接就探不进去，这是本机回环的固有行为，不是故障。
    """
    if os.name != "nt":
        return [Check(SKIP, "端口检查已跳过（当前不是 Windows，仅 Windows 使用本地端口桥）")]

    owners = port_owners()
    checks: list[Check] = []

    for port in (PORT_PLUGIN_COMMAND, PORT_PLUGIN_EVENT):
        rc = probe_tcp(port)
        owner_name, owner_pid = owners.get(port, ("", ""))
        who = f"，占用进程 {owner_name} (PID {owner_pid})" if owner_name else ""
        role = "命令端口" if port == PORT_PLUGIN_COMMAND else "事件端口"

        if rc == 0:
            checks.append(Check(OK, f"端口 {port} 可连接（{role}{who}）"))
        elif port in owners:
            checks.append(Check(OK, f"端口 {port} 已在通信中（{role}{who}）—— 本机回环探测被短路，属正常；"
                                  "但连接存在≠插件在应答（桥僵死时也长这样，见坑 20）"))
        elif rc in (10060, 10035, -1):
            checks.append(
                Check(
                    FAIL,
                    f"端口 {port} 连接超时，且查不到监听进程（{role}）",
                    "多半是安全软件/防火墙拦了本地回环端口：把 58763、58764 加入放行规则，"
                    "或临时关掉第三方杀软的网络防护后重试。",
                )
            )
        else:
            checks.append(
                Check(
                    FAIL,
                    f"端口 {port} 没有进程监听（{role}，错误码 {rc}）—— Lua 插件没有加载成功",
                    "1) 打开 Lightroom → 文件 → 增效工具管理器，确认 LightroomMCP 已启用且没有报错；"
                    "2) 按 G 切换到图库模块（插件菜单只在图库/ Develop 下刷新）；"
                    "3) 重启 Lightroom；4) 还不行就重装插件后重启 Lightroom。",
                )
            )
    return checks


# ---------------------------------------------------------------------------
# 检查 5：Lua 插件是否安装
# ---------------------------------------------------------------------------


def plugin_dir() -> Path | None:
    """插件目录：%APPDATA%\\Adobe\\Lightroom\\Modules\\LightroomMCP.lrplugin"""
    base = appdata_dir()
    if base is None:
        return None
    return base / "Adobe" / "Lightroom" / "Modules" / PLUGIN_DIR_NAME


def check_plugin_installed() -> list[Check]:
    """检查 Lua 插件目录和 Info.lua。

    为什么查：Info.lua 是 Lightroom 识别一个增效工具的入口文件，
    没有它 Lightroom 直接忽略整个目录 —— 装错位置的经典症状。
    """
    target = plugin_dir()
    if target is None:
        return [Check(SKIP, "插件目录检查已跳过（当前不是 Windows，Lightroom 插件路径仅 Windows 适用）")]

    if not target.is_dir():
        return [
            Check(
                FAIL,
                f"Lua 插件未安装（找不到 {target}）",
                "把仓库里的 LightroomMCP.lrplugin 整个文件夹复制到上面这个 Modules 目录下"
                "（注意是复制整个文件夹，不是里面的文件），然后重启 Lightroom。",
            )
        ]

    info = target / "Info.lua"
    if info.is_file():
        return [Check(OK, f"Lua 插件已安装（{target}）")]
    return [
        Check(
            FAIL,
            f"插件目录存在但缺少 Info.lua（{target}）",
            "说明插件复制不完整（只复制了部分文件）。删掉这个目录，"
            "重新把完整的 LightroomMCP.lrplugin 文件夹复制过去，再重启 Lightroom。",
        )
    ]


# ---------------------------------------------------------------------------
# 检查 6：插件日志新鲜度
# ---------------------------------------------------------------------------


def log_candidates() -> list[Path]:
    """插件日志可能出现的位置，按优先级排。

    主路径是 <我的文档>\\LrClassicLogs\\LightroomMCP.log；但有人把「文档」重定向到
    OneDrive，或者 Lightroom 回退到家目录，所以多准备几个候选，避免误报「日志不存在」。
    """
    names = ("LrClassicLogs", "LightroomLogs", "LrClassicLog")
    roots = [documents_dir(), Path(os.path.expanduser("~")), Path(os.path.expanduser("~")) / "Documents"]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        for name in names:
            path = root / name / PLUGIN_LOG_NAME
            if path not in seen:
                seen.add(path)
                candidates.append(path)
    return candidates


def ports_established() -> set[int]:
    """返回当前处于 ESTABLISHED 状态的插件端口集合。

    为什么需要：端口上真的有连接，是「插件活着、桥已连上」的**直接证据**，
    比日志时间戳可靠得多。日志只在**有请求**时才写，所以「日志旧」完全可能
    只是「这几天没修图」，而不是插件坏了。实测踩过：Lightroom 已运行 28 小时、
    两个端口都 ESTABLISHED，但日志停在 37 小时前——报 FAIL 会把好环境说成坏的。
    """
    found: set[int] = set()
    if os.name != "nt":
        return found
    ps = (
        "Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -in 58763,58764 } | "
        "ForEach-Object { $_.LocalPort }"
    )
    rc, out = timed_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=NETSTAT_TIMEOUT)
    if rc == 0:
        for line in out.splitlines():
            token = line.strip()
            if token.isdigit():
                found.add(int(token))
    return found


def check_plugin_log() -> list[Check]:
    """检查插件日志最后写入时间。

    为什么查：日志能反映插件的加载历史。但**日龄不能单独用来判定插件死活** ——
    日志只在有请求时才追加，所以「很久没更新」最常见的含义其实是「最近没修图」。

    因此判定顺序是：日志新鲜 → OK；日志旧 → **再看端口有没有 ESTABLISHED 连接**，
    有连接就说明插件活着（此时日志旧是正常的）；两者都不成立才报 FAIL。
    """
    existing = [p for p in log_candidates() if p.is_file()]
    if not existing:
        return [
            Check(
                WARN,
                "找不到插件日志 LrClassicLogs\\LightroomMCP.log（插件可能从未成功加载）",
                "先确认插件已装好并重启过 Lightroom，然后在 Lightroom 里随便用一次"
                "「增效工具 → LightroomMCP → 显示状态」；若仍无日志，检查 Lightroom 的"
                "增效工具管理器里该插件是不是显示为已启用。",
            )
        ]

    newest = max(existing, key=lambda p: p.stat().st_mtime)
    try:
        mtime = datetime.fromtimestamp(newest.stat().st_mtime)
    except (OSError, OverflowError, ValueError):
        return [Check(WARN, f"插件日志时间戳无法读取（{newest}）", "删除该日志文件后重启 Lightroom 让它重新生成。")]

    age = (datetime.now() - mtime).total_seconds()
    stamp = mtime.strftime("%Y-%m-%d %H:%M:%S")
    if age <= LOG_STALE_HOURS * 3600:
        return [Check(OK, f"插件日志新鲜（最后更新 {stamp}，{human_age(age)}）")]

    # 日志旧 —— 但不能据此判死刑，先看端口上有没有活连接。
    live = ports_established()
    if live:
        ports_txt = "、".join(str(p) for p in sorted(live))
        return [
            Check(
                OK,
                f"插件日志已 {human_age(age)} 没更新（最后更新 {stamp}），"
                f"但端口 {ports_txt} 正处于 ESTABLISHED —— 插件活着，只是这段时间没有请求（属正常）",
            )
        ]

    return [
        Check(
            FAIL,
            f"插件日志已 {human_age(age)} 没更新（最后更新 {stamp}），且端口没有连接 —— 插件没有被加载",
            "1) Lightroom → 文件 → 增效工具管理器，确认 LightroomMCP 已勾选启用；"
            "2) 启用后必须完全退出并重启 Lightroom，**重启后按 G 切到「图库」模块**"
            "（插件只在图库模块强制初始化，见 pitfalls 坑 14）；"
            f"3) 日志文件在 {newest}，删掉它再重启 Lightroom，看是否重新生成。",
        )
    ]


# ---------------------------------------------------------------------------
# 检查 7：MCP server 是否找得到
# ---------------------------------------------------------------------------


def find_mcp_server() -> tuple[Path | None, list[Path]]:
    """在几个合理位置找 @pired/lightroom-mcp 的 dist/index.js，返回 (找到的入口, 尝试过的路径)。

    为什么查：这个入口就是 MCP server 本体。找不到它，AI 客户端里的 lightroom
    服务会启动失败，表现为「工具列表里没有 lightroom」。
    """
    tried: list[Path] = []
    seen: set[Path] = set()

    def consider(base: Path) -> Path | None:
        if base in seen:
            return None
        seen.add(base)
        candidate = base / MCP_PACKAGE_REL
        tried.append(candidate)
        return candidate if candidate.is_file() else None

    # 1) 仓库目录本身，以及它的各级父目录（很多人在项目上一级装依赖）
    for base in [REPO_ROOT, *REPO_ROOT.parents]:
        hit = consider(base)
        if hit:
            return hit, tried

    # 2) 当前工作目录（用户可能在别处跑 doctor.py）
    cwd_bases: list[Path] = []
    try:
        cwd = Path.cwd()
        for base in (cwd, cwd.parent):
            hit = consider(base)
            if hit:
                return hit, tried
            cwd_bases.append(base)
    except OSError:
        pass

    # 3) 常见的手工安装位置：把依赖集中装在项目旁边的 _ai_tools 里，是很多人的习惯
    guesses = [REPO_ROOT.parent / "_ai_tools", Path(os.path.expanduser("~")) / "_ai_tools"]
    guesses += [base / "_ai_tools" for base in cwd_bases]
    for guess in guesses:
        hit = consider(guess)
        if hit:
            return hit, tried

    return None, tried


def read_package_version(entry: Path) -> str:
    """从入口文件往上找最近的 package.json 读 version，读不到就说「未知」。"""
    for parent in [entry.parent, *entry.parents]:
        pkg = parent / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            name = data.get("name", "@pired/lightroom-mcp")
            version = data.get("version", "未知")
            return f"{name}@{version}（{pkg}）"
    return f"入口已找到但读不到 package.json 版本（{entry}）"


def check_mcp_server() -> list[Check]:
    """检查 MCP server 入口文件和版本号。"""
    entry, tried = find_mcp_server()
    if entry is not None:
        return [Check(OK, f"MCP server 已就位：{read_package_version(entry)}")]

    head = "\n".join(f"       - {p}" for p in tried[:3])
    tail = "\n".join(f"       - {p}" for p in tried[-3:])
    return [
        Check(
            FAIL,
            "在常见位置找不到 MCP server（@pired/lightroom-mcp 的 dist/index.js）",
            "在仓库目录执行：npm install @pired/lightroom-mcp\n"
            f"    已查找：\n{head}\n       …\n{tail}\n"
            "    如果你早把它装在别处，可以不改动：只要 AI 客户端的 lightroom server "
            "指向那个 index.js 就能用（路径见 README）。",
        )
    ]


# ---------------------------------------------------------------------------
# 检查 8 / 9：git 卫生
# ---------------------------------------------------------------------------


def is_git_repo(path: Path) -> bool:
    rc, out = timed_run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"])
    return rc == 0 and out.strip().lower().startswith("true")


def git_tracked_files(repo: Path) -> list[str]:
    """列出被 git 跟踪的文件（相对仓库根）。"""
    rc, out = timed_run(["git", "-C", str(repo), "ls-files"], timeout=60)
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def check_git_hygiene() -> list[Check]:
    """检查有没有把客户照片/目录文件提交进 git。

    为什么查：这是本仓库最容易出的隐私事故 —— 一张客户婚礼原片（.CR3）、
    一份 .lrcat 目录、一张导出图，一旦 push 到公开 GitHub，
    就是不可撤回的泄露，而且 git 历史里的东西删不干净。
    """
    if not is_git_repo(REPO_ROOT):
        return [
            Check(
                SKIP,
                f"git 卫生检查已跳过（{REPO_ROOT} 不是 git 仓库，或本机没装 git）—— 尚未纳入版本控制，无泄露风险",
            )
        ]

    tracked = git_tracked_files(REPO_ROOT)
    if not tracked:
        return [Check(WARN, "git 仓库已初始化但还没有跟踪任何文件（或 git ls-files 执行失败）")]

    grouped: dict[str, list[str]] = {}
    for rel in tracked:
        name = Path(rel).name
        for pattern in SENSITIVE_PATTERNS:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                grouped.setdefault(pattern.lower(), []).append(rel)
                break

    if not grouped:
        return [Check(OK, f"git 未跟踪敏感文件（已检查 {len(tracked)} 个文件：照片、.lrcat、.lrdata、日志）")]

    lines = []
    for pattern, files in sorted(grouped.items()):
        sample = "、".join(files[:3]) + ("…" if len(files) > 3 else "")
        lines.append(f"{pattern} × {len(files)}（{sample}）")
    detail = "；".join(lines)
    total = sum(len(v) for v in grouped.values())
    return [
        Check(
            FAIL,
            f"git 里有 {total} 个敏感文件被跟踪 —— 客户照片/目录文件泄露风险！",
            f"命中：{detail}\n"
            "    立刻处理（push 之前还来得及）：\n"
            "      1) git rm --cached <文件>          # 只从 git 移除，磁盘文件保留\n"
            "      2) 把规则写进 .gitignore（*.CR3、*.jpg、*.lrcat、*.lrdata、*.log）\n"
            "      3) 如果这些文件已经被 push 过，历史里仍然有，需要改写历史或直接删库重建\n"
            "      4) 已经推到公开仓库的话，视为已泄露：立刻撤下并通知相关方",
        )
    ]


def check_gitignore() -> list[Check]:
    """检查 .gitignore 存在且真的生效。

    为什么查：没有 .gitignore，下一次 git add . 就会把客户照片一起提交；
    存在但没被跟踪的 .gitignore 等于没有 —— 别人 clone 下来照样裸奔。
    """
    if not is_git_repo(REPO_ROOT):
        return [Check(SKIP, "gitignore 检查已跳过（当前目录不是 git 仓库）")]

    path = REPO_ROOT / ".gitignore"
    if not path.is_file():
        return [
            Check(
                FAIL,
                "git 仓库里没有 .gitignore（下一次 git add . 会把客户照片一起提交）",
                "在仓库根目录新建 .gitignore，至少写入：\n"
                "      *.CR3\n      *.cr3\n      *.jpg\n      *.jpeg\n      *.lrcat\n"
                "      *.lrdata/\n      *.log\n      node_modules/",
            )
        ]

    tracked = set(git_tracked_files(REPO_ROOT))
    if ".gitignore" not in tracked:
        return [
            Check(
                WARN,
                ".gitignore 存在但还没被 git 跟踪（推上去别人 clone 下来不受保护）",
                "执行：git add .gitignore && git commit -m \"add .gitignore\"",
            )
        ]

    content = path.read_text(encoding="utf-8", errors="replace")
    missing = [p for p in ("*.CR3", "*.lrcat", "*.lrdata") if p.lower() not in content.lower()]
    if missing:
        return [
            Check(
                WARN,
                f".gitignore 已生效，但缺少关键规则：{'、'.join(missing)}",
                "把这些规则补进 .gitignore（.lrcat 是目录数据库，*.lrdata 是预览缓存，都可能含客户照片）。",
            )
        ]
    return [Check(OK, ".gitignore 已生效且包含照片/目录类规则")]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def print_header() -> None:
    print("=" * 72)
    print(" Lightroom AI Grading —— 环境体检 (doctor)")
    print(f" 仓库目录 : {REPO_ROOT}")
    print(f" 工作目录 : {Path.cwd()}")
    print(f" 系统平台 : {sys.platform}    Python: {sys.executable or '未知'}")
    print(f" 体检时间 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print()


def print_check(item: Check) -> None:
    print(f"{STATUS_TAG.get(item.status, '[????]')} {item.title}")
    if item.hint and item.status in (FAIL, WARN):
        for line in item.hint.splitlines():
            print(f"       → {line}" if not line.startswith(" ") else f"       {line}")


def main() -> int:
    init_console_encoding()
    print_header()

    checks: list[Check] = []
    # 每项检查都自己捕获异常：体检脚本自己崩掉是最糟的体验
    for step in (
        check_python,
        check_dependencies,
        check_node,
        check_lightroom_process,
        check_ports,
        check_plugin_installed,
        check_plugin_log,
        check_mcp_server,
        check_git_hygiene,
        check_gitignore,
    ):
        try:
            checks.extend(step())
        except Exception as exc:  # noqa: BLE001 - 体检脚本必须跑到底
            checks.append(
                Check(
                    WARN,
                    f"检查项 {step.__name__} 内部出错（{type(exc).__name__}: {exc}）",
                    "这一项没查成，其余项结果仍然有效；可以把这行报给仓库作者。",
                )
            )

    for item in checks:
        print_check(item)

    passed = sum(1 for c in checks if c.status == OK)
    warned = sum(1 for c in checks if c.status == WARN)
    failed = sum(1 for c in checks if c.status == FAIL)
    skipped = sum(1 for c in checks if c.status == SKIP)

    print()
    print("-" * 72)
    summary = f"统计：通过 {passed} 项，警告 {warned} 项，失败 {failed} 项"
    if skipped:
        summary += f"，跳过 {skipped} 项"
    print(summary)

    if failed:
        print("结论：有 FAIL，环境还跑不起来。先按上面的 → 建议逐条修，然后重跑 python doctor.py。")
        return 1
    if warned:
        print("结论：没有硬性错误，但有几条警告，建议顺手处理掉。")
        return 0
    print("结论：全部通过，可以开始调色了。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
