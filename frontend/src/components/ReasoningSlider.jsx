import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'

const clamp = (value) => Math.max(0, Math.min(1, value))
const THUMB_RADIUS = 14

export function ReasoningSlider({ options, value, modelLabel, onChange, onChooseModel, descriptionId, active = true }) {
  const max = Math.max(0, options.length - 1)
  const savedIndex = Math.max(0, options.findIndex(option => option.value === value))
  const savedRatio = max ? savedIndex / max : 0
  const [dragIndex, setDragIndex] = useState(null)
  const sliderRef = useRef(null)
  const pointerRef = useRef(null)
  const frameRef = useRef(0)
  const visualRatioRef = useRef(savedRatio)
  const reducedMotionRef = useRef(false)
  const index = dragIndex ?? savedIndex
  const option = options[index]

  // Paint once per frame; React only updates the label at discrete detents.
  const paint = (ratio) => {
    visualRatioRef.current = ratio
    sliderRef.current?.style.setProperty('--reasoning-ratio', String(ratio))
  }
  const settle = (target) => {
    cancelAnimationFrame(frameRef.current)
    if (reducedMotionRef.current) { paint(target); return }
    let position = visualRatioRef.current
    let velocity = 0
    let previousTime = performance.now()
    const tick = (time) => {
      const elapsed = Math.min((time - previousTime) / 1000, 0.032)
      previousTime = time
      // Small integration steps keep the damped spring stable at 60/120 Hz.
      const steps = Math.max(1, Math.ceil(elapsed / 0.008))
      const dt = elapsed / steps
      for (let step = 0; step < steps; step += 1) {
        velocity += ((target - position) * 480 - velocity * 32) * dt
        position += velocity * dt
      }
      paint(clamp(position))
      if (Math.abs(target - position) < 0.0003 && Math.abs(velocity) < 0.003) {
        paint(target)
        frameRef.current = 0
      } else {
        frameRef.current = requestAnimationFrame(tick)
      }
    }
    frameRef.current = requestAnimationFrame(tick)
  }
  const settleRef = useRef(settle)
  useEffect(() => { settleRef.current = settle })

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => { reducedMotionRef.current = media.matches }
    update()
    media.addEventListener('change', update)
    const element = sliderRef.current
    const resize = () => element?.style.setProperty('--slider-travel', `${Math.max(0, element.clientWidth - THUMB_RADIUS * 2)}px`)
    const observer = new ResizeObserver(resize)
    if (element) observer.observe(element)
    resize()
    return () => {
      media.removeEventListener('change', update)
      observer.disconnect()
      cancelAnimationFrame(frameRef.current)
    }
  }, [])

  useEffect(() => {
    if (!pointerRef.current) settleRef.current(savedRatio)
  }, [savedRatio, active])

  const pointerRatio = (event) => {
    const pointer = pointerRef.current
    return clamp((event.clientX - pointer.left - THUMB_RADIUS - pointer.offset) / pointer.travel)
  }
  const cancelDrag = () => {
    if (!pointerRef.current) return
    pointerRef.current = null
    setDragIndex(null)
    settle(savedRatio)
  }
  const finishDrag = (event, commit) => {
    if (pointerRef.current?.id !== event.pointerId) return
    const nextIndex = commit ? Math.round(pointerRatio(event) * max) : savedIndex
    pointerRef.current = null
    setDragIndex(null)
    settle(max ? nextIndex / max : 0)
    if (commit && nextIndex !== savedIndex) onChange(options[nextIndex]?.value)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return <>
    <button type="button" className="composer-popover-model" title={`当前模型：${modelLabel}，点击切换模型`} aria-label={`选择模型：${modelLabel}`} onClick={onChooseModel}>
      <span className="reasoning-value-window" aria-hidden="true">
        <span className="reasoning-value-stack" style={{ transform: `translate3d(0, ${-index * 24}px, 0)` }}>
          {options.length ? options.map(item => <span className="reasoning-value" key={item.value}>{item.label}</span>) : <span className="reasoning-value">默认</span>}
        </span>
      </span>
      <ChevronRight size={11} strokeWidth={1.5} aria-hidden="true" />
    </button>
    <div ref={sliderRef} className="reasoning-slider" data-dragging={dragIndex !== null} data-disabled={!max}>
      <div className="reasoning-slider-track" aria-hidden="true">
        <div className="reasoning-slider-fill" />
        {options.map((item, i) => <i key={item.value} className={i <= index ? 'is-filled' : ''} style={{ '--tick-ratio': i / Math.max(1, max) }} />)}
      </div>
      <div className="reasoning-slider-thumb" aria-hidden="true"><span /></div>
      <input type="range" min="0" max={max} step="1" value={index} disabled={!max}
        aria-label="推理强度" aria-valuetext={option?.label || '默认'} aria-describedby={descriptionId}
        onChange={event => { if (!pointerRef.current) onChange(options[Number(event.target.value)]?.value) }}
        onPointerDown={event => {
          if (event.button !== 0 || !event.isPrimary || !max) return
          event.preventDefault()
          event.currentTarget.focus({ preventScroll: true })
          const bounds = event.currentTarget.getBoundingClientRect()
          const travel = Math.max(1, bounds.width - THUMB_RADIUS * 2)
          const fromThumb = event.clientX - (bounds.left + THUMB_RADIUS + visualRatioRef.current * travel)
          pointerRef.current = { id: event.pointerId, left: bounds.left, travel, offset: Math.abs(fromThumb) <= THUMB_RADIUS ? fromThumb : 0 }
          event.currentTarget.setPointerCapture(event.pointerId)
          const ratio = pointerRatio(event)
          cancelAnimationFrame(frameRef.current)
          paint(ratio)
          setDragIndex(Math.round(ratio * max))
        }}
        onPointerMove={event => {
          if (pointerRef.current?.id !== event.pointerId) return
          const ratio = pointerRatio(event)
          cancelAnimationFrame(frameRef.current)
          frameRef.current = requestAnimationFrame(() => paint(ratio))
          const nextIndex = Math.round(ratio * max)
          setDragIndex(current => current === nextIndex ? current : nextIndex)
        }}
        onPointerUp={event => finishDrag(event, true)}
        onPointerCancel={event => finishDrag(event, false)}
        onLostPointerCapture={cancelDrag}
        onBlur={cancelDrag}
      />
    </div>
    <span id={descriptionId} className="sr-only">{option?.description}。使用左右方向键调整。</span>
  </>
}
