import { useEffect, useState } from 'react'
import { Fingerprint, Plus, Trash2 } from 'lucide-react'
import { passkeyErrorMessage, passkeyRequest, supportsPasskeys, runPasskeyCeremony } from '../lib/passkeys.js'
import '../passkeys.css'
import '../alipay-mobile.css'

export function PasskeyLogin({ acceptedLegal, onBack }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const start = async register => {
    if (!acceptedLegal) { setError('请先阅读并同意用户协议与隐私政策。'); return }
    setBusy(register ? 'register' : 'login')
    setError('')
    try { await runPasskeyCeremony(register); window.location.replace('/') }
    catch (err) { setError(passkeyErrorMessage(err, register)); setBusy('') }
  }
  return <section className="alipay-handoff alipay-handoff--page" aria-label="通行密钥登录">
    <Fingerprint size={32} aria-hidden="true" /><h1>使用通行密钥</h1>
    <p>无需用户名、邮箱或第三方账号。用设备解锁方式即可进入福大灵犀。</p>
    <button type="button" className="alipay-handoff__primary" disabled={Boolean(busy) || !supportsPasskeys()} onClick={() => start(false)}>{busy === 'login' ? '请在设备上确认…' : '使用已有通行密钥登录'}</button>
    <button type="button" className="alipay-handoff__secondary passkey-create" disabled={Boolean(busy) || !supportsPasskeys()} onClick={() => start(true)}>{busy === 'register' ? '请在设备上创建…' : '首次使用：创建通行密钥并进入'}</button>
    <p className="alipay-handoff__hint">已有通行密钥请直接登录。再次创建会建立另一个独立身份，聊天记录不会自动合并。请保留通行密钥同步或备份，全部丢失后无法找回该身份。</p>
    {!supportsPasskeys() && <p role="alert" className="alipay-handoff__error">当前浏览器不支持通行密钥，请使用系统浏览器。支付宝等内置浏览器可能不支持。</p>}
    {error && <p role="alert" className="alipay-handoff__error">{error}</p>}
    <button type="button" className="alipay-handoff__cancel" onClick={onBack} disabled={Boolean(busy)}>返回其他登录方式</button>
  </section>
}

export function PasskeySettings() {
  const [keys, setKeys] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [removing, setRemoving] = useState('')
  useEffect(() => {
    let active = true
    passkeyRequest('credentials').then(value => { if (active) setKeys(value) }).catch(err => { if (active) setError(passkeyErrorMessage(err)) })
    return () => { active = false }
  }, [])
  const act = async action => {
    setBusy(true); setError('')
    try { await action(); setKeys(await passkeyRequest('credentials')); setRemoving('') }
    catch (err) { setError(passkeyErrorMessage(err)) }
    finally { setBusy(false) }
  }
  return <section className="privacy-card passkey-settings" aria-label="管理通行密钥">
    <h3><Fingerprint size={19} aria-hidden="true" />通行密钥</h3>
    <p>为当前身份添加设备或同步密钥，之后无需输入密码。管理密钥前需要在最近 10 分钟内登录。</p>
    <ul>{keys.map(key => <li key={key.id}><div><strong>{key.name}</strong><small>创建于 {new Date(key.created * 1000).toLocaleDateString()} · {key.used ? `最近使用 ${new Date(key.used * 1000).toLocaleDateString()}` : '尚未用于登录'}</small></div>
      {removing === key.id ? <span className="passkey-actions"><button type="button" className="danger-btn" disabled={busy} onClick={() => act(() => passkeyRequest('credentials', { credential_id: key.id }, 'DELETE'))}>确认移除</button><button type="button" className="secondary-btn" disabled={busy} onClick={() => setRemoving('')}>取消</button></span>
        : <button type="button" className="secondary-btn" aria-label={`移除${key.name}`} disabled={busy} onClick={() => setRemoving(key.id)}><Trash2 size={15} /></button>}</li>)}</ul>
    {!keys.length && <p>尚未为此身份设置通行密钥。</p>}
    <button type="button" className="secondary-btn" disabled={busy || !supportsPasskeys()} onClick={() => act(() => runPasskeyCeremony(true, true))}><Plus size={16} />{busy ? '处理中…' : '添加通行密钥'}</button>
    {!supportsPasskeys() && <p>此浏览器暂不支持创建通行密钥。</p>}
    <p className="passkey-hint">移除会停用本站验证凭据，但不会自动删除设备密码管理器中的条目。独立 Passkey 身份不能移除最后一个密钥；如需停用，请删除账号。</p>
    {error && <p role="alert" className="passkey-error">{error}</p>}
  </section>
}
