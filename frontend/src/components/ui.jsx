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
    dialogRef.current?.focus()
  }, [open])

  if (!open) return null

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <div
        ref={dialogRef}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && !busy) onCancel?.()
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
