// 端到端实测：通过 MCP 调用 Lightroom，验证插件链路。
// 用法: node scripts/lr-test.mjs <工具名> [JSON参数]
//
// MCP server 路径默认从仓库上级的 node_modules 里找；也可以用环境变量指定：
//   $env:LIGHTROOM_MCP_SERVER = "C:\path\to\lightroom-mcp\dist\index.js"
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

const SERVER = process.env.LIGHTROOM_MCP_SERVER
  ?? fileURLToPath(new URL('../node_modules/@pired/lightroom-mcp/dist/index.js', import.meta.url))
const toolName = process.argv[2] ?? 'get_photo_status'
// 默认参数只是个示例，id 换成你自己目录里真实的照片 id
const toolArgs = process.argv[3] ? JSON.parse(process.argv[3]) : { photo_ids: [12345] }

const child = spawn(process.execPath, [SERVER], { stdio: ['pipe', 'pipe', 'pipe'] })
let nextId = 1
const pending = new Map()
let stderrBuf = ''

createInterface({ input: child.stdout }).on('line', (line) => {
  line = line.trim()
  if (!line) return
  let msg
  try { msg = JSON.parse(line) } catch { return }
  if (msg.id !== undefined && pending.has(msg.id)) {
    pending.get(msg.id)(msg)
    pending.delete(msg.id)
  }
})
child.stderr.on('data', (d) => { stderrBuf += d.toString() })

function send(method, params) {
  const id = nextId++
  const payload = { jsonrpc: '2.0', id, method }
  if (params !== undefined) payload.params = params
  child.stdin.write(JSON.stringify(payload) + '\n')
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`${method} 超时(60s)`)), 60000)
    pending.set(id, (m) => { clearTimeout(t); resolve(m) })
  })
}
const notify = (method, params) => {
  const p = { jsonrpc: '2.0', method }
  if (params !== undefined) p.params = params
  child.stdin.write(JSON.stringify(p) + '\n')
}

console.log(`调用工具: ${toolName}`)
console.log(`参数: ${JSON.stringify(toolArgs)}\n`)

try {
  const init = await send('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'lr-test', version: '1.0.0' },
  })
  console.log(`✓ 握手: ${init.result?.serverInfo?.name} v${init.result?.serverInfo?.version}`)
  notify('notifications/initialized', {})

  const res = await send('tools/call', { name: toolName, arguments: toolArgs })
  if (res.error) {
    console.log('\n✗ 协议层错误:', JSON.stringify(res.error))
  } else {
    const content = res.result?.content ?? []
    console.log(`\n${res.result?.isError ? '✗ 工具报错' : '✓ 工具成功返回'}，内容块 ${content.length} 个:\n`)
    for (const c of content) {
      if (c.type === 'text') console.log(c.text)
      else console.log(`[${c.type}] ${JSON.stringify(c).slice(0, 200)}`)
    }
  }
} catch (e) {
  console.log('\n✗ 失败:', e.message)
} finally {
  if (stderrBuf.trim()) {
    console.log('\n--- 服务端 stderr ---')
    console.log(stderrBuf.trim().split('\n').slice(0, 12).join('\n'))
  }
  child.kill()
  process.exit(0)
}
