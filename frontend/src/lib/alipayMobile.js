export const MOBILE_FLOW_STORAGE = 'fzu_alipay_mobile_flow'
export const mobileOutsideAlipay = (ua, touchPoints = 0) => !/AlipayClient|AliApp\(AP\//i.test(ua)
  && (/Android|iPhone|iPad|iPod|Mobile/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1))

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
  if (!['authorize', 'result'].includes(mode)) return null
  const ticket = new URLSearchParams(location.hash.slice(1)).get('ticket') || ''
  return { mode, ticket: /^[a-f0-9]{64}$/.test(ticket) ? ticket : '', status: params.get('status') || '' }
}
