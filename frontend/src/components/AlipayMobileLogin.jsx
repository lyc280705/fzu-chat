import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, LockKeyhole, RefreshCw, Smartphone } from 'lucide-react'
import { mobileRequest, rememberMobileFlow } from '../lib/alipayMobile.js'
import '../alipay-mobile.css'

const terminalLabels = {
  cancelled: '本次授权已取消', failed: '支付宝授权未完成', unavailable: '支付宝服务暂不可用',
  expired: '本次登录已过期', consumed: '本次登录已结束',
}

export function AlipayMobileLogin({ initial, onCancel }) {
  const [snapshot, setSnapshot] = useState(initial)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const checkRef = useRef(null)
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
      setChecking(true)
      try {
        const next = await mobileRequest(`status?flow=${encodeURIComponent(flow)}`, null, controller.signal)
        if (disposed) return
        setSnapshot(next)
        setError('')
        stopped = Boolean(terminalLabels[next.status]) || next.status === 'ready'
      } catch (err) {
        if (disposed) return
        if ([403, 410].includes(err.status)) {
          stopped = true
          setSnapshot((value) => ({ ...value, status: 'expired' }))
          rememberMobileFlow(null)
        }
        setError(err.name === 'AbortError' ? '网络响应较慢，请稍后重新检查。' : err.message)
      } finally {
        clearTimeout(timeout)
        active = false
        if (!disposed) {
          setChecking(false)
          timer = setTimeout(check, 2500)
        }
      }
    }
    const resume = () => { clearTimeout(timer); check() }
    checkRef.current = resume
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

  const finish = async () => {
    setBusy(true)
    setError('')
    try {
      await mobileRequest('claim', { flow })
      rememberMobileFlow(null)
      window.location.replace('/')
    } catch (err) { setError(err.message); setBusy(false) }
  }
  const cancel = async () => {
    setBusy(true)
    try {
      await mobileRequest('cancel', { flow })
    } catch (err) {
      if (![403, 410].includes(err.status)) { setError(err.message); setBusy(false); return }
    }
    rememberMobileFlow(null)
    onCancel()
  }
  return (
    <section className="alipay-handoff" aria-label="支付宝手机登录">
      <div className="alipay-handoff__heading"><Smartphone size={18} aria-hidden="true" /><strong>支付宝登录</strong></div>
      {snapshot.status === 'ready' ? <>
        <p className="alipay-handoff__success"><Check size={16} aria-hidden="true" />授权已完成</p>
        <p>确认使用 <strong>{snapshot.display_name || '支付宝账号'}</strong> 登录当前浏览器。</p>
        <button type="button" className="alipay-handoff__primary" onClick={finish} disabled={busy}>继续登录<ArrowRight size={16} /></button>
      </> : terminal ? <p role="status">{terminalLabels[snapshot.status]}，请重新发起或选择其他登录方式。</p> : <>
        <p>记住确认码，在支付宝内输入。仅为你自己刚刚发起的登录授权。</p>
        <div className="alipay-handoff__code" aria-label={`登录确认码 ${snapshot.verification_code || '正在获取'}`}>{snapshot.verification_code || '······'}</div>
        {snapshot.launch_url && <a className="alipay-handoff__primary" href={snapshot.launch_url}>打开支付宝授权<ArrowRight size={16} aria-hidden="true" /></a>}
        <p className="alipay-handoff__hint">确认码 5 分钟内有效。授权后请手动返回此浏览器，本页会检查结果；不保证自动跳回。</p>
        <p className="alipay-handoff__hint">未安装支付宝或无法唤起？可取消并换用其他登录方式。微信、QQ 内请先用系统浏览器打开本站。</p>
        <button type="button" className="alipay-handoff__secondary" onClick={() => checkRef.current?.()} disabled={checking || busy}><RefreshCw size={14} aria-hidden="true" />{checking ? '正在检查…' : '已完成授权，检查结果'}</button>
      </>}
      {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
      <button type="button" className="alipay-handoff__cancel" disabled={busy} onClick={cancel}>{busy ? '处理中…' : '取消并返回登录'}</button>
    </section>
  )
}

export function AlipayHandoffPage({ entry }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const inAlipay = /AlipayClient|AliApp\(AP\//i.test(navigator.userAgent)
  const succeeded = entry.mode === 'result' && entry.status === 'success'
  useEffect(() => {
    // Launch ticket is fragment-only and removed from browser history immediately.
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }, [])
  const begin = async (event) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const result = await mobileRequest('begin', { ticket: entry.ticket, verification_code: code })
      const url = new URL(result.authorization_url)
      if (url.protocol !== 'https:' || url.hostname !== 'openauth.alipay.com') throw new Error('授权地址无效，请重新发起。')
      window.location.replace(url.href)
    } catch (err) { setError(err.message); setBusy(false) }
  }
  return <main className="alipay-handoff-page">
    <section className="alipay-handoff alipay-handoff--page">
      <div className="alipay-handoff__brand"><img src="/assets/FZU.png" alt="" /><span>福大灵犀</span></div>
      {entry.mode === 'result' ? <>
        <div className="alipay-handoff__symbol">{succeeded ? <Check size={28} /> : <RefreshCw size={28} />}</div>
        <h1>{succeeded ? '支付宝授权已完成' : '本次授权未完成'}</h1>
        <p>{succeeded ? '请手动返回刚才的 Safari、Chrome 或系统浏览器，确认账号并完成登录。' : '请返回最初发起登录的浏览器，重新发起或选择其他登录方式。'}</p>
        <p className="alipay-handoff__hint">此页面不会登录你的账号，也不会把登录凭证放进链接。</p>
      </> : !inAlipay || !entry.ticket ? <>
        <h1>请从原浏览器重新发起</h1>
        <p>在福大灵犀登录页点击“支付宝”，再使用“打开支付宝授权”按钮。请勿复制或转发授权链接。</p>
      </> : <>
        <h1>确认是你发起的登录</h1>
        <p>本次授权将用于登录另一个浏览器。请输入你刚才在原浏览器看到的六位确认码；不要为他人发来的链接授权。</p>
        <form onSubmit={begin}>
          <label htmlFor="alipay-confirmation-code">原浏览器的确认码</label>
          <input id="alipay-confirmation-code" className="alipay-handoff__input" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="off" required placeholder="输入六位数字" disabled={busy} />
          <button type="submit" className="alipay-handoff__primary" disabled={busy || code.length !== 6}>{busy ? '正在前往支付宝…' : '确认并前往授权'}<ArrowRight size={16} /></button>
        </form>
      </>}
      {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
      <p className="alipay-handoff__footer"><LockKeyhole size={13} aria-hidden="true" />仅用于账号登录，不涉及付款</p>
    </section>
  </main>
}
