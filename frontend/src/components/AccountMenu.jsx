import { useEffect, useId, useRef, useState } from 'react'
import { LogOut, ShieldCheck } from 'lucide-react'

export function AccountMenu({ user, avatarUrl, modeText, privacyActive, onPrivacy, onLogout }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    let frame = requestAnimationFrame(() => rootRef.current?.querySelector('.account-menu-action')?.focus({ preventScroll: true }))
    const outside = event => { if (!rootRef.current?.contains(event.target)) setOpen(false) }
    const keydown = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        setOpen(false)
        triggerRef.current?.focus()
      } else if (event.key === 'Tab') {
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(() => { if (!rootRef.current?.contains(document.activeElement)) setOpen(false) })
      }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', keydown, true)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', keydown, true)
    }
  }, [open])

  return (
    <div className="account-menu" ref={rootRef}>
      <div id={menuId} className="account-menu-popover" role="dialog" aria-label="账号设置" aria-hidden={!open} inert={!open} data-open={open}>
        <span className="account-menu-caption">账号设置</span>
        <button type="button" className="account-menu-action" aria-current={privacyActive ? 'page' : undefined} onClick={() => { setOpen(false); onPrivacy() }}>
          <ShieldCheck size={17} aria-hidden="true" /><span>隐私与数据</span>
        </button>
        <div className="account-menu-divider" />
        <button type="button" className="account-menu-action account-menu-action--logout" onClick={() => { setOpen(false); void onLogout() }}>
          <LogOut size={17} aria-hidden="true" /><span>退出登录</span>
        </button>
      </div>
      <button type="button" ref={triggerRef} className="user-card account-menu-trigger" title="账号设置" aria-label={`账号设置：${user.display_name || '用户'}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen(value => !value)}>
        <span className={avatarUrl ? 'user-avatar user-avatar--image' : 'user-avatar'}>
          {avatarUrl ? <img src={avatarUrl} alt="" referrerPolicy="no-referrer" /> : (user.display_name?.charAt(0) || 'U')}
        </span>
        <span className="user-info"><strong>{user.display_name}</strong><span>{modeText}</span></span>
      </button>
    </div>
  )
}
