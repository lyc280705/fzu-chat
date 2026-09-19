import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export function IconButton({
  label,
  title,
  children,
  className = '',
  variant = 'default',
  ...props
}) {
  return (
    <button
      {...props}
      className={`icon-btn icon-btn--${variant} ${className}`.trim()}
      aria-label={label}
      title={title || label}
      type={props.type || 'button'}
    >
      {children}
    </button>
  )
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  danger = false,
  busy = false,
  details,
  onCancel,
  onConfirm,
}) {
  const dialogRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    return () => { if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true }) }
  }, [open])

  if (!open) return null

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => { if (!busy) onCancel?.() }}>
      <div
        ref={dialogRef}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation()
            if (!busy) onCancel?.()
          }
          if (event.key === 'Tab') {
            const buttons = [...event.currentTarget.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), [tabindex="0"]')]
            const first = buttons[0]
            const last = buttons.at(-1)
            if (!first) { event.preventDefault(); return }
            if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
              event.preventDefault(); last.focus()
            } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.current)) {
              event.preventDefault(); first.focus()
            }
          }
        }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-dialog__header">
          <h3 id="confirm-dialog-title">{title}</h3>
          <IconButton label="关闭弹窗" className="confirm-dialog__close" onClick={onCancel} disabled={busy}>
            <X size={18} aria-hidden="true" />
          </IconButton>
        </div>
        <p id="confirm-dialog-description">{description}</p>
        {details && <div className="confirm-dialog__details">{details}</div>}
        <div className="confirm-dialog__actions">
          <button type="button" className="secondary-btn" onClick={onCancel} disabled={busy}>
            {cancelText}
          </button>
          <button
            type="button"
            className={danger ? 'danger-btn' : 'primary-btn'}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? '处理中…' : confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
