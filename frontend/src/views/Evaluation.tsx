import { useState } from 'react'
import { fetchEvaluation, fetchMetrics } from '../api'
import { Async, Bar, Card, Empty, ErrorBox, Spinner, buttonClass, inputClass, primaryButtonClass } from '../components/ui'
import { RULE_LABELS, STATUS_LABELS, comparisonRows, formatRate } from '../format'
import { useFetch } from '../hooks'
import type { DelayStats, EvaluationReport, Rule, Status, Sweep } from '../types'

const KIND_LABELS: Record<string, string> = { ...RULE_LABELS }

export default function Evaluation({ version }: { version: number }) {
  const state = useFetch(fetchMetrics, [version])

  return (
    <div className="space-y-4">
      <Benchmark />

      <Async state={state}>
        {(m) => {
          const ruleMax = Math.max(...Object.values(m.by_rule), 0)
          const statusMax = Math.max(...Object.values(m.by_status), 0)
          return (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title={`Your alerts by pattern (${m.total} total)`}>
                <div className="space-y-2">
                  {(Object.keys(RULE_LABELS) as Rule[]).map((r) => (
                    <Bar key={r} label={RULE_LABELS[r]} value={m.by_rule[r]} max={ruleMax} />
                  ))}
                </div>
              </Card>
              <Card title="Your alerts by review status">
                <div className="space-y-2">
                  {(Object.keys(STATUS_LABELS) as Status[]).map((s) => (
                    <Bar key={s} label={STATUS_LABELS[s]} value={m.by_status[s]} max={statusMax} />
                  ))}
                </div>
                <p className="mt-3 text-xs text-slate-400">
                  These counts reflect analyst decisions. A dismissed alert is a judgment call, not proof that the
                  pattern was harmless, so this is not a false-positive rate.
                </p>
              </Card>
            </div>
          )
        }}
      </Async>
    </div>
  )
}

function Benchmark() {
  const [dataset, setDataset] = useState<'benchmark' | 'simulator'>('benchmark')
  const [seed, setSeed] = useState(42)
  const [events, setEvents] = useState(240)
  const [report, setReport] = useState<EvaluationReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setReport(await fetchEvaluation(dataset, seed, events))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The evaluation failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Synthetic benchmark: precision, recall and F1">
      <p role="note" className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
        This measures how well the rules find patterns <strong>that we planted</strong> in made-up data. It cannot tell
        you how accurate the system would be on real banking activity.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="bm-dataset" className="mb-1 block text-xs text-slate-400">Dataset</label>
          <select id="bm-dataset" className={`${inputClass} w-64`} value={dataset} onChange={(e) => setDataset(e.target.value as 'benchmark' | 'simulator')}>
            <option value="benchmark">Designed benchmark (with near-misses and look-alikes)</option>
            <option value="simulator">Live simulator stream (planted patterns only)</option>
          </select>
        </div>
        <div>
          <label htmlFor="bm-seed" className="mb-1 block text-xs text-slate-400">Seed</label>
          <input id="bm-seed" type="number" min={0} className={`${inputClass} w-28`} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </div>
        {dataset === 'simulator' && (
          <div>
            <label htmlFor="bm-events" className="mb-1 block text-xs text-slate-400">Events (50 to 2000)</label>
            <input id="bm-events" type="number" min={50} max={2000} className={`${inputClass} w-28`} value={events} onChange={(e) => setEvents(Number(e.target.value))} />
          </div>
        )}
        <button className={primaryButtonClass} disabled={busy} onClick={() => void run()}>Run benchmark</button>
      </div>

      <div className="mt-4">
        {busy && <Spinner label="Running the benchmark (a few seconds)" />}
        {error && <ErrorBox message={error} />}
        {!busy && !error && !report && (
          <Empty title="Not run yet">
            Press Run benchmark. The same seed always gives the same numbers, so you can reproduce a result exactly.
          </Empty>
        )}
        {!busy && report && <Results report={report} />}
      </div>
    </Card>
  )
}

