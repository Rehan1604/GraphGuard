import { useState } from 'react'
import { fetchDetectionConfig, fetchSimulation, previewDetection, scanAlerts, simulationAction } from '../api'
import { Async, Card, ErrorBox, PriorityBadge, buttonClass, inputClass, primaryButtonClass } from '../components/ui'
import { RULE_LABELS } from '../format'
import { useFetch } from '../hooks'


const FIELDS = [
  { key: 'pass_through_ratio', label: 'Pass-through ratio', step: 0.05, help: 'Smallest share of incoming money that counts as "forwarded"' },
  { key: 'chain_hop_window_minutes', label: 'Chain hop window (min)', step: 1, help: 'Max minutes between money arriving and leaving' },
  { key: 'min_chain_hops', label: 'Min chain hops', step: 1, help: 'Shortest chain worth flagging' },
  { key: 'max_chain_hops', label: 'Max chain hops', step: 1, help: 'Longest chain we follow' },
  { key: 'cycle_window_minutes', label: 'Cycle window (min)', step: 5, help: 'Money must return within this time' },
  { key: 'min_cycle_length', label: 'Min cycle length', step: 1, help: 'Fewest transfers in a loop' },
  { key: 'max_cycle_length', label: 'Max cycle length', step: 1, help: 'Most transfers in a loop' },
  { key: 'cycle_min_amount_ratio', label: 'Loop amount ratio', step: 0.05, help: 'Smallest/largest transfer in a loop; lower than this is treated as coincidence' },
  { key: 'burst_window_minutes', label: 'Burst window (min)', step: 1, help: 'Time window for bursts and many-counterparty checks' },
  { key: 'burst_min_transactions', label: 'Burst size', step: 1, help: 'Transfers inside the window that count as a burst' },
  { key: 'fan_min_counterparties', label: 'Counterparties', step: 1, help: 'Different accounts inside the window that count as a crowd' },
]

export default function Settings({ version, onChanged }) {
  return (
    <div className="space-y-4">
      <SimulationPanel version={version} onChanged={onChanged} />
      <DetectionPanel onChanged={onChanged} />
    </div>
  )
}

function SimulationPanel({ version, onChanged }) {
  const sim = useFetch(fetchSimulation, [version])
  const [options, setOptions] = useState({ events_per_second: 2, seed: 42, duplicate_rate: 0.05 })
  const [error, setError] = useState(null)

  async function act(action) {
    if (action === 'reset' && !window.confirm('Delete all simulated accounts, transactions and alerts? Your own data is not touched.')) return
    setError(null)
    try {
      await simulationAction(action, action === 'start' ? options : undefined)
      sim.reload()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    }
  }

  return (
    <Card title="Simulation">
      <Async state={sim}>
        {(s) => (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="sim-eps" className="mb-1 block text-xs text-slate-400">Events per second (0.1 to 20)</label>
                <input id="sim-eps" type="number" min={0.1} max={20} step={0.5} className={inputClass} value={options.events_per_second}
                  onChange={(e) => setOptions({ ...options, events_per_second: Number(e.target.value) })} disabled={s.status !== 'stopped'} />
              </div>
              <div>
                <label htmlFor="sim-seed" className="mb-1 block text-xs text-slate-400">Seed (same seed, same story)</label>
                <input id="sim-seed" type="number" className={inputClass} value={options.seed}
                  onChange={(e) => setOptions({ ...options, seed: Number(e.target.value) })} disabled={s.status !== 'stopped'} />
              </div>
              <div>
                <label htmlFor="sim-dup" className="mb-1 block text-xs text-slate-400">Duplicate rate (0 to 0.5)</label>
                <input id="sim-dup" type="number" min={0} max={0.5} step={0.05} className={inputClass} value={options.duplicate_rate}
                  onChange={(e) => setOptions({ ...options, duplicate_rate: Number(e.target.value) })} disabled={s.status !== 'stopped'} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className={primaryButtonClass} disabled={s.status !== 'stopped'} onClick={() => void act('start')}>Start</button>
              <button className={buttonClass} disabled={s.status !== 'running'} onClick={() => void act('pause')}>Pause</button>
              <button className={buttonClass} disabled={s.status !== 'paused'} onClick={() => void act('resume')}>Resume</button>
              <button className={buttonClass} onClick={() => void act('reset')}>Reset simulated data</button>
              <span className="ml-2 text-sm capitalize text-slate-300">Status: {s.status}</span>
            </div>
            <p className="text-xs text-slate-400">
              After a server restart the simulator is stopped but its data is still stored. Starting again with the same
              seed replays the same transactions, which are recognised as duplicates. Reset first for a fresh run.
            </p>
            {error && <ErrorBox message={error} />}
          </div>
        )}
      </Async>
    </Card>
  )
}

