export function supportsPasskeys() {
  return Boolean(globalThis.isSecureContext && globalThis.PublicKeyCredential && globalThis.navigator?.credentials?.create && globalThis.navigator?.credentials?.get)
}

export const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
export const encode = value => btoa(Array.from(new Uint8Array(value), n => String.fromCharCode(n)).join('')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

export function credentialJSON(credential) {
  const response = {}
  for (const key of ['clientDataJSON', 'attestationObject', 'authenticatorData', 'signature', 'userHandle']) {
    if (credential.response[key]) response[key] = encode(credential.response[key])
  }
  if (credential.response.getTransports) response.transports = credential.response.getTransports()
  return { id: credential.id, rawId: encode(credential.rawId), type: credential.type, response,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults?.() || {} }
}

export async function passkeyRequest(action, body, method = body ? 'POST' : 'GET') {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(`/api/auth/passkey/${action}`, { method, credentials: 'same-origin',
      headers: { 'X-FZU-Passkey': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}), signal: controller.signal })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请重试。')
    return data
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('网络响应超时，请重试。')
    throw error
  } finally { clearTimeout(timer) }
}

export async function runPasskeyCeremony(register = false, enroll = false) {
  if (!supportsPasskeys()) throw new Error('当前浏览器不支持通行密钥，请使用最新版 Edge、Chrome 或 Safari；内置浏览器可能不支持。')
  const kind = register ? 'register' : 'login'
  const options = await passkeyRequest(`${kind}/options`, { accepted_legal: true, enroll })
  const publicKey = { ...options, challenge: decode(options.challenge) }
  if (options.user) publicKey.user = { ...options.user, id: decode(options.user.id) }
  for (const field of ['allowCredentials', 'excludeCredentials']) {
    if (options[field]) publicKey[field] = options[field].map(item => ({ ...item, id: decode(item.id) }))
  }
  try {
    const credential = await navigator.credentials[register ? 'create' : 'get']({ publicKey })
    if (!credential) throw new Error('未取得通行密钥，请重试。')
    await passkeyRequest(`${kind}/verify`, { credential: credentialJSON(credential) })
  } catch (error) {
    if (error.name === 'NotAllowedError') throw new Error('操作已取消、超时或设备中没有可用的通行密钥。首次使用请点击“创建通行密钥并进入”。')
    if (error.name === 'InvalidStateError') throw new Error('此设备已保存该身份的通行密钥，请直接登录。')
    if (['NotSupportedError', 'SecurityError'].includes(error.name)) throw new Error('当前浏览器或设备无法使用此通行密钥，请在支持的浏览器中重试。')
    throw error
  }
}
