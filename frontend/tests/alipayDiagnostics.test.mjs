import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../public/ui/alipay-diagnostics-v1.js', import.meta.url), 'utf8')
function page(pathname = '/api/auth/oauth/alipay/callback') {
  const window = new EventTarget()
  const document = new EventTarget()
  window.location = { pathname, origin: 'https://mylingxi.cn', search: '?auth_code=DO_NOT_CAPTURE', hash: '#state=DO_NOT_CAPTURE' }
  window.isSecureContext = true
  let now = 55
  const timers = []
  runInNewContext(source, { window, document, navigator: { userAgent: 'AlipayClient/12' }, performance: { now: () => now }, Event, URL,
    setTimeout: (callback, delay) => timers.push({ callback, delay }),
  })
  return { window, document, timers, report: () => window.__fzuAlipayDiagnostic.report(), tick(delay) { now = 55 + delay; timers.find(timer => timer.delay === delay).callback() } }
}

test('normal pages do not observe or create diagnostic timers', () => {
  const normal = page('/')
  assert.equal(normal.window.__fzuAlipayDiagnostic, undefined)
  assert.equal(normal.timers.length, 0)
})

test('observes missing bridge through 15 seconds without invoking authorization', () => {
  const p = page()
  for (const ms of [1000, 3000, 8000, 15000]) p.tick(ms)
  assert.match(p.report(), /已完成 15 秒/)
  assert.match(p.report(), /15.0s 定时观察；接口未出现/)
  assert.doesNotMatch(p.report(), /DO_NOT_CAPTURE|auth_code|state=/)
})

test('records a late bridge even when no ready event arrives', () => {
  const p = page()
  p.tick(8000)
  p.window.AlipayJSBridge = { call() { throw new Error('Diagnostics must not call native APIs') } }
  p.tick(15000)
  assert.match(p.report(), /8.0s 定时观察；接口未出现/)
  assert.match(p.report(), /15.0s 定时观察；接口存在，call 可用/)
  assert.doesNotMatch(p.report(), /收到就绪事件/)
})

test('records early ready events and sanitized native result codes', () => {
  const p = page()
  p.window.AlipayJSBridge = { call() {} }
  p.document.dispatchEvent(new Event('AlipayJSBridgeReady'))
  p.window.__fzuAlipayDiagnostic.mark('native_result', '15')
  p.window.__fzuAlipayDiagnostic.mark('native_result', 'DO_NOT_CAPTURE')
  p.window.__fzuAlipayDiagnostic.mark('DO_NOT_CAPTURE', 123)
  assert.match(p.report(), /收到就绪事件；接口存在，call 可用/)
  assert.match(p.report(), /原生授权回调（数字错误码） \[15\]/)
  assert.doesNotMatch(p.report(), /DO_NOT_CAPTURE/)
})

test('CSP evidence excludes raw URLs, snippets, policy and auth data and is bounded', () => {
  const p = page()
  const event = Object.assign(new Event('securitypolicyviolation'), {
    effectiveDirective: 'script-src-elem', disposition: 'enforce',
    blockedURI: 'https://gw.alipayobjects.com/path?auth_code=DO_NOT_CAPTURE',
    documentURI: 'DO_NOT_CAPTURE', originalPolicy: 'DO_NOT_CAPTURE', sample: 'DO_NOT_CAPTURE',
  })
  for (let i = 0; i < 70; i++) p.document.dispatchEvent(event)
  assert.match(p.report(), /CSP 实际拦截：script-src-elem \/ 支付宝域名资源/)
  assert.match(p.report(), /已省略/)
  assert.doesNotMatch(p.report(), /DO_NOT_CAPTURE|https:|gw\.alipayobjects/)
  assert.ok(p.report().length < 6000)
})