function DetectionPanel({ onChanged }) {
  const defaults = useFetch(fetchDetectionConfig, [])
  const [edited, setEdited] = useState(null)
  const [preview, setPreview] = useState(null)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Show the server's defaults until the user edits something.
  const fromServer = defaults.data ? { ...defaults.data, pass_through_ratio: Number(defaults.data.pass_through_ratio), cycle_min_amount_ratio: Number(defaults.data.cycle_min_amount_ratio) } : null
  const config = edited ?? fromServer
  const setConfig = setEdited

  async function run(kind) {
    if (!config) return
    setBusy(true)
    setError(null)
    try {
      if (kind === 'preview') {
        setPreview(await previewDetection(config))
      } else {
        setSaved(await scanAlerts(config))
        onChanged()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Detection thresholds">
      <Async state={defaults}>
        {() =>
          config && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {FIELDS.map((f) => (
                  <div key={f.key}>
                    <label htmlFor={`cfg-${f.key}`} className="mb-1 block text-xs text-slate-300">{f.label}</label>
                    <input id={`cfg-${f.key}`} type="number" step={f.step} className={inputClass} value={config[f.key]}
                      onChange={(e) => setConfig({ ...config, [f.key]: Number(e.target.value) })} />
                    <p className="mt-0.5 text-xs text-slate-500">{f.help}</p>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <button className={buttonClass} disabled={busy} onClick={() => void run('preview')}>Preview (does not save)</button>
                <button className={primaryButtonClass} disabled={busy} onClick={() => void run('scan')}>Scan and save alerts</button>
                <button className={buttonClass} onClick={() => setEdited(null)}>Restore defaults</button>
              </div>
              {error && <ErrorBox message={error} />}
              {saved && (
                <p className="text-sm text-emerald-300">
                  Saved: {saved.created} new, {saved.updated} updated, {saved.unchanged} unchanged ({saved.findings} patterns found).
                </p>
              )}
              {preview && (
                <div className="rounded-lg border border-navy-700 bg-navy-800 p-3 text-sm">
                  <p className="mb-2 text-slate-300">
                    Preview over {preview.transactions_analyzed} transactions: <strong>{preview.findings.length}</strong> patterns.
                  </p>
                  <p className="mb-2 text-xs text-slate-400">
                    {(Object.keys(RULE_LABELS) ).map((r) => `${RULE_LABELS[r]}: ${preview.findings.filter((f) => f.rule === r).length}`).join(' | ')}
                  </p>
                  <ul className="space-y-1">
                    {preview.findings.slice(0, 8).map((f, i) => (
                      <li key={i} className="flex items-center gap-2">
                        <PriorityBadge priority={f.priority} />
                        <span className="text-slate-200">{RULE_LABELS[f.rule]}</span>
                        <span className="truncate font-mono text-xs text-slate-400">{f.accounts.slice(0, 3).join(' > ')}</span>
                        <span className="ml-auto tabular-nums">{f.risk_score}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        }
      </Async>
    </Card>
  )
}