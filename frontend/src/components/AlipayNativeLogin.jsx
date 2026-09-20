import { useEffect, useRef, useState } from 'react'
import { LockKeyhole, RefreshCw } from 'lucide-react'
import { nativeRequest } from '../lib/alipayMobile.js'
import { AlipayDiagnostics } from './AlipayDiagnostics.jsx'
import '../alipay-mobile.css'

function diagnose(stage, code) {
  // Diagnostics must never interrupt authentication; pass only fixed stages/codes.
  try { window.__fzuAlipayDiagnostic?.mark(stage, code) } catch { /* Passive only. */ }
}

function nativeAuthorization(appId) {
  return new Promise((resolve, reject) => {
    let started = false
    diagnose('bridge_wait')
    const readyTimer = setTimeout(() => {
      diagnose('bridge_timeout')
      finish(new Error('支付宝原生授权暂不可用，请点击下方按钮重试或使用网页授权。'))
    }, 8000)
    let authorizationTimer
    function finish(error, code) {
      clearTimeout(readyTimer)
      clearTimeout(authorizationTimer)
      document.removeEventListener('AlipayJSBridgeReady', ready)
      if (error) reject(error)
      else resolve(code)
    }
    function ready() {
      if (started || !window.AlipayJSBridge?.call) return
      started = true
      clearTimeout(readyTimer)
      authorizationTimer = setTimeout(() => {
        diagnose('native_timeout')
        finish(new Error('授权等待超时，请重新尝试。'))
      }, 120000)
      try {
        diagnose('native_start')
        // Official alipayjsapi maps scopes -> scopeNicks and authcode -> authCode.
        window.AlipayJSBridge.call('getAuthCode', { appId, scopeNicks: ['auth_user'], showErrorTip: false }, result => {
          const code = result?.authCode || result?.authcode
          diagnose('native_result', result?.error)
          if (code) diagnose('native_code')
          if (code && (!result.error || Number(result.error) === 0)) { finish(null, code); return }
          const message = Number(result?.error) === 11 ? '你已取消支付宝授权。'
            : Number(result?.error) === 15 ? '支付宝暂未允许当前页面使用原生授权，可选择网页授权继续。'
              : '支付宝原生授权暂未完成，请重试或选择网页授权。'
          finish(new Error(message))
        })
      } catch {
        diagnose('native_throw')
        finish(new Error('支付宝原生授权暂不可用，请选择网页授权继续。'))
      }
    }
    document.addEventListener('AlipayJSBridgeReady', ready)
    ready()
  })
}

export function AlipayNativeLogin() {
  const accepted = useRef(window.location.hash === '#native_consent=1')
  const requestRef = useRef(null)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  useEffect(() => {
    window.history.replaceState(null, '', window.location.pathname)
    let disposed = false
    if (!requestRef.current) requestRef.current = (async () => {
      if (!accepted.current) throw new Error('请从登录页同意协议后重新发起支付宝登录。')
      if (!/AlipayClient|AliApp\(AP\//i.test(navigator.userAgent)) throw new Error('请在支付宝内继续，或返回首页选择其他登录方式。')
      diagnose('prepare_start')
      const options = await nativeRequest('prepare', { accepted_legal: true }).catch(err => { diagnose('prepare_error', err.status); throw err })
      diagnose('prepare_ok')
      const authCode = await nativeAuthorization(options.app_id)
      diagnose('complete_start')
      await nativeRequest('complete', { auth_code: authCode, state: options.state }).catch(err => { diagnose('complete_error', err.status); throw err })
      diagnose('complete_ok')
    })()
    requestRef.current.then(() => { if (!disposed) window.location.replace('/') })
      .catch(err => { if (!disposed) { setError(err.message); setBusy(false) } })
    return () => { disposed = true }
  }, [attempt])
  return <main className="alipay-handoff-page"><section className="alipay-handoff alipay-handoff--page">
    <div className="alipay-handoff__brand"><img src="/assets/FZU.png" alt="" /><span>福大灵犀</span></div>
    {busy && <RefreshCw className="alipay-handoff__spinner" size={24} aria-hidden="true" />}
    <h1>{busy ? '正在支付宝内授权' : '继续支付宝登录'}</h1>
    <p>授权完成后直接进入聊天，无需离开当前页面或返回浏览器。</p>
    {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
    {!busy && accepted.current && <>
      <button type="button" className="alipay-handoff__primary" onClick={() => { requestRef.current = null; setBusy(true); setError(''); setAttempt(value => value + 1) }}>重试原生授权</button>
      <a className="alipay-handoff__cancel" href="/api/auth/oauth/alipay/start?accepted_legal=true">改用网页授权（可能再次提示继续访问）</a>
    </>}
    {!busy && <a className="alipay-handoff__cancel" href="/">返回登录页</a>}
    {error && <AlipayDiagnostics />}
    <p className="alipay-handoff__footer"><LockKeyhole size={13} aria-hidden="true" />仅用于账号登录，不涉及付款</p>
  </section></main>
}
