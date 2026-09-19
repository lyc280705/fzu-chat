import { useLayoutEffect } from 'react'

export function useAutoResizeTextarea(ref, value, maxHeight = 180) {
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const resize = () => {
      const style = getComputedStyle(element)
      const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
      const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
      element.style.height = 'auto'
      // Empty placeholders must not make the composer taller on narrow screens.
      const contentHeight = element.value ? element.scrollHeight : parseFloat(style.lineHeight) + padding
      element.style.height = `${Math.min(contentHeight + border, maxHeight)}px`
      element.style.overflowY = contentHeight + border > maxHeight ? 'auto' : 'hidden'
    }
    resize()

    // Reflow wrapped drafts when the viewport or sidebar changes width.
    let width = element.clientWidth
    const observer = new ResizeObserver(() => {
      if (element.clientWidth === width) return
      width = element.clientWidth
      resize()
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [maxHeight, ref, value])
}
