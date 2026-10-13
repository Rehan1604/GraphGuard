

export const RULE_LABELS = {
  pass_through_chain: 'Pass-through chain',
  cycle: 'Circular flow',
  burst: 'Transfer burst',
  fan: 'Many counterparties',
}

export const STATUS_LABELS = {
  new: 'New',
  in_review: 'In review',
  escalated: 'Escalated',
  dismissed: 'Dismissed',
}

export function formatMoney(amount, currency = 'USD') {
  const n = Number(amount)
  if (!Number.isFinite(n)) return `${amount} ${currency}`
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n)
  } catch {
    return `${n.toFixed(2)} ${currency}` // unknown currency code
  }
}

/** Always shown in UTC so everyone looking at the same alert sees the same time. */
export function formatTime(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toISOString().slice(0, 19).replace('T', ' ')} UTC`
}

export function timeOnly(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(11, 19)
}

export function matchesSearch(alert, query) {
  const q = query.trim().replace(/^#/, '').toLowerCase()
  if (!q) return true
  const haystack = [String(alert.id), alert.rule, RULE_LABELS[alert.rule] ?? '', alert.summary, ...alert.accounts]
  return haystack.some((text) => text.toLowerCase().includes(q))
}
/** "59 / 82 (72.0%)", or "n/a" when the fraction is undefined. The denominator is always shown. */
export function formatRate(r) {
  const pct = r.value === null ? 'n/a' : `${(r.value * 100).toFixed(1)}%`
  return `${r.numerator} / ${r.denominator} (${pct})`
}








export function comparisonRows(g, b) {
  const f1 = (r) => (r.f1 === null ? 'n/a' : r.f1.toFixed(3))
  const fp = (r) =>
    `${r.false_positive_findings} (${r.false_positives_from_benign_lookalikes} look-alikes, ${r.false_positives_from_near_misses} near-misses, ` +
    `${r.false_positives_mixed_overlap} partial overlap, ${r.false_positives_background_only} pure background)`
  return [
    { label: 'Alerts to read', help: 'Findings an analyst would have to look at', graph: String(g.findings), baseline: String(b.findings) },
    { label: 'Precision', help: 'Findings that match a planted pattern / all findings', graph: formatRate(g.precision), baseline: formatRate(b.precision) },
    { label: 'Recall (strict)', help: 'Planted patterns found / planted patterns. A finding must cover half the pattern', graph: formatRate(g.recall), baseline: formatRate(b.recall) },
    { label: 'Recall (lenient)', help: 'Same, but any overlap with the pattern counts as found', graph: formatRate(g.recall_lenient), baseline: formatRate(b.recall_lenient) },
    { label: 'F1', help: 'One number that balances precision and recall', graph: f1(g), baseline: f1(b) },
    { label: 'Look-alikes flagged', help: 'Legitimate activity shaped like a pattern. Any pattern rule will flag these', graph: formatRate(g.benign_lookalikes_flagged), baseline: formatRate(b.benign_lookalikes_flagged) },
    { label: 'Near-misses flagged', help: 'Activity just outside the thresholds', graph: formatRate(g.near_misses_flagged), baseline: formatRate(b.near_misses_flagged) },
    { label: 'False-positive findings', help: 'Where the wrong alerts came from', graph: fp(g), baseline: fp(b) },
  ]
}