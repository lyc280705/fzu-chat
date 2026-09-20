import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mobileOutsideAlipay, readMobileEntry } from './alipayMobile.js'

test('mobile outside Alipay uses handoff, desktop and Alipay keep direct authorization', () => {
  assert.equal(mobileOutsideAlipay('iPhone Mobile Safari'), true)
  assert.equal(mobileOutsideAlipay('Android Chrome Mobile'), true)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 5), true)
  assert.equal(mobileOutsideAlipay('iPhone AlipayClient/10.0'), false)
  assert.equal(mobileOutsideAlipay('Macintosh Safari', 0), false)
})
test('launch ticket is read only from fragment and format checked', () => {
  const ticket = 'a'.repeat(64)
  assert.equal(readMobileEntry({ search: '?alipay_mobile=authorize', hash: `#ticket=${ticket}` }).ticket, ticket)
  assert.equal(readMobileEntry({ search: `?alipay_mobile=authorize&ticket=${ticket}`, hash: '' }).ticket, '')
  assert.equal(readMobileEntry({ search: '?alipay_mobile=authorize', hash: '#ticket=bad' }).ticket, '')
  assert.equal(readMobileEntry({ search: '', hash: '' }), null)
})
