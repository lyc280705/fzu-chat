// Same-client web OAuth only. No native bridge, browser-return scheme, storage,
// auth-code handling or automatic failure/retry loop.
;(function () {
  const accepted = new URLSearchParams(window.location.hash.slice(1)).get('native_consent') === '1'
  window.history.replaceState(null, '', window.location.pathname)
  const title = document.getElementById('entry-title')
  const error = document.getElementById('entry-error')
  const next = document.getElementById('entry-continue')
  function fail(message) {
    title.textContent = '继续支付宝登录'
    error.textContent = message
    error.hidden = false
  }
  if (!accepted) {
    fail('本次登录入口已失效，请返回登录页，勾选同意协议后重新点击支付宝。')
    return
  }
  if (!/AlipayClient|AliApp\(AP\//i.test(navigator.userAgent)) {
    fail('请从浏览器登录页点击“打开支付宝”，在支付宝内继续。')
    return
  }
  next.hidden = false
  try {
    window.location.replace('/api/auth/oauth/alipay/start?accepted_legal=true')
  } catch {
    fail('未能自动打开授权页，请点击“继续支付宝授权”。')
  }
})()
