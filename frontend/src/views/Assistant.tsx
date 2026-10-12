import { useState } from 'react'
import { askAssistant, fetchAlerts, fetchAssistantStatus } from '../api'
import { Async, Card, ErrorBox, Spinner, buttonClass, inputClass, primaryButtonClass } from '../components/ui'
import { splitCitations } from '../citations'
import { RULE_LABELS } from '../format'
import { useFetch } from '../hooks'
import type { AssistantAnswer } from '../types'

const SUGGESTIONS = ['Why was this flagged?', 'What innocent explanations are there?', 'What should I check next?']

export default function Assistant({ version, selectedAlert }: { version: number; selectedAlert: number | null }) {
  const status = useFetch(fetchAssistantStatus, [])
  const alerts = useFetch(() => fetchAlerts({}), [version])
  const [alertId, setAlertId] = useState<number | null>(selectedAlert)
  const [question, setQuestion] = useState('')
  const [useAi, setUseAi] = useState(true)
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const chosen = alertId ?? alerts.data?.[0]?.id ?? null

  async function ask(text: string) {
    if (chosen === null || text.trim() === '') return
    setBusy(true)
    setError(null)
    setAnswer(null)
    try {
      setAnswer(await askAssistant(chosen, text.trim(), useAi))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant could not answer')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Investigation assistant">
        <Async state={status}>
          {(s) => (
            <div className="space-y-1 text-sm">
              {s.ai_configured ? (
                <p className="text-slate-200">AI provider: <strong>{s.provider} / {s.model}</strong></p>
              ) : (
                <p className="text-slate-200">
                  No AI provider is configured, so answers are <strong>rule-based summaries, not AI</strong>.
                  {s.problem && <span className="text-amber-300"> Problem: {s.problem}.</span>}
                </p>
              )}
              <p className="text-xs text-slate-400">{s.privacy}</p>
            </div>
          )}
        </Async>

        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
          <div>
            <label htmlFor="assistant-alert" className="mb-1 block text-xs text-slate-400">Alert</label>
            <select id="assistant-alert" className={inputClass} value={chosen ?? ''} onChange={(e) => setAlertId(Number(e.target.value))}>
              {(alerts.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>#{a.id} {RULE_LABELS[a.rule]} (score {a.risk_score}): {a.accounts.slice(0, 3).join(' > ')}</option>
              ))}
            </select>
          </div>
          <label className="flex items-end gap-2 pb-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={useAi && !!status.data?.ai_configured}
              disabled={!status.data?.ai_configured}
              onChange={(e) => setUseAi(e.target.checked)}
            />
            Use the AI provider
          </label>
        </div>

        <div className="mt-3">
          <label htmlFor="assistant-question" className="mb-1 block text-xs text-slate-400">
            Your question (do not type personal details; account ids are replaced by aliases, nothing else is protected)
          </label>
          <textarea id="assistant-question" className={`${inputClass} min-h-16`} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} />
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <button className={primaryButtonClass} disabled={busy || chosen === null || question.trim() === ''} onClick={() => void ask(question)}>
            Ask
          </button>
          {SUGGESTIONS.map((q) => (
            <button key={q} className={buttonClass} disabled={busy || chosen === null} onClick={() => { setQuestion(q); void ask(q) }}>
              {q}
            </button>
          ))}
        </div>
      </Card>

      {busy && <Spinner label="Working on it" />}
      {error && <ErrorBox message={error} />}
      {answer && <Answer answer={answer} />}
    </div>
  )
}

function Answer({ answer }: { answer: AssistantAnswer }) {
  const { explanation: e } = answer
  const lookup = new Map<string, string>([
    ...answer.facts.map((f) => [f.id, f.text] as [string, string]),
    ...answer.guidance.map((g) => [g.id, `${g.title}: ${g.section}`] as [string, string]),
  ])

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-300">{answer.disclaimer}</p>

      <Card title="1. Verified facts (computed from the transaction database)">
        <ul className="space-y-1.5 text-sm">
          {answer.facts.map((f) => (
            <li key={f.id} id={`src-${f.id}`} className="flex gap-2">
              <span className="w-8 shrink-0 font-mono text-xs text-emerald-300">{f.id}</span>
              <span className="text-slate-200">{f.text}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="2. Retrieved guidance (general library, not about these accounts)">
        <ul className="space-y-2 text-sm">
          {answer.guidance.map((g) => (
            <li key={g.id} id={`src-${g.id}`} className="rounded-lg border border-navy-700 bg-navy-800 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-sky-300">{g.id}</span>
                <span className="text-slate-100">{g.title}: {g.section}</span>
                <span className="ml-auto text-xs text-slate-400">
                  {g.source} | {g.via === 'similarity' ? `matched your question (score ${g.score.toFixed(2)})` : 'standard guidance for this pattern'}
                </span>
              </div>
              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-slate-400">Show the passage</summary>
                <p className="mt-1 whitespace-pre-wrap text-slate-300">{g.text}</p>
              </details>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="3. Explanation (advisory)">
        <div className="mb-3 flex flex-wrap items-start gap-2">
          <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${e.mode === 'ai' ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-slate-600 text-slate-300'}`}>
            {e.mode === 'ai' ? 'AI-generated' : 'Rule-based, not AI'}
          </span>
          <p className="min-w-0 flex-1 text-xs text-slate-400">{e.label}</p>
        </div>
        {e.warnings.length > 0 && (
          <ul role="alert" className="mb-3 space-y-1 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-sm text-amber-200">
            {e.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        )}
        <div className="space-y-3">
          {e.sections.map((s) => (
            <section key={s.heading}>
              <h3 className="mb-1 text-sm font-semibold text-slate-100">{s.heading}</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm text-slate-200">
                {s.items.map((item, i) => (
                  <li key={i}><CitedText text={item} lookup={lookup} /></li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        {e.privacy_note && <p className="mt-3 border-t border-navy-700 pt-2 text-xs text-slate-400">{e.privacy_note}</p>}
      </Card>
    </div>
  )
}

/** Plain text with citation markers drawn as small badges. The text is never treated as HTML. */
function CitedText({ text, lookup }: { text: string; lookup: Map<string, string> }) {
  return (
    <>
      {splitCitations(text).map((seg, i) =>
        seg.kind === 'text' ? (
          <span key={i}>{seg.value}</span>
        ) : (
          <span key={i}>
            {seg.ids.map((id) => (
              <a
                key={id}
                href={`#src-${id}`}
                title={lookup.get(id) ?? id}
                aria-label={`Source ${id}`}
                className="mx-0.5 rounded border border-navy-600 bg-navy-800 px-1 font-mono text-[10px] text-emerald-300 no-underline hover:bg-navy-700"
              >
                {id}
              </a>
            ))}
          </span>
        ),
      )}
    </>
  )
}