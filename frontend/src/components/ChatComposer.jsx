import { ArrowDown, Pause, Pencil, RotateCcw, Send, X } from 'lucide-react'

export function ChatComposer({
  composerRef,
  disabled,
  editingMessage,
  error,
  failedPrompt,
  input,
  inputLength,
  inputNearLimit,
  isStopPending,
  isStreaming,
  maxLength,
  onChange,
  onCancelEdit,
  onRestoreFailedPrompt,
  onRetryFailedPrompt,
  onScrollBottom,
  onStop,
  onSubmit,
  showScrollBottom,
  statusText,
}) {
  const describedBy = statusText ? 'composer-status composer-runtime-status' : 'composer-status'

  return (
    <footer className="composer-area">
      {showScrollBottom && (
        <button type="button" className="scroll-bottom-btn" onClick={onScrollBottom}>
          <ArrowDown size={16} aria-hidden="true" /> 回到底部
        </button>
      )}

      {(error || failedPrompt) && (
        <div className={failedPrompt ? 'err-banner err-banner--actionable' : 'err-banner'} role="alert">
          <span>{failedPrompt?.message || error}</span>
          {failedPrompt && (
            <div className="err-banner__actions">
              <button type="button" className="secondary-btn secondary-btn--compact" onClick={onRestoreFailedPrompt}>
                恢复输入
              </button>
              <button type="button" className="primary-btn primary-btn--compact" onClick={onRetryFailedPrompt}>
                <RotateCcw size={14} aria-hidden="true" /> 重试
              </button>
            </div>
          )}
        </div>
      )}

      {statusText && (
        <div id="composer-runtime-status" className="composer-runtime-status" role="status" aria-live="polite">
          {statusText}
        </div>
      )}

      {editingMessage && (
        <div className="composer-editing" role="status" aria-live="polite">
          <Pencil size={15} aria-hidden="true" />
          <span>正在修改已发送的问题</span>
          <button type="button" onClick={onCancelEdit} aria-label="取消修改" title="取消修改">
            <X size={15} aria-hidden="true" />
          </button>
        </div>
      )}

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          ref={composerRef}
          value={input}
          onChange={(event) => onChange(event.target.value)}
          maxLength={maxLength + 1}
          placeholder={editingMessage ? '修改这条问题，发送后将重新生成回复' : '输入问题，按 Enter 发送，Shift+Enter 换行'}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              onSubmit(event)
            }
          }}
          aria-label={editingMessage ? '修改消息内容' : '消息输入框'}
          aria-describedby={describedBy}
          aria-invalid={inputLength > maxLength}
        />
        <div id="composer-status" className={inputNearLimit ? 'composer-status composer-status--warn' : 'composer-status'} aria-live={inputNearLimit ? 'polite' : 'off'}>
          {inputLength}/{maxLength}
        </div>
        <button
          className={`send-btn ${isStreaming ? 'send-btn--stop' : ''}`}
          type={isStreaming ? 'button' : 'submit'}
          disabled={isStreaming ? isStopPending : disabled}
          onClick={isStreaming ? onStop : undefined}
          aria-describedby={statusText ? 'composer-runtime-status' : undefined}
          aria-label={isStreaming ? '停止响应' : editingMessage ? '提交修改并重新生成' : '发送消息'}
          title={isStreaming ? '停止响应' : editingMessage ? '提交修改并重新生成' : '发送消息'}
        >
          {isStreaming ? <Pause size={18} aria-hidden="true" /> : <Send size={18} aria-hidden="true" />}
        </button>
      </form>
    </footer>
  )
}
