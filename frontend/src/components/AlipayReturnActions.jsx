import { useState } from 'react'
import { ArrowRight, Check, Copy } from 'lucide-react'
import { browserReturnUrl, completionUrl } from '../lib/alipayMobile.js'

export default function AlipayReturnActions({ origin, entry }) {
  const [copied, setCopied] = useState(false)
  const [showLink, setShowLink] = useState(false)
  const nativeUrl = browserReturnUrl(origin, entry)
  const webUrl = completionUrl(origin, entry)
  const browser = entry.browser === 'edge_android' ? 'Edge' : entry.browser === 'safari' ? 'Safari'
    : ['chrome_android', 'chrome_ios'].includes(entry.browser) ? 'Chrome' : '原浏览器'
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(webUrl)
      setCopied(true)
    } catch { setShowLink(true) }
  }
  if (!webUrl) return <p role="alert">返回信息不完整，请回原浏览器重新登录。</p>
  return <div className="alipay-return-actions">
    <p>支付宝授权已完成。请返回 {browser}，完成网站登录。</p>
    {nativeUrl && <a className="alipay-handoff__primary" href={nativeUrl}>返回 {browser} 完成登录<ArrowRight size={16} aria-hidden="true" /></a>}
    <button type="button" className={nativeUrl ? 'alipay-handoff__secondary' : 'alipay-handoff__primary'} onClick={copyLink}>
      {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
      {copied ? '已复制返回链接' : '复制返回链接'}
    </button>
    <p className="alipay-handoff__hint" role="status">{copied
      ? `请切回 ${browser}，把链接粘贴到地址栏并打开，即可完成登录。`
      : `如果返回按钮被拦截，可复制链接后在 ${browser} 地址栏粘贴打开，无需操作支付宝右上角菜单。`}</p>
    {showLink && <label className="alipay-handoff__link-label">无法自动复制，请长按下方链接全选并复制
      <textarea className="alipay-handoff__return-link" readOnly value={webUrl} aria-label="一次性返回链接" onFocus={event => event.target.select()} />
    </label>}
    <p className="alipay-handoff__hint">仅在刚才发起登录的浏览器及相同浏览模式中有效。请勿转发此一次性链接。</p>
  </div>
}
