import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, LockKeyhole, RefreshCw, Smartphone } from 'lucide-react'
import { mobileRequest, rememberMobileFlow } from '../lib/alipayMobile.js'
import AlipayReturnActions from './AlipayReturnActions.jsx'
import '../alipay-mobile.css'

const terminalLabels = {
  cancelled: '本次授权已取消', failed: '支付宝授权未完成', unavailable: '支付宝服务暂不可用',
  expired: '本次登录已过期', consumed: '本次登录已结束',
}

export function AlipayMobileLogin({ initial, onCancel }) {
  const [snapshot, setSnapshot] = useState(initial)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const flow = initial.flow
  const terminal = Boolean(terminalLabels[snapshot.status])

  useEffect(() => {
    let disposed = false
    let active = false
    let stopped = false
    let timer
    let controller
    const check = async () => {
      if (disposed || active || stopped || document.hidden) return
      active = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 10000)
      try {
        const next = await mobileRequest(`status?flow=${encodeURIComponent(flow)}`, null, controller.signal)
        if (disposed) return
        setSnapshot(next)
        setError('')
        stopped = Boolean(terminalLabels[next.status])
      } catch (err) {
        if (disposed) return
        if (err.status === 403) {
          // A return link can finish in another tab sharing this cookie jar.
          const me = await fetch('/api/auth/me', { credentials: 'same-origin', signal: controller.signal }).catch(() => null)
          if (disposed) return
          if (me?.ok) { rememberMobileFlow(null); window.location.replace('/'); return }
        }
        if ([403, 410].includes(err.status)) {
          stopped = true
          setSnapshot((value) => ({ ...value, status: 'expired' }))
          rememberMobileFlow(null)
        }
        setError(err.name === 'AbortError' ? '网络响应较慢，请稍后重试。' : err.message)
      } finally {
        clearTimeout(timeout)
        active = false
        if (!disposed) timer = setTimeout(check, 2500)
      }
    }
    const resume = () => { clearTimeout(timer); check() }
    window.addEventListener('focus', resume)
    window.addEventListener('pageshow', resume)
    document.addEventListener('visibilitychange', resume)
    check()
    return () => {
      disposed = true
      clearTimeout(timer)
      controller?.abort()
      window.removeEventListener('focus', resume)
      window.removeEventListener('pageshow', resume)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [flow])

  const cancel = async () => {
    setBusy(true)
    try { await mobileRequest('cancel', { flow }) }
    catch (err) {
      if (![403, 410].includes(err.status)) { setError(err.message); setBusy(false); return }
    }
    rememberMobileFlow(null)
    onCancel()
  }
  return <section className="alipay-handoff alipay-handoff--page" aria-label="支付宝手机登录">
    <div className="alipay-handoff__heading"><Smartphone size={18} aria-hidden="true" /><strong>支付宝登录</strong></div>
    <h1>{terminal ? terminalLabels[snapshot.status] : snapshot.status === 'ready' ? '授权已完成' : '正在前往支付宝'}</h1>
    {terminal ? <p>请重新发起或选择其他登录方式。</p> : snapshot.status === 'ready' ? <>
      <p>请点击支付宝授权完成页的返回按钮；如果被拦截，可复制返回链接，在原浏览器地址栏粘贴打开。</p>
      <p className="alipay-handoff__hint">为保护账号，单纯切换应用不会领取授权结果。</p>
    </> : <>
      <p>在支付宝确认授权后，使用返回按钮即可完成登录，无需输入确认码。</p>
      {snapshot.launch_url && <a className="alipay-handoff__primary" href={snapshot.launch_url}>打开支付宝<ArrowRight size={16} aria-hidden="true" /></a>}
      <p className="alipay-handoff__hint">没有自动打开？可点上方按钮重试。未安装支付宝，或在微信、QQ 内打开时，可换用其他登录方式。</p>
    </>}
    {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
    <button type="button" className="alipay-handoff__cancel" disabled={busy} onClick={cancel}>{busy ? '处理中…' : '取消并返回登录'}</button>
  </section>
}

export function AlipayHandoffPage({ entry }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const requestRef = useRef(null)
  const [attempt, setAttempt] = useState(0)
  const inAlipay = /AlipayClient|AliApp\(AP\//i.test(navigator.userAgent)
  const completing = entry.mode === 'complete'
  const validReceipt = Boolean(entry.flow && entry.receipt)
  const returning = completing && inAlipay && validReceipt

  useEffect(() => {
    // Keep the completion fragment inside Alipay for explicit retry/copy only.
    // It is short-lived and useless without the original owner cookie.
    // The receiving browser removes it before API calls and never persists it.
    if (!returning) window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    if (returning) {
      setBusy(false)
      return
    }
    const canBegin = entry.mode === 'authorize' && inAlipay && entry.ticket
    const canClaim = completing && !inAlipay && validReceipt
    if (!canBegin && !canClaim) { setBusy(false); return }
    // Share one-shot requests across React StrictMode's effect replay.
    if (!requestRef.current) requestRef.current = canBegin
      ? mobileRequest('begin', { ticket: entry.ticket })
      : mobileRequest('claim', { flow: entry.flow, receipt: entry.receipt })
    let disposed = false
    requestRef.current.then(result => {
      if (disposed) return
      if (canBegin) {
        const url = new URL(result.authorization_url)
        if (url.protocol !== 'https:' || url.hostname !== 'openauth.alipay.com') throw new Error('授权地址无效，请重新发起。')
        window.location.replace(url.href)
      } else {
        rememberMobileFlow(null)
        window.location.replace('/')
      }
    }).catch(err => {
      if (!disposed) { setError(err.message); setBusy(false) }
    })
    return () => { disposed = true }
  }, [attempt, completing, entry, inAlipay, returning, validReceipt])

  const retry = () => { requestRef.current = null; setError(''); setBusy(true); setAttempt(value => value + 1) }
  return <main className="alipay-handoff-page">
    <section className="alipay-handoff alipay-handoff--page">
      <div className="alipay-handoff__brand"><img src="/assets/FZU.png" alt="" /><span>福大灵犀</span></div>
      <div className="alipay-handoff__symbol">{returning ? <Check size={28} /> : busy ? <RefreshCw className="alipay-handoff__spinner" size={24} /> : <Smartphone size={26} />}</div>
      {returning ? <>
        <h1>还差一步，返回浏览器</h1>
        <AlipayReturnActions origin={window.location.origin} entry={entry} />
      </> : completing ? <>
        <h1>{busy ? '正在完成登录' : '暂时无法完成登录'}</h1>
        <p>{busy ? '正在安全接收授权结果，即将进入聊天。' : '请使用原浏览器及相同浏览模式打开支付宝的返回链接。不要打开他人转发的登录链接。'}</p>
        {!busy && validReceipt && <button type="button" className="alipay-handoff__primary" onClick={retry}>重试登录<ArrowRight size={16} /></button>}
      </> : entry.mode === 'authorize' && inAlipay && entry.ticket ? <>
        <h1>{busy ? '正在前往支付宝授权' : '暂时无法发起授权'}</h1>
        <p>仅用于登录你刚才打开的福大灵犀。</p>
        {!busy && <button type="button" className="alipay-handoff__primary" onClick={retry}>重新尝试<ArrowRight size={16} /></button>}
      </> : <>
        <h1>{terminalLabels[entry.status] || '请重新发起登录'}</h1>
        <p>请返回原浏览器重试，或选择其他登录方式。</p>
      </>}
      {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
      <p className="alipay-handoff__footer"><LockKeyhole size={13} aria-hidden="true" />仅用于账号登录，不涉及付款</p>
    </section>
  </main>
}
