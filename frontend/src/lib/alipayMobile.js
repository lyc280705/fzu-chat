export const mobileOutsideAlipay = (ua, touchPoints = 0) => !/AlipayClient|AliApp\(AP\//i.test(ua)
  && (/Android|iPhone|iPad|iPod|Mobile/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1))

// Open the web-OAuth entry inside Alipay; keep the consent marker for existing tabs.
// The fragment carries consent only, never a code, state or session credential.
export function alipayInAppUrl(origin) {
  const base = new URL(origin)
  const landing = `${base.origin}/api/auth/oauth/alipay/callback#native_consent=1`
  return `alipays://platformapi/startapp?${new URLSearchParams({ appId: '20000067', url: landing })}`
}
