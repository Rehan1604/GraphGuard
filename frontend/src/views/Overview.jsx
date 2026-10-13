import { fetchAlerts, fetchMetrics, fetchSimulation, fetchStats } from '../api'
import { Async, Bar, Card, Empty, PriorityBadge, Stat, StatusBadge } from '../components/ui'
import { RULE_LABELS, formatMoney, timeOnly } from '../format'
import { useFetch } from '../hooks'


export default function Overview({ version, live, onOpenAlert }



) {
  const stats = useFetch(fetchStats, [version])
  const metrics = useFetch(fetchMetrics, [version])
  const alerts = useFetch(() => fetchAlerts({}), [version])
  const sim = useFetch(fetchSimulation, [version])

  return (
    <div className="space-y-4">
      <Async state={stats}>
        {(s) => (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Accounts" value={s.accounts} />
            <Stat label="Transfers" value={s.transactions} hint="Edges in the account graph" />
            <Stat label="Open alerts" value={s.alerts_open} hint="New or in review" />
            <Stat label="All alerts" value={s.alerts_total} />
          </div>
        )}
      </Async>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Alerts needing attention">
          <Async state={alerts}>
            {(list) => {
              const top = list.filter((a) => a.status !== 'dismissed').slice(0, 5)
              if (top.length === 0) {
                return <Empty title="No open alerts">Start the simulation, or load data and run a scan in Settings.</Empty>
              }
              return (
                <ul className="space-y-2">
                  {top.map((a) => (
                    <li key={a.id}>
                      <button
                        onClick={() => onOpenAlert(a.id)}
                        className="w-full rounded-lg border border-navy-700 bg-navy-800 p-3 text-left hover:border-emerald-500/50"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-slate-100">{RULE_LABELS[a.rule]}</span>
                          <PriorityBadge priority={a.priority} />
                          <StatusBadge status={a.status} />
                          <span className="ml-auto text-sm tabular-nums text-slate-300">score {a.risk_score}</span>
                        </div>
                        <div className="mt-1 truncate font-mono text-xs text-slate-400">{a.accounts.slice(0, 4).join(' > ')}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }}
          </Async>
        </Card>

        <Card title="Alerts by priority">
          <Async state={metrics}>
            {(m) => {
              const max = Math.max(...Object.values(m.by_priority), 0)
              return (
                <div className="space-y-2">
                  <Bar label="High" value={m.by_priority.high} max={max} />
                  <Bar label="Medium" value={m.by_priority.medium} max={max} />
                  <Bar label="Low" value={m.by_priority.low} max={max} />
                </div>
              )
            }}
          </Async>
        </Card>

        <Card title="Live transactions">
          {live.recent.length === 0 ? (
            <Empty title="Nothing yet">Press Start simulation in the top bar to watch transfers arrive.</Empty>
          ) : (
            <ul className="space-y-1 font-mono text-xs">
              {live.recent.slice(0, 12).map((t) => (
                <li key={t.id} className="flex gap-2 border-b border-navy-700 py-1">
                  <span className="text-slate-400">{timeOnly(t.timestamp)}</span>
                  <span className="truncate text-slate-200">{t.source_account_id} &gt; {t.target_account_id}</span>
                  <span className="ml-auto tabular-nums text-slate-300">{formatMoney(t.amount, t.currency)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Simulation">
          <Async state={sim}>
            {(s) => (
              <dl className="grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-slate-400">Status</dt><dd className="capitalize">{s.status}</dd>
                <dt className="text-slate-400">Events sent</dt><dd className="tabular-nums">{s.events_emitted}</dd>
                <dt className="text-slate-400">Transactions stored</dt><dd className="tabular-nums">{s.transactions_created}</dd>
                <dt className="text-slate-400">Duplicates ignored</dt><dd className="tabular-nums">{s.duplicates_ignored}</dd>
                <dt className="text-slate-400">Errors</dt><dd className="tabular-nums">{s.errors}</dd>
              </dl>
            )}
          </Async>
        </Card>
      </div>
    </div>
  )
}