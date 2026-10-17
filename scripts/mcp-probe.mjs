// 最小 MCP stdio 客户端：握手 + 列出工具，验证服务端可用。
// 用法: node scripts/mcp-probe.mjs <server.js 的绝对路径>
//   例如: node scripts/mcp-probe.mjs "C:\path\to\node_modules\@pired\lightroom-mcp\dist\index.js"
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

const serverPath = process.argv[2]
if (!serverPath) {
  console.error('用法: node mcp-probe.mjs <server.js 绝对路径>')
  process.exit(1)
}

const child = spawn(process.execPath, [serverPath], {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: { ...process.env },
})

let nextId = 1
const pending = new Map()
const rl = createInterface({ input: child.stdout })
let stderrBuf = ''

child.stderr.on('data', (d) => { stderrBuf += d.toString() })

rl.on('line', (line) => {
  line = line.trim()
  if (!line) return
  let msg
  try { msg = JSON.parse(line) } catch { return }
  if (msg.id !== undefined && pending.has(msg.id)) {
    pending.get(msg.id)(msg)
    pending.delete(msg.id)
  }
})

function send(method, params) {
  const id = nextId++
  const payload = { jsonrpc: '2.0', id, method }
  if (params !== undefined) payload.params = params
  child.stdin.write(JSON.stringify(payload) + '\n')
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${method} 超时(20s)`)), 20000)
    pending.set(id, (msg) => { clearTimeout(timer); resolve(msg) })
  })
}

function notify(method, params) {
  const payload = { jsonrpc: '2.0', method }
  if (params !== undefined) payload.params = params
  child.stdin.write(JSON.stringify(payload) + '\n')
}

const bail = setTimeout(() => {
  console.error('整体超时，强制退出')
  child.kill()
  process.exit(2)
}, 45000)

try {
  const init = await send('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'dsh-probe', version: '1.0.0' },
  })
  if (init.error) {
    console.error('initialize 报错:', JSON.stringify(init.error))
  } else {
    const si = init.result?.serverInfo ?? {}
    console.log(`✓ 握手成功  server=${si.name ?? '?'} v${si.version ?? '?'}`)
    console.log(`  protocolVersion=${init.result?.protocolVersion}`)
  }
  notify('notifications/initialized', {})

  const tools = await send('tools/list', {})
  if (tools.error) {
    console.error('tools/list 报错:', JSON.stringify(tools.error))
  } else {
    const list = tools.result?.tools ?? []
    console.log(`\n✓ 工具数量: ${list.length}\n`)
    for (const t of list) {
      const desc = (t.description ?? '').split('\n')[0].slice(0, 72)
      console.log(`  ${t.name.padEnd(28)} ${desc}`)
    }
  }
} catch (e) {
  console.error('失败:', e.message)
} finally {
  clearTimeout(bail)
  if (stderrBuf.trim()) {
    console.log('\n--- 服务端 stderr ---')
    console.log(stderrBuf.trim().split('\n').slice(0, 15).join('\n'))
  }
  child.kill()
  process.exit(0)
}
