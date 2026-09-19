import { useEffect, useId, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Check, ChevronDown, Pencil, RotateCcw, Square, X } from 'lucide-react'
import { ReasoningSlider } from './ReasoningSlider'

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
  models,
  onChange,
  onCancelEdit,
  onModelChange,
  onReasoningChange,
  onRestoreFailedPrompt,
  onRetryFailedPrompt,
  onScrollBottom,
  onStop,
  onSubmit,
  reasoningOptions,
  reasoningValue,
  selectedModel,
  showScrollBottom,
  statusText,
}) {
  const [panelView, setPanelView] = useState('reasoning')
  const [panelOpen, setPanelOpen] = useState(false)
  const setOpenPanel = (view) => {
    if (view) setPanelView(view)
    setPanelOpen(Boolean(view))
  }
  const controlsRef = useRef(null)
  const reasoningTriggerRef = useRef(null)
  const panelId = useId()
  const describedBy = statusText ? 'composer-status composer-runtime-status' : 'composer-status'
  const reasoningIndex = Math.max(0, reasoningOptions.findIndex((option) => option.value === reasoningValue))
  const reasoningOption = reasoningOptions[reasoningIndex]
  const modelLabel = models.find((model) => model.id === selectedModel)?.label || selectedModel
  const selectedModelIndex = Math.max(0, models.findIndex((model) => model.id === selectedModel))
  const visiblePanel = !isStreaming && panelOpen ? panelView : null

  useEffect(() => {
    if (!visiblePanel) return undefined
    let tabFocusFrame = 0
    const handleOutside = (event) => {
      if (!controlsRef.current?.contains(event.target)) setOpenPanel(null)
    }
    const handleKey = (event) => {
      if (event.key === 'Tab') {
        cancelAnimationFrame(tabFocusFrame)
        tabFocusFrame = requestAnimationFrame(() => {
          if (!controlsRef.current?.contains(document.activeElement)) setOpenPanel(null)
        })
        return
      }
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      setOpenPanel(null)
      reasoningTriggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', handleOutside)
    // Safari moves focus to the page when clicking an unfocusable button.
    // Dismiss pointer interactions by hit target, and keyboard exits after
    // Tab completes; neither blur nor focusin reliably identifies outside clicks.
    document.addEventListener('keydown', handleKey, true)
    return () => {
      document.removeEventListener('pointerdown', handleOutside)
      cancelAnimationFrame(tabFocusFrame)
      document.removeEventListener('keydown', handleKey, true)
    }
  }, [visiblePanel])

  useEffect(() => {
    if (!visiblePanel) return
    const panel = controlsRef.current?.querySelector('[role="dialog"]')
    const target = visiblePanel === 'model'
      ? panel?.querySelector('[aria-pressed="true"]') || panel?.querySelector('.composer-model-option')
      : panel?.querySelector('input')
    target?.focus({ preventScroll: true })
  }, [visiblePanel])

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
          <span>正在修改已发送的问题，发送后会覆盖这条问题之后的所有内容</span>
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
          placeholder={editingMessage ? '修改这条问题，发送后会覆盖之后的所有内容' : '问问灵犀，或分享你的想法…'}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              if (event.nativeEvent.isComposing || event.keyCode === 229) return
              event.preventDefault()
              onSubmit(event)
            }
          }}
          aria-label={editingMessage ? '修改消息内容' : '消息输入框'}
          aria-describedby={describedBy}
          aria-invalid={inputLength > maxLength}
        />
        <div className="composer-toolbar">
          <div id="composer-status" className={inputNearLimit ? 'composer-status composer-status--warn' : 'composer-status'} aria-live={inputNearLimit ? 'polite' : 'off'}>
            {inputLength}/{maxLength}
          </div>
          <div
            className="composer-controls"
            ref={controlsRef}
          >
            <button
              ref={reasoningTriggerRef}
              type="button"
              className="composer-setting-trigger composer-reasoning-trigger"
              disabled={isStreaming || !models.length}
              aria-label={`模型与推理强度：${modelLabel}，${reasoningOption?.label || '默认'}`}
              title={`${modelLabel} · ${reasoningOption?.label || '默认'}`}
              aria-haspopup="dialog"
              aria-expanded={Boolean(visiblePanel)}
              aria-controls={visiblePanel ? `${panelId}-reasoning` : undefined}
              onClick={() => setOpenPanel(visiblePanel ? null : 'reasoning')}
            >
              <span className="composer-trigger-model">{modelLabel}</span>
              <span className="composer-trigger-dot" aria-hidden="true">·</span>
              <span>{reasoningOption?.label || '默认'}</span><ChevronDown size={11} strokeWidth={1.5} aria-hidden="true" />
            </button>
              <div className="composer-settings-popover reasoning-popover" role="dialog" aria-label="模型与推理强度" id={`${panelId}-reasoning`}
                data-open={Boolean(visiblePanel)} data-view={panelView} aria-hidden={!visiblePanel} inert={!visiblePanel}
                style={{ '--model-panel-height': `${40 * models.length}px` }}>
                <div className="composer-settings-pane composer-settings-pane--model" aria-hidden={panelView !== 'model'} inert={panelView !== 'model'}>
                  <div className="composer-model-options">
                  <div className="composer-model-selection" aria-hidden="true" style={{ transform: `translate3d(0, ${selectedModelIndex * 40}px, 0)` }} />
                  {models.map((model) => (
                    <button
                      type="button"
                      key={model.id}
                      className="composer-model-option"
                      aria-pressed={model.id === selectedModel}
                      onClick={() => {
                        onModelChange(model.id)
                        setOpenPanel('reasoning')
                      }}
                    >
                      <span>{model.label}</span>
                      {model.id === selectedModel && <Check size={14} strokeWidth={1.7} aria-hidden="true" />}
                    </button>
                  ))}
                  </div>
                </div>
                <div className="composer-settings-pane composer-settings-pane--reasoning" aria-hidden={panelView !== 'reasoning'} inert={panelView !== 'reasoning'}>
                  <ReasoningSlider options={reasoningOptions} value={reasoningValue} modelLabel={modelLabel} active={visiblePanel === 'reasoning'}
                    onChange={onReasoningChange} onChooseModel={() => setOpenPanel('model')} descriptionId={`${panelId}-description`} />
                </div>
              </div>
          </div>
          <button
            className={`send-btn ${isStreaming ? 'send-btn--stop' : ''}`}
            type={isStreaming ? 'button' : 'submit'}
            disabled={isStreaming ? isStopPending : disabled}
            onClick={isStreaming ? onStop : undefined}
            aria-describedby={statusText ? 'composer-runtime-status' : undefined}
            aria-label={isStreaming ? '停止响应' : editingMessage ? '提交修改并覆盖之后的所有内容' : '发送消息'}
            title={isStreaming ? '停止响应' : editingMessage ? '提交修改并覆盖之后的所有内容' : '发送消息'}
          >
            {isStreaming ? <Square size={13} fill="currentColor" aria-hidden="true" /> : <ArrowUp size={20} strokeWidth={2.3} aria-hidden="true" />}
          </button>
        </div>
      </form>
      <p className="composer-footnote">灵犀也可能出错，重要信息请核实。<span>Enter 发送 · Shift + Enter 换行</span></p>
    </footer>
  )
}
