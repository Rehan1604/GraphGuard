import { useMemo, useState } from 'react'
import { addNote, changeStatus, fetchAlert } from '../api'
import { RULE_LABELS, STATUS_LABELS, formatMoney, formatTime } from '../format'
import { buildEvidenceGraph } from '../graphLayout'
import { useFetch } from '../hooks'

import FlowGraph from './FlowGraph'
import { Async, Card, PriorityBadge, StatusBadge, buttonClass, inputClass, primaryButtonClass } from './ui'

function describeEvent(e) {
  if (e.event === 'created') return 'Alert raised by the detection rules'
  if (e.event === 'evidence_grew') return 'New evidence added'
  if (e.event === 'status_changed' && e.from_status && e.to_status) {
    return `Status: ${STATUS_LABELS[e.from_status]} to ${STATUS_LABELS[e.to_status]}`
  }
  return e.event
}

export default function AlertDetail({ alertId, refreshKey, onChanged, onAsk }




) {
  const state = useFetch(() => fetchAlert(alertId), [alertId, refreshKey])
  const [analyst, setAnalyst] = useState('analyst')

  return (
    <Async state={state}>
      {(detail) => (
        <Body
          detail={detail}
          analyst={analyst}
          setAnalyst={setAnalyst}
          onAsk={onAsk}
          onSaved={() => {
            state.reload()
            onChanged()
          }}
        />
      )}
    </Async>
  )
}

