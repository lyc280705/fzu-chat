import { test } from 'node:test'
import assert from 'node:assert/strict'
import { browserReturnUrl, completionUrl, mobileOutsideAlipay, readMobileEntry, returnBrowser } from './alipayMobile.js'

test('mobile outside Alipay uses handoff, desktop and Alipay keep direct authorization', () => {
  assert.equal(mobileOutsideAlipay('iPhone Mobile Safari'), true)
  assert.equal(mobileOutsideAlipay('Android Chrome Mobile'), true)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 5), true)
  assert.equal(mobileOutsideAlipay('iPhone AlipayClient/10.0'), false)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 0), false)
})

test('return browser hint only selects known browsers', () => {
  assert.equal(returnBrowser('iPhone Version/18.0 Mobile Safari/604.1'), 'safari')
  assert.equal(returnBrowser('Macintosh Version/18.0 Safari/604.1', 5), 'safari')
  assert.equal(returnBrowser('iPhone CriOS/140 Mobile Safari/604.1'), 'chrome_ios')
  assert.equal(returnBrowser('Android Chrome/140 Mobile Safari/537.36'), 'chrome_android')
  assert.equal(returnBrowser('Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36 EdgA/140.0'), 'edge_android')
  assert.equal(returnBrowser('Mozilla/5.0 (Linux; Android 16) Chrome/140.0 Safari/537.36 Edg/140.0'), 'edge_android')
  assert.equal(returnBrowser('Android Chrome/140 SamsungBrowser/20 Mobile'), 'system')
  assert.equal(returnBrowser('Android; wv) Chrome/140 Mobile'), 'system')
  assert.equal(returnBrowser('iPhone FxiOS/140 Mobile Safari/604.1'), 'system')
})

test('completion reads receipt only from fragment and rejects arbitrary browser targets', () => {
  const flow = 'a'.repeat(64), receipt = 'b'.repeat(64)
  const entry = readMobileEntry({ search: '?alipay_mobile=complete', hash: `#flow=${flow}&receipt=${receipt}&browser=safari` })
  assert.equal(entry.receipt, receipt)
  assert.equal(entry.flow, flow)
  assert.equal(readMobileEntry({ search: `?alipay_mobile=complete&flow=${flow}&receipt=${receipt}`, hash: '' }).receipt, '')
  assert.equal(readMobileEntry({ search: '?alipay_mobile=complete', hash: '#browser=javascript:alert(1)' }).browser, 'system')
  const native = browserReturnUrl('https://mylingxi.cn', entry)
  assert.equal(native, `x-safari-https://mylingxi.cn/?alipay_mobile=complete#flow=${flow}&receipt=${receipt}&browser=safari`)
  assert.equal(new URL(native).search.includes(receipt), false)
  assert.equal(browserReturnUrl('https://mylingxi.cn', { ...entry, browser: 'chrome_ios' }).startsWith('googlechromes://mylingxi.cn/'), true)
  const android = browserReturnUrl('https://mylingxi.cn', { ...entry, browser: 'chrome_android' })
  assert.equal(android.endsWith('#Intent;scheme=https;package=com.android.chrome;end'), true)
  assert.equal(android.includes(`receipt=${receipt}`), true)
  const edge = browserReturnUrl('https://mylingxi.cn', { ...entry, browser: 'edge_android' })
  assert.equal(edge.endsWith('#Intent;scheme=https;package=com.microsoft.emmx;end'), true)
  // Android parses the last #Intent separator; the preceding fragment must survive.
  const recovered = new URL('https:' + edge.slice(7, edge.lastIndexOf('#Intent;')))
  assert.equal(new URLSearchParams(recovered.hash.slice(1)).get('receipt'), receipt)
  assert.equal(new URLSearchParams(recovered.hash.slice(1)).get('browser'), 'edge_android')
  assert.equal(recovered.search, '?alipay_mobile=complete')
  assert.equal(readMobileEntry(recovered).browser, 'edge_android')
  assert.equal(completionUrl('https://mylingxi.cn', { ...entry, browser: 'unknown' }).includes('browser=system'), true)
  assert.equal(browserReturnUrl('https://mylingxi.cn', { ...entry, browser: 'evil' }), '')
  assert.equal(browserReturnUrl('http://mylingxi.cn', entry), '')
  assert.equal(browserReturnUrl('https://mylingxi.cn', { ...entry, receipt: 'bad' }), '')
})
test('launch ticket is read only from fragment and format checked', () => {
  const ticket = 'a'.repeat(64)
  assert.equal(readMobileEntry({ search: '?alipay_mobile=authorize', hash: `#ticket=${ticket}` }).ticket, ticket)
  assert.equal(readMobileEntry({ search: `?alipay_mobile=authorize&ticket=${ticket}`, hash: '' }).ticket, '')
  assert.equal(readMobileEntry({ search: '?alipay_mobile=authorize', hash: '#ticket=bad' }).ticket, '')
  assert.equal(readMobileEntry({ search: '', hash: '' }), null)
})
