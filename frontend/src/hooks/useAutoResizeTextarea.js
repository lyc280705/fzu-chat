import { useLayoutEffect } from 'react'

export function useAutoResizeTextarea(ref, value, maxHeight = 180) {
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`
  }, [maxHeight, ref, value])
}
