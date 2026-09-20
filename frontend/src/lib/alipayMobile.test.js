import { test } from 'node:test'
import assert from 'node:assert/strict'
import { alipayInAppUrl, mobileOutsideAlipay } from './alipayMobile.js'

test('mobile browsers open Alipay, while desktop and Alipay keep their current client', () => {
  assert.equal(mobileOutsideAlipay('iPhone Mobile Safari'), true)
  assert.equal(mobileOutsideAlipay('Android Chrome Mobile'), true)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 5), true)
  assert.equal(mobileOutsideAlipay('iPhone AlipayClient/10.0'), false)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 0), false)
})

test('launch preserves the working in-Alipay entry without return-browser credentials', () => {
  const launch = new URL(alipayInAppUrl('https://mylingxi.cn'))
  assert.equal(launch.protocol, 'alipays:')
  assert.equal(launch.searchParams.get('appId'), '20000067')
  const entry = new URL(launch.searchParams.get('url'))
  assert.equal(entry.origin, 'https://mylingxi.cn')
  assert.equal(entry.pathname, '/api/auth/oauth/alipay/callback')
  assert.equal(entry.hash, '#native_consent=1')
  assert.equal(entry.search, '')
  assert.doesNotMatch(launch.href, /receipt|ticket|return_browser|auth_code/)
})
