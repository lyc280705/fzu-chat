import { useState } from 'react'

// Keep an opened panel mounted so reversing the animation does not reset its
// contents. Never-opened tool results stay lazy, including large grade tables.
export function AnimatedCollapse({ open, id, className = '', children }) {
  const [hasOpened, setHasOpened] = useState(Boolean(open))
  if (open && !hasOpened) setHasOpened(true)

  return (
    <div id={id} className={`animated-collapse ${className}`.trim()} data-open={Boolean(open)} aria-hidden={!open} inert={!open}>
      <div className="animated-collapse__clip">
        <div className="animated-collapse__content">{hasOpened && children}</div>
      </div>
    </div>
  )
}
