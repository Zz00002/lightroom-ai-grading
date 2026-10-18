// 直连插件探针：绕过 MCP 桥，直接问 Lua 插件「你还活着吗」。
//
// 用法: node scripts/ping-plugin.mjs
//
// 为什么需要它：桥僵死时（见 docs/pitfalls.md#pit-20），每一条工具调用都返回
// 「Connected to the Lightroom plugin's ports, but it is not answering」——
// 这句话把锅甩给「另一个进程占着连接」，但你没法只凭报错判断到底是插件死了
// 还是桥僵死了。这个脚本给出第三种证据：**绕开桥，直接和插件握手**。
//
// ⚠️ 重要前提：插件**同一时刻只服务一个客户端**。如果桥正健康地连着，你这第二
// 条连接会被插件**静默忽略**（不报错、不打日志、就是没回应）。所以：
//   * 没回应 ≠ 插件死了，先看下面打印的桥 PID
//   * 真正的判定顺序是：先杀桥 → 再跑本脚本 → 秒回 pong 就说明插件好着，
//     问题在桥（DSH 会自动重启桥，3 秒后一切恢复）
import net from 'node:net'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const REQUEST_PORT = 58763
const RESPONSE_PORT = 58764
const TIMEOUT_MS = 6000

const tokenPath = process.env.LIGHTROOM_MCP_TOKEN_PATH
  ?? path.join(os.homedir(), '.config', 'lightroom-mcp', 'token')
const lockPath = path.join(os.homedir(), '.config', 'lightroom-mcp', `bridge-${REQUEST_PORT}-${RESPONSE_PORT}.lock`)

function readToken() {
  try {
    return fs.readFileSync(tokenPath, 'utf8').trim()
  } catch {
    console.error(`✗ 找不到 token: ${tokenPath}`)
    console.error('  → 在 Lightroom 里「文件 > 增效工具管理器」对 LightroomMCP 点 Start Server 生成。')
    process.exit(2)
  }
}

const token = readToken()

let bridgePid = null
try {
  const raw = fs.readFileSync(lockPath, 'utf8').trim()
  if (/^\d+$/.test(raw)) bridgePid = raw
} catch { /* 桥没起过，正常 */ }

function pidAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

console.log(`token        : ${tokenPath} (${token.length} 字节)`)
console.log(`桥的锁文件   : ${bridgePid ? `PID ${bridgePid}${pidAlive(bridgePid) ? '（活着）' : '（已死，锁是残留）'}` : '没有锁文件（桥没起过）'}`)

const req = net.connect(REQUEST_PORT, '127.0.0.1')
const res = net.connect(RESPONSE_PORT, '127.0.0.1')
req.setEncoding('utf8')
res.setEncoding('utf8')

let answered = false
let sent = false

req.on('connect', () => {
  sent = true
  req.write(JSON.stringify({ hello: token, id: 'ping_doctor', action: 'ping', params: {} }) + '\n')
})
req.on('error', (e) => console.error(`  request 端口错误: ${e.message}`))
res.on('error', (e) => console.error(`  response 端口错误: ${e.message}`))
res.on('data', (chunk) => {
  answered = true
  let parsed
  try { parsed = JSON.parse(String(chunk).trim()) } catch { parsed = null }
  if (parsed?.result?.pong) {
    console.log('✓ 插件回了 pong —— Lua 插件是活的')
  } else {
    console.log(`? 收到无法识别的内容: ${String(chunk).trim().slice(0, 200)}`)
  }
})

setTimeout(() => {
  req.destroy()
  res.destroy()

  if (answered) {
    console.log('\n判定：插件健康。若工具仍报「not answering」，说明是**桥**僵死（坑 20）：')
    console.log('  → 桥会被 MCP 客户端自动重启；若 3 秒后仍未恢复，手动杀掉它再等它重启：')
    console.log(bridgePid ? `  Stop-Process -Id ${bridgePid} -Force` : '  （先找到桥 PID：netstat -ano | findstr 58763）')
    process.exit(0)
  }

  console.log('\n判定：没有收到 pong。两种可能，别急着重启 Lightroom：')
  if (!sent) {
    console.log('  (a) 端口连不上 → 插件没加载，走坑 14：按 G 切图库模块 → 增效工具管理器 → 重启 Lightroom')
  } else {
    console.log('  (b) 端口连上了但没人应答 → 最可能是**桥正占着唯一的客户端槽位**（插件一次只服务一个客户端）')
    console.log(bridgePid
      ? `      → 先杀桥再跑一次本脚本：Stop-Process -Id ${bridgePid} -Force`
      : '      → 先杀掉桥，再跑一次本脚本')
    console.log('      → 杀掉后仍无回应，才怀疑插件本身（坑 14）')
  }
  process.exit(1)
}, TIMEOUT_MS)
