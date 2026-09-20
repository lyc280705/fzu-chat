export function supportsPasskeys() {
  return Boolean(globalThis.isSecureContext && globalThis.PublicKeyCredential && globalThis.navigator?.credentials?.create && globalThis.navigator?.credentials?.get)
}

export function passkeyErrorMessage(error, register = false) {
  const name = error?.name || ''
  if (name === 'NotReadableError' || /credential manager/i.test(error?.message || '')) {
    return '暂时无法连接手机的通行密钥服务。请检查系统中的密码／通行密钥提供方是否已启用；若使用 Google 密码管理工具，请确认 Google Play 服务可用后重试。也可以返回选择其他登录方式。'
  }
  if (name === 'NotAllowedError') return register
    ? '通行密钥创建已取消或超时。请确认设备已设置锁屏密码，并在系统提示中完成确认后重试。'
    : '操作已取消、超时或未找到可用的通行密钥。首次使用请选择“创建通行密钥并进入”。'
  if (name === 'InvalidStateError') return '此设备已保存该身份的通行密钥，请直接登录。'
  if (name === 'SecurityError') return '此页面无法安全使用通行密钥，请从 https://mylingxi.cn 重新打开后尝试。'
  if (name === 'NotSupportedError') return '当前浏览器或密钥管理工具暂不支持此操作，请使用其他支持通行密钥的浏览器或登录方式。'
  if (name === 'AbortError') return '本次通行密钥操作已中断，请重新尝试。'
  if (/[\u3400-\u9fff]/.test(error?.message || '')) return error.message
  return '暂时无法完成通行密钥操作，请检查网络和系统密钥服务，或选择其他登录方式。'
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
    throw new Error(passkeyErrorMessage(error, register))
  }
}
