import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AlipayHandoffPage } from './components/AlipayMobileLogin.jsx'
import { readMobileEntry } from './lib/alipayMobile.js'
import { AlipayNativeLogin } from './components/AlipayNativeLogin.jsx'

const mobileEntry = readMobileEntry(window.location)
const nativeAlipay = window.location.pathname === '/api/auth/oauth/alipay/callback'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {nativeAlipay ? <AlipayNativeLogin /> : mobileEntry ? <AlipayHandoffPage entry={mobileEntry} /> : <App />}
  </StrictMode>,
)
