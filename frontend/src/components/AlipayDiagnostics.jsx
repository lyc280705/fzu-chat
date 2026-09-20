import { useEffect, useRef, useState } from 'react'

const readReport = () => window.__fzuAlipayDiagnostic?.report() || '诊断脚本未加载，无法判断桥接接口状态。请退出此页后重新发起登录。'

export function AlipayDiagnostics() {
  const [report, setReport] = useState(readReport)
  const [copyHint, setCopyHint] = useState('')
  const field = useRef(null)
  useEffect(() => {
    const update = () => setReport(readReport())
    window.addEventListener('fzu-alipay-diagnostic', update)
    update()
    return () => window.removeEventListener('fzu-alipay-diagnostic', update)
  }, [])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(readReport())
      setCopyHint('已复制，请把诊断信息发给我们。')
    } catch {
      field.current?.focus()
      field.current?.select()
      setCopyHint('已选中文本，请长按复制；也可以截图。')
    }
  }
  return <section className="alipay-diagnostics" aria-labelledby="alipay-diagnostics-title">
    <h2 id="alipay-diagnostics-title">登录诊断</h2>
    <p>请在本页停留至 15 秒，再复制下方信息或截图。仅在当前页面记录状态，不会自动上传。</p>
    <textarea ref={field} className="alipay-diagnostics__report" aria-label="支付宝登录诊断信息" value={report} readOnly spellCheck={false} />
    <button type="button" className="alipay-handoff__secondary" onClick={copy}>复制诊断信息</button>
    <p role="status" className="alipay-handoff__hint">{copyHint}</p>
  </section>
}
