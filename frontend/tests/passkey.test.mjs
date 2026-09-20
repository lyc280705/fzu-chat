import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { credentialJSON, encode, decode, runPasskeyCeremony, supportsPasskeys } from '../src/lib/passkeys.js'
import { alipayInAppUrl, mobileOutsideAlipay } from '../src/lib/alipayMobile.js'

const bytes = new Uint8Array([0, 255, 17, 250])
const credential = { id: encode(bytes), rawId: bytes.buffer, type: 'public-key',
  response: { clientDataJSON: bytes.buffer, attestationObject: bytes.buffer, getTransports: () => ['internal'] },
  getClientExtensionResults: () => ({}) }

function globals(t, values) {
  for (const [key, value] of Object.entries(values)) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key)
    Object.defineProperty(globalThis, key, { value, configurable: true })
    t.after(() => { if (previous) Object.defineProperty(globalThis, key, previous); else delete globalThis[key] })
  }
}

test('binary WebAuthn data survives JSON transport, including large authenticator data', () => {
  assert.deepEqual(decode(encode(bytes)), bytes)
  const large = new Uint8Array(200000).fill(255)
  assert.deepEqual(decode(encode(large)), large)
  const data = credentialJSON(credential)
  assert.deepEqual(decode(data.response.clientDataJSON), bytes)
  assert.deepEqual(data.response.transports, ['internal'])
  assert.equal(data.rawId, credential.id)
})

test('standalone create and discoverable login need no username or pre-existing session', async t => {
  const calls = []
  globals(t, { isSecureContext: true, PublicKeyCredential: class {}, navigator: { credentials: {
    create: async ({ publicKey }) => {
      assert.deepEqual(publicKey.challenge, bytes)
      assert.deepEqual(publicKey.user.id, bytes)
      assert.deepEqual(publicKey.excludeCredentials[0].id, bytes)
      return credential
    },
    get: async ({ publicKey }) => {
      assert.deepEqual(publicKey.challenge, bytes)
      assert.deepEqual(publicKey.allowCredentials, [])
      return { ...credential, response: { clientDataJSON: bytes.buffer, authenticatorData: bytes.buffer, signature: bytes.buffer, userHandle: bytes.buffer } }
    },
  } }, fetch: async (url, init) => {
    calls.push({ url, init })
    const options = { challenge: encode(bytes), userVerification: 'required',
      ...(url.includes('/register/') ? { user: { id: encode(bytes), name: 'random-identity' }, excludeCredentials: [{ id: encode(bytes), type: 'public-key' }] } : { allowCredentials: [] }) }
    return { ok: true, json: async () => url.endsWith('/options') ? options : { ok: true } }
  } })
  await runPasskeyCeremony(true)
  await runPasskeyCeremony(false)
  assert.equal(calls.length, 4)
  for (const { init } of calls) {
    assert.equal(init.credentials, 'same-origin')
    assert.equal(init.headers['X-FZU-Passkey'], '1')
  }
  assert.deepEqual(JSON.parse(calls[0].init.body), { accepted_legal: true, enroll: false })
  assert.deepEqual(JSON.parse(calls[2].init.body), { accepted_legal: true, enroll: false })
  assert.equal(JSON.parse(calls[3].init.body).credential.response.userHandle, encode(bytes))
})

test('cancellation and unsupported browsers produce a useful message', async t => {
  globals(t, { isSecureContext: true, PublicKeyCredential: class {}, navigator: { credentials: {
    create: async () => {}, get: async () => { throw new DOMException('cancelled', 'NotAllowedError') },
  } }, fetch: async () => ({ ok: true, json: async () => ({ challenge: encode(bytes) }) }) })
  await assert.rejects(runPasskeyCeremony(), /操作已取消/)
  Object.defineProperty(globalThis, 'isSecureContext', { value: false, configurable: true })
  assert.equal(supportsPasskeys(), false)
  await assert.rejects(runPasskeyCeremony(), /当前浏览器不支持/)
})

test('Alipay launch keeps authorization and chat inside its webview, with no browser-return flow', () => {
  const launch = new URL(alipayInAppUrl('https://mylingxi.cn'))
  assert.equal(launch.protocol, 'alipays:')
  assert.equal(launch.searchParams.get('appId'), '20000067')
  assert.equal(launch.searchParams.get('url'), 'https://mylingxi.cn/api/auth/oauth/alipay/start?accepted_legal=true')
  assert.doesNotMatch(launch.href, /receipt|flow|complete|intent:|return_browser/)
  assert.equal(mobileOutsideAlipay('Android EdgA/1'), true)
  assert.equal(mobileOutsideAlipay('Android AlipayClient/10'), false)
})

test('real passkey login panel exposes both independent entry paths and recovery warning', t => {
  globals(t, { isSecureContext: true, PublicKeyCredential: class {}, navigator: { credentials: { create() {}, get() {} } } })
  const bundle = buildSync({
    entryPoints: [fileURLToPath(new URL('../src/components/PasskeyPanel.jsx', import.meta.url))],
    bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false,
    loader: { '.css': 'empty' }, external: ['react', 'react/jsx-runtime', 'lucide-react'],
  })
  const compiled = { exports: {} }
  new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports)
  const html = renderToStaticMarkup(createElement(compiled.exports.PasskeyLogin, { acceptedLegal: true }))
  assert.match(html, /使用已有通行密钥登录/)
  assert.match(html, /首次使用：创建通行密钥并进入/)
  assert.match(html, /全部丢失后无法找回/)
  assert.doesNotMatch(html, /<input|disabled=/)
})
