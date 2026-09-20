import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const bundle = buildSync({
  entryPoints: [fileURLToPath(new URL('../src/components/AlipayReturnActions.jsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false,
  external: ['react', 'react/jsx-runtime', 'lucide-react'],
})
const compiled = { exports: {} }
// Compile the real component in memory; no generated test files or new runtime dependency.
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports)
const ReturnActions = compiled.exports.default
const entry = { flow: 'a'.repeat(64), receipt: 'b'.repeat(64), browser: 'edge_android' }
const render = value => renderToStaticMarkup(createElement(ReturnActions, { origin: 'https://mylingxi.cn', entry: value }))

test('Android Edge completion renders a visible return button and a separate copy fallback', () => {
  const html = render(entry)
  assert.match(html, /返回 Edge 完成登录/)
  assert.match(html, /href="intent:.*package=com\.microsoft\.emmx;end"/)
  assert.match(html, /<button[^>]*>.*复制返回链接/)
  assert.match(html, /无需操作支付宝右上角菜单/)
})

test('unknown browsers still have a working fallback action instead of no buttons', () => {
  const html = render({ ...entry, browser: 'system' })
  assert.match(html, /<button[^>]*class="alipay-handoff__primary"[^>]*>.*复制返回链接/)
  assert.doesNotMatch(html, /href="intent:/)
})

test('incomplete completion data does not expose an unusable login action', () => {
  const html = render({ ...entry, receipt: '' })
  assert.match(html, /返回信息不完整/)
  assert.doesNotMatch(html, /复制返回链接|href="intent:/)
})