function Results({ report: r }: { report: EvaluationReport }) {
  const d = r.dataset
  const rows = comparisonRows(r.graph, r.baseline)
  const c = r.graph.confusion
  const kinds = Object.keys(r.graph.per_kind_recall)

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-300">
        {d.name === 'benchmark' ? 'Designed benchmark' : 'Simulator stream'}, seed {d.seed}: {d.transactions} transactions
        ({d.background_transactions} ordinary background). Labelled episodes:{' '}
        {Object.entries(d.episodes_by_role).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ')}.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Graph engine compared with a simple transaction-rule baseline</caption>
          <thead className="text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">Measure</th>
              <th scope="col" className="py-1 pr-3 font-medium">Graph engine</th>
              <th scope="col" className="py-1 font-medium">Baseline (no graph)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-navy-700 align-top">
                <th scope="row" className="py-2 pr-3 text-left font-medium text-slate-200">
                  {row.label}
                  <span className="block text-xs font-normal text-slate-400">{row.help}</span>
                </th>
                <td className="py-2 pr-3 tabular-nums text-slate-100">{row.graph}</td>
                <td className="py-2 tabular-nums text-slate-100">{row.baseline}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Recall for each kind of pattern</h3>
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-400">
              <tr><th scope="col" className="text-left font-medium">Pattern</th><th scope="col" className="text-left font-medium">Graph</th><th scope="col" className="text-left font-medium">Baseline</th></tr>
            </thead>
            <tbody>
              {kinds.map((k) => (
                <tr key={k} className="border-t border-navy-700">
                  <th scope="row" className="py-1 text-left font-normal text-slate-300">{KIND_LABELS[k] ?? k}</th>
                  <td className="tabular-nums">{formatRate(r.graph.per_kind_recall[k])}</td>
                  <td className="tabular-nums">{formatRate(r.baseline.per_kind_recall[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Confusion matrix (graph engine, labelled episodes)</h3>
          <table className="w-full text-center text-sm">
            <thead className="text-xs text-slate-400">
              <tr><td /><th scope="col" className="font-medium">Flagged</th><th scope="col" className="font-medium">Not flagged</th></tr>
            </thead>
            <tbody>
              <tr className="border-t border-navy-700"><th scope="row" className="py-2 text-left font-normal text-slate-300">Planted pattern</th><td className="tabular-nums text-emerald-300">{c.true_positive} <span className="text-xs text-slate-400">found</span></td><td className="tabular-nums text-amber-300">{c.false_negative} <span className="text-xs text-slate-400">missed</span></td></tr>
              <tr className="border-t border-navy-700"><th scope="row" className="py-2 text-left font-normal text-slate-300">Near-miss or look-alike</th><td className="tabular-nums text-amber-300">{c.false_positive} <span className="text-xs text-slate-400">false alarm</span></td><td className="tabular-nums text-emerald-300">{c.true_negative} <span className="text-xs text-slate-400">left alone</span></td></tr>
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-400">
            Counted over labelled episodes only. Findings that touch no labelled episode have no row here, so they are
            reported separately above.
          </p>
        </div>
      </div>

      <DelayBlock delay={r.delay} />
      {r.sweeps.length > 0 && r.sweeps.map((s) => <SweepTable key={s.parameter} sweep={s} />)}

      <p className="text-sm text-slate-300">
        <strong>Negative control:</strong> {r.negative_control.description} Recall fell to {formatRate(r.negative_control.recall)}.
        If that number were high, the scoring itself would be broken.
      </p>

      <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
        {r.caveats.map((text) => <li key={text}>{text}</li>)}
      </ul>
      <p className="text-xs text-slate-500">
        Speed on this machine while replaying the stream: {r.timing.milliseconds_per_transaction} ms per transaction (not part of the reproducible results).
      </p>
      <button className={buttonClass} onClick={() => window.print()}>Print this page</button>
    </div>
  )
}

function DelayBlock({ delay: d }: { delay: DelayStats }) {
  if (d.detected === 0) return <p className="text-sm text-slate-400">No planted pattern was flagged while streaming, so there is no delay to report.</p>
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Detection delay (event time)</h3>
      <p className="text-sm text-slate-300">
        Of {d.detected} patterns found while replaying transactions one at a time, the median alert came{' '}
        <strong>{d.median_minutes_from_first_transfer} min</strong> after the pattern's first transfer (slowest: {d.max_minutes_from_first_transfer} min).
        Relative to the pattern's last transfer the median is {d.median_minutes_after_last_transfer} min; a negative number
        means the alert came before the pattern finished. {formatRate(d.flagged_before_pattern_finished)} were flagged early.
      </p>
      <p className="mt-1 text-xs text-slate-400">
        Median by pattern: {Object.entries(d.median_by_kind).map(([k, v]) => `${KIND_LABELS[k] ?? k} ${v} min`).join(', ')}.
        Measured with the timestamps in the data, not computer speed.
      </p>
    </div>
  )
}

function SweepTable({ sweep }: { sweep: Sweep }) {
  const pct = (x: number | null) => (x === null ? 'n/a' : `${(x * 100).toFixed(1)}%`)
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Threshold sweep: {sweep.parameter}</h3>
      <p className="mb-1 text-xs text-slate-400">{sweep.description}. Only this threshold changes; everything else stays at its default.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-slate-400">
            <tr>
              <th scope="col" className="text-left font-medium">Value</th><th scope="col" className="text-left font-medium">Alerts</th>
              <th scope="col" className="text-left font-medium">Precision</th><th scope="col" className="text-left font-medium">Recall</th>
            </tr>
          </thead>
          <tbody>
            {sweep.points.map((p) => (
              <tr key={p.value} className={`border-t border-navy-700 ${p.value === sweep.default ? 'bg-navy-800' : ''}`}>
                <th scope="row" className="py-1 text-left font-normal text-slate-200">{p.value}{p.value === sweep.default && <span className="ml-2 text-xs text-emerald-300">default</span>}</th>
                <td className="tabular-nums">{p.findings}</td><td className="tabular-nums">{pct(p.precision)}</td><td className="tabular-nums">{pct(p.recall)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}