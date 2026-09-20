import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AlipayHandoffPage } from './components/AlipayMobileLogin.jsx'
import { readMobileEntry } from './lib/alipayMobile.js'

const mobileEntry = readMobileEntry(window.location)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {mobileEntry ? <AlipayHandoffPage entry={mobileEntry} /> : <App />}
  </StrictMode>,
)
