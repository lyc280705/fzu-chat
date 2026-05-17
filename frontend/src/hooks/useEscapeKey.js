import { useEffect } from 'react'

export function useEscapeKey(enabled, onEscape) {
  useEffect(() => {
    if (!enabled) return undefined

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onEscape(event)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [enabled, onEscape])
}
