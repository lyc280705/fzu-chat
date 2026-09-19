import { useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'

export function ReasoningSlider({ options, value, modelLabel, onChange, onChooseModel, descriptionId }) {
  const [dragRatio, setDragRatio] = useState(null)
  const pointerRef = useRef(null)
  const max = Math.max(0, options.length - 1)
  const savedIndex = Math.max(0, options.findIndex(option => option.value === value))
  const index = dragRatio === null ? savedIndex : Math.round(dragRatio * max)
  const option = options[index]
  const ratio = dragRatio ?? (max ? savedIndex / max : 0)

  const pointerRatio = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return Math.max(0, Math.min(1, (event.clientX - bounds.left - 12) / Math.max(1, bounds.width - 24)))
  }
  const finishDrag = (event, commit) => {
    if (pointerRef.current !== event.pointerId) return
    pointerRef.current = null
    if (commit) onChange(options[Math.round(pointerRatio(event) * max)]?.value)
    setDragRatio(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return <>
    <button type="button" className="composer-popover-model" title={`当前模型：${modelLabel}，点击切换模型`} aria-label={`选择模型：${modelLabel}`} onClick={onChooseModel}>
      <span className="reasoning-value" key={option?.value}>{option?.label || '默认'}</span><ChevronRight size={11} strokeWidth={1.5} aria-hidden="true" />
    </button>
    <div className="reasoning-slider" data-dragging={dragRatio !== null} style={{ '--reasoning-ratio': ratio }}>
      <div className="reasoning-slider-track" aria-hidden="true">
        <div className="reasoning-slider-fill" />
        {options.map((item, i) => <i key={item.value} className={i <= index ? 'is-filled' : ''} style={{ '--tick-ratio': i / Math.max(1, max) }} />)}
      </div>
      <div className="reasoning-slider-thumb" aria-hidden="true" />
      <input type="range" min="0" max={max} step="1" value={index} disabled={!max}
        aria-label="推理强度" aria-valuetext={option?.label || '默认'} aria-describedby={descriptionId}
        onChange={event => { if (pointerRef.current === null) onChange(options[Number(event.target.value)]?.value) }}
        onPointerDown={event => {
          if (event.button !== 0 || !max) return
          event.preventDefault()
          event.currentTarget.focus({ preventScroll: true })
          pointerRef.current = event.pointerId
          event.currentTarget.setPointerCapture(event.pointerId)
          setDragRatio(pointerRatio(event))
        }}
        onPointerMove={event => { if (pointerRef.current === event.pointerId) setDragRatio(pointerRatio(event)) }}
        onPointerUp={event => finishDrag(event, true)}
        onPointerCancel={event => finishDrag(event, false)}
        onLostPointerCapture={() => { pointerRef.current = null; setDragRatio(null) }}
        onBlur={() => { pointerRef.current = null; setDragRatio(null) }}
      />
    </div>
    <span id={descriptionId} className="sr-only">{option?.description}。使用左右方向键调整。</span>
  </>
}
