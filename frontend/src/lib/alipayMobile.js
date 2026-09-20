export const MOBILE_FLOW_STORAGE = 'fzu_alipay_mobile_flow'
export const mobileOutsideAlipay = (ua, touchPoints = 0) => !/AlipayClient|AliApp\(AP\//i.test(ua)
  && (/Android|iPhone|iPad|iPod|Mobile/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1))

export function returnBrowser(ua, touchPoints = 0) {
  const ios = /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1)
  if (ios && /CriOS\//i.test(ua)) return 'chrome_ios'
  if (ios && /Version\/.*Safari\//i.test(ua) && !/FxiOS|EdgiOS|OPiOS/i.test(ua)) return 'safari'
  if (/Android.*Chrome\//i.test(ua) && !/EdgA|OPR|SamsungBrowser|HuaweiBrowser|; wv\)/i.test(ua)) return 'chrome_android'
  return 'system'
}

// Fixed browser schemes only; never accept a return URL, package or scheme from input.
// Safari's scheme and native app switching are best-effort, not an OS guarantee.
export function browserReturnUrl(origin, entry) {
  const base = new URL(origin)
  if (base.protocol !== 'https:' || !/^[a-f0-9]{64}$/.test(entry.flow) || !/^[a-f0-9]{64}$/.test(entry.receipt)) return ''
  const url = `${base.origin}/?alipay_mobile=complete#${new URLSearchParams({ flow: entry.flow, receipt: entry.receipt, browser: entry.browser })}`
  if (entry.browser === 'safari') return url.replace(/^https:/, 'x-safari-https:')
  if (entry.browser === 'chrome_ios') return url.replace(/^https:/, 'googlechromes:')
  // HTTPS-only BROWSABLE intent; the target package is fixed.
  if (entry.browser === 'chrome_android') return `intent:${url.slice(6)}#Intent;scheme=https;package=com.android.chrome;end`
  return ''
}

export function savedMobileFlow() {
  try {
    const flow = window.sessionStorage.getItem(MOBILE_FLOW_STORAGE) || ''
    return /^[a-f0-9]{64}$/.test(flow) ? { flow, status: 'waiting' } : null
  } catch { return null }
}

export function rememberMobileFlow(flow) {
  // Only the non-secret task ID persists in this tab. The owner secret stays HttpOnly.
  try {
    if (flow) window.sessionStorage.setItem(MOBILE_FLOW_STORAGE, flow)
    else window.sessionStorage.removeItem(MOBILE_FLOW_STORAGE)
  } catch { /* Storage can be unavailable in private browsing. */ }
}

export async function mobileRequest(action, body, signal) {
  const controller = signal ? null : new AbortController()
  const timer = controller ? setTimeout(() => controller.abort(), 12000) : null
  try {
    const response = await fetch(`/api/auth/oauth/alipay/mobile/${action}`, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin', signal: signal || controller.signal,
      headers: { 'X-FZU-Alipay-Mobile': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : '登录状态暂时无法获取，请重试。')
      error.status = response.status
      throw error
    }
    return data
  } catch (err) {
    if (err.name === 'AbortError' && controller) throw new Error('网络响应较慢，请检查连接后重试。')
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export function readMobileEntry(location) {
  const params = new URLSearchParams(location.search)
  const mode = params.get('alipay_mobile')
  if (!['authorize', 'result', 'complete'].includes(mode)) return null
  const fragment = new URLSearchParams(location.hash.slice(1))
  const secret = (name) => /^[a-f0-9]{64}$/.test(fragment.get(name) || '') ? fragment.get(name) : ''
  const browser = fragment.get('browser') || 'system'
  return { mode, ticket: secret('ticket'), flow: secret('flow'), receipt: secret('receipt'),
    browser: ['safari', 'chrome_ios', 'chrome_android'].includes(browser) ? browser : 'system', status: params.get('status') || '' }
}
