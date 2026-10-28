import { useEffect, useRef } from 'react'

// Plain-text only: the body is split on the evidence substring and the match wrapped in <mark>.
// React escapes every piece, so email content can never inject HTML.
export function HighlightedText({ text, evidence }: { text: string; evidence?: string | null }) {
  const markRef = useRef<HTMLElement>(null)
  const index = evidence ? text.indexOf(evidence) : -1

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [text, evidence])

  if (!evidence || index < 0) return <pre className="email-body">{text}</pre>
  return (
    <pre className="email-body">
      {text.slice(0, index)}
      <mark ref={markRef}>{evidence}</mark>
      {text.slice(index + evidence.length)}
    </pre>
  )
}