function Body({ detail, analyst, setAnalyst,onAsk ,onSaved}





) {
  const graph = useMemo(() => buildEvidenceGraph(detail), [detail])
  const total = detail.contributions.reduce((sum, c) => sum + c.points, 0)

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-100">
          {RULE_LABELS[detail.rule]} <span className="text-slate-400">#{detail.id}</span>
        </h2>
        <PriorityBadge priority={detail.priority} />
        <StatusBadge status={detail.status} />
                {onAsk && (
          <button className={`${buttonClass} ml-auto`} onClick={() => onAsk(detail.id)}>
            Ask the assistant
          </button>
        )}
      </header>

      <p className="rounded-lg border border-navy-600 bg-navy-800 p-3 text-sm text-slate-300">
        This is a <strong>pattern flagged for human review</strong>. It is not proof of wrongdoing, and many
        legitimate activities look like this. {detail.summary}
      </p>

      {/* ---------- EVIDENCE: facts the system observed ---------- */}
      <Card title="Evidence: what the data shows">
        <FlowGraph key={`${detail.id}-${detail.evidence_count}`} {...graph} label={`Transfer graph for alert ${detail.id}`} />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Transactions supporting this alert</caption>
            <thead className="text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="py-1 pr-3 font-medium">Time</th>
                <th className="py-1 pr-3 font-medium">From</th>
                <th className="py-1 pr-3 font-medium">To</th>
                <th className="py-1 pr-3 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody>
              {detail.evidence.map((tx) => (
                <tr key={tx.id} className="border-t border-navy-700">
                  <td className="whitespace-nowrap py-1.5 pr-3 text-slate-300">{formatTime(tx.timestamp)}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs">{tx.source_account_id}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs">{tx.target_account_id}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatMoney(tx.amount, tx.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Why this score">
        <ul className="space-y-1 text-sm">
          {detail.contributions.map((c) => (
            <li key={c.reason} className="flex gap-3">
              <span className="w-10 shrink-0 text-right font-medium tabular-nums text-emerald-300">+{c.points}</span>
              <span className="text-slate-300">{c.reason}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 border-t border-navy-700 pt-2 text-sm text-slate-300">
          Total <strong className="tabular-nums">{Math.min(total, 100)}</strong> / 100. This is a review-priority
          score built from the rules above. It is not a probability of fraud.
        </p>
      </Card>

      <TriageCard detail={detail} />

      {/* ---------- WORKSPACE: opinions and decisions by people ---------- */}
      <Card title="Analyst workspace: opinions and decisions">
        <div className="mb-3 max-w-xs">
          <label htmlFor="analyst-name" className="mb-1 block text-xs text-slate-400">Your name</label>
          <input id="analyst-name" className={inputClass} value={analyst} onChange={(e) => setAnalyst(e.target.value)} maxLength={50} />
        </div>
        <StatusPanel detail={detail} analyst={analyst} onSaved={onSaved} />
        <hr className="my-4 border-navy-700" />
        <NotesPanel detail={detail} analyst={analyst} onSaved={onSaved} />
      </Card>

      <Card title="Investigation timeline">
        <ol className="space-y-3 border-l border-navy-600 pl-4">
          {[...detail.history].reverse().map((e) => (
            <li key={e.id} className="relative text-sm">
              <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" />
              <div className="text-slate-200">{describeEvent(e)}</div>
              <div className="text-xs text-slate-400">
                {e.actor} | {formatTime(e.created_at)}
              </div>
              {e.comment && <div className="mt-0.5 text-slate-300">{e.comment}</div>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}

function StatusPanel({ detail, analyst, onSaved }) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function move(status) {
    setBusy(true)
    setError(null)
    try {
      await changeStatus(detail.id, status, comment.trim(), analyst.trim() || 'analyst')
      setComment('')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the status')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <label htmlFor="status-comment" className="mb-1 block text-xs text-slate-400">
        Reason (required to escalate or dismiss)
      </label>
      <textarea
        id="status-comment"
        className={`${inputClass} min-h-16`}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        maxLength={1000}
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {detail.allowed_next_statuses.map((status) => {
          const needsReason = detail.comment_required_for.includes(status)
          return (
            <button
              key={status}
              className={status === 'in_review' ? primaryButtonClass : buttonClass}
              disabled={busy || (needsReason && comment.trim() === '')}
              onClick={() => void move(status)}
            >
              {status === 'in_review' && detail.status !== 'new' ? 'Reopen for review' : `Mark ${STATUS_LABELS[status].toLowerCase()}`}
            </button>
          )
        })}
        {detail.allowed_next_statuses.length === 0 && <span className="text-sm text-slate-400">No further moves available.</span>}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-amber-300">{error}</p>}
    </div>
  )
}

function NotesPanel({ detail, analyst, onSaved }) {
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await addNote(detail.id, analyst.trim() || 'analyst', body.trim())
      setBody('')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the note')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Notes</h3>
      {detail.notes.length === 0 && <p className="mb-2 text-sm text-slate-400">No notes yet.</p>}
      <ul className="mb-3 space-y-2">
        {detail.notes.map((n) => (
          <li key={n.id} className="rounded-lg border border-navy-700 bg-navy-800 p-2 text-sm">
            <div className="text-xs text-slate-400">{n.author} | {formatTime(n.created_at)}</div>
            <div className="whitespace-pre-wrap text-slate-200">{n.body}</div>
          </li>
        ))}
      </ul>
      <label htmlFor="new-note" className="mb-1 block text-xs text-slate-400">Add a note</label>
      <textarea id="new-note" className={`${inputClass} min-h-16`} value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} />
      <button className={`${buttonClass} mt-2`} disabled={busy || body.trim() === ''} onClick={() => void save()}>
        Save note
      </button>
      {error && <p role="alert" className="mt-2 text-sm text-amber-300">{error}</p>}
    </div>
  )
}

function TriageCard({ detail }) {
  if (detail.ml_score === null || detail.ml_score === undefined) {
    return (
      <Card title="ML triage">
        <p className="text-sm text-slate-400">
          No triage estimate for this alert (the model is switched off or was not available when it was raised).
          The rule score above is all there is.
        </p>
      </Card>
    )
  }
  const pct = Math.round(detail.ml_score * 100)
  return (
    <Card title="ML triage: does this look like a genuine pattern?">
      <p className="text-sm text-slate-300">
        A trained classifier estimates <strong className="tabular-nums">{pct}%</strong> that this alert is a genuine
        pattern rather than a benign look-alike (verdict:{' '}
        <strong>{detail.ml_verdict === 'likely_benign' ? 'likely benign' : 'likely genuine'}</strong>). It is trained
        on synthetic data and is an aid to review order, not a verdict about anyone.
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {(detail.ml_drivers ?? []).map((d) => (
          <li key={d.label} className="flex gap-3">
            <span className={`w-14 shrink-0 text-right font-medium tabular-nums ${d.effect >= 0 ? 'text-emerald-300' : 'text-amber-300'}`}>
              {d.effect >= 0 ? '+' : ''}{Math.round(d.effect * 100)}
            </span>
            <span className="text-slate-300">{d.label} ({d.direction} the estimate)</span>
          </li>
        ))}
      </ul>
      {detail.ml_model && <p className="mt-2 text-xs text-slate-500">Model: {detail.ml_model}</p>}
    </Card>
  )
}
