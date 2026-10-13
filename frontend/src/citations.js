 

const CITATION = /\[((?:[FKC]\d+)(?:\s*,\s*[FKC]\d+)*)\]/g

/** Cut a sentence into plain text and citation markers like [F2] or [F1, K3], so each marker
 *  can be drawn as a badge. Nothing here ever becomes HTML. */
export function splitCitations(text) {
  const out = []
  let last = 0
  for (const match of text.matchAll(CITATION)) {
    const start = match.index ?? 0
    if (start > last) out.push({ kind: 'text', value: text.slice(last, start) })
    out.push({ kind: 'cite', ids: match[1].split(',').map((s) => s.trim()) })
    last = start + match[0].length
  }
  if (last < text.length) out.push({ kind: 'text', value: text.slice(last) })
  return out
}