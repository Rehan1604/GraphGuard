import { useEffect, useState } from 'react'
import { fetchAlerts } from '../api'
import AlertDetail from '../components/AlertDetail'
import { Async, Empty, PriorityBadge, StatusBadge, inputClass } from '../components/ui'
import { RULE_LABELS, STATUS_LABELS, formatTime, matchesSearch } from '../format'
import { useFetch } from '../hooks'
import type { Priority, Rule, Status } from '../types'

export default function Alerts({ version, selectedId, onSelect, search, onSearch, onChanged,onAsk }: {
  version: number
  selectedId: number | null
  onSelect: (id: number) => void
  search: string
  onSearch: (text: string) => void
  onChanged: () => void
  onAsk: (id: number) => void
}) {
  const [status, setStatus] = useState<Status | ''>('')
  const [priority, setPriority] = useState<Priority | ''>('')
  const [rule, setRule] = useState<Rule | ''>('')
  const state = useFetch(() => fetchAlerts({ status, priority, rule }), [status, priority, rule, version])

  const visible = (state.data ?? []).filter((a) => matchesSearch(a, search))

  // Open the most urgent alert automatically the first time the list loads.
  useEffect(() => {
    if (selectedId === null && visible.length > 0) onSelect(visible[0].id)
  }, [selectedId, visible, onSelect])

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-3">
        <div className="space-y-2 rounded-xl border border-navy-700 bg-navy-900 p-3">
          <label htmlFor="alert-search" className="sr-only">Search alerts</label>
          <input
            id="alert-search"
            className={inputClass}
            placeholder="Search by account, rule or #id"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
          />
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label htmlFor="f-status" className="mb-1 block text-xs text-slate-400">Status</label>
              <select id="f-status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as Status | '')}>
                <option value="">All</option>
                {(Object.keys(STATUS_LABELS) as Status[]).map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="f-priority" className="mb-1 block text-xs text-slate-400">Priority</label>
              <select id="f-priority" className={inputClass} value={priority} onChange={(e) => setPriority(e.target.value as Priority | '')}>
                <option value="">All</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div>
              <label htmlFor="f-rule" className="mb-1 block text-xs text-slate-400">Pattern</label>
              <select id="f-rule" className={inputClass} value={rule} onChange={(e) => setRule(e.target.value as Rule | '')}>
                <option value="">All</option>
                {(Object.keys(RULE_LABELS) as Rule[]).map((r) => <option key={r} value={r}>{RULE_LABELS[r]}</option>)}
              </select>
            </div>
          </div>
        </div>

        <Async state={state}>
          {(all) => (
            <>
              <p className="text-xs text-slate-400">Showing {visible.length} of {all.length} alerts, highest score first</p>
              {visible.length === 0 ? (
                <Empty title="No alerts match">Clear the filters, or start the simulation to generate activity.</Empty>
              ) : (
                <ul className="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
                  {visible.map((a) => (
                    <li key={a.id}>
                      <button
                        onClick={() => onSelect(a.id)}
                        aria-pressed={a.id === selectedId}
                        className={`w-full rounded-lg border p-3 text-left ${
                          a.id === selectedId ? 'border-emerald-500/60 bg-navy-800' : 'border-navy-700 bg-navy-900 hover:border-navy-600'
                        }`}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-slate-100">{RULE_LABELS[a.rule]}</span>
                          <PriorityBadge priority={a.priority} />
                          <span className="ml-auto text-sm tabular-nums text-slate-300">{a.risk_score}</span>
                        </div>
                        <div className="mt-1 truncate font-mono text-xs text-slate-400">#{a.id} {a.accounts.slice(0, 3).join(' > ')}</div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
                          <StatusBadge status={a.status} />
                          <span>{a.evidence_count} transfers</span>
                          <span className="ml-auto">{formatTime(a.window_start).slice(0, 16)}</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Async>
      </div>

      <div className="min-w-0">
        {selectedId === null ? (
          <Empty title="Select an alert">Pick one from the list to inspect its evidence.</Empty>
        ) : (
          <AlertDetail key={selectedId} alertId={selectedId} refreshKey={version} onChanged={onChanged} onAsk={onAsk} />
        )}
      </div>
    </div>
  )
}