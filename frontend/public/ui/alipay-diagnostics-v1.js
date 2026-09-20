// Early, passive, page-local observations only. Version the filename when changing
// this file: /ui assets are cached immutably. Never capture URLs or auth payloads.
;(function () {
  if (window.location.pathname !== '/api/auth/oauth/alipay/callback') return
  const started = performance.now()
  const entries = []
  let dropped = 0
  let finished = false
  const labels = {
    prepare_start: '准备请求开始', prepare_ok: '准备请求成功', prepare_error: '准备请求失败',
    bridge_wait: '等待原生接口', bridge_timeout: '原生接口等待超时',
    native_start: '调用 getAuthCode', native_result: '原生授权回调（数字错误码）',
    native_code: '原生回调包含授权码（不记录内容）', native_throw: '调用原生接口抛出异常',
    native_timeout: '原生授权回调超时', complete_start: '提交授权结果',
    complete_ok: '登录完成', complete_error: '提交授权结果失败',
  }
  function bridge() {
    try {
      const value = window.AlipayJSBridge
      return !value ? '未出现' : typeof value.call === 'function' ? '存在，call 可用' : '存在，call 不可用'
    } catch { return '读取异常' }
  }
  function append(label) {
    if (entries.length < 64) entries.push(`${((performance.now() - started) / 1000).toFixed(1)}s ${label}`)
    else dropped += 1
    window.dispatchEvent(new Event('fzu-alipay-diagnostic'))
  }
  function resourceCategory(value) {
    if (['inline', 'eval', 'wasm-eval'].includes(value)) return value
    try {
      const url = new URL(value)
      if (!['http:', 'https:'].includes(url.protocol)) return '其他资源'
      if (url.origin === window.location.origin) return '本站资源'
      if (/(^|\.)(alipay\.com|alipayobjects\.com)$/.test(url.hostname)) return '支付宝域名资源'
      return '其他外部资源'
    } catch { return '未知资源' }
  }
  document.addEventListener('AlipayJSBridgeReady', () => append(`收到就绪事件；接口${bridge()}`))
  document.addEventListener('securitypolicyviolation', event => {
    const directives = ['script-src', 'script-src-elem', 'script-src-attr', 'connect-src', 'default-src', 'style-src', 'style-src-elem', 'style-src-attr', 'img-src', 'frame-src', 'font-src', 'worker-src']
    const rule = directives.includes(event.effectiveDirective) ? event.effectiveDirective : '其他规则'
    const action = event.disposition === 'enforce' ? '实际拦截' : '仅报告/未知'
    append(`CSP ${action}：${rule} / ${resourceCategory(event.blockedURI)}`)
  })
  window.__fzuAlipayDiagnostic = {
    mark(stage, code) {
      if (!Object.hasOwn(labels, stage)) return
      const numericCode = typeof code === 'number' || (typeof code === 'string' && /^\d{1,6}$/.test(code)) ? Number(code) : NaN
      const suffix = Number.isSafeInteger(numericCode) && Math.abs(numericCode) <= 999999 ? ` [${numericCode}]` : ''
      append(`${labels[stage]}${suffix}；接口${bridge()}`)
    },
    report() {
      return [
        '福大灵犀 · 支付宝诊断 v1 / v7.29',
        `开始记录：页面加载后 ${Math.round(started)}ms`,
        `环境：${/AlipayClient|AliApp\(AP\//i.test(navigator.userAgent) ? '支付宝内' : '其他浏览器'}；安全上下文：${window.isSecureContext ? '是' : '否'}`,
        `定时观察：${finished ? '已完成 15 秒' : '进行中，请停留至 15 秒'}`,
        ...entries,
        ...(dropped ? [`已省略 ${dropped} 条重复/超量事件`] : []),
        '仅记录状态；不含授权码、Cookie、账号、密钥或完整网址。',
        '没有 CSP 记录不代表排除拦截；记录开始前的事件无法回溯。',
      ].join('\n')
    },
  }
  append(`诊断开始；接口${bridge()}`)
  for (const seconds of [1, 3, 8, 15]) setTimeout(() => {
    if (seconds === 15) finished = true
    append(`定时观察；接口${bridge()}`)
  }, seconds * 1000)
})()
