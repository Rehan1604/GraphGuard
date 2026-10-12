import { useCallback, useState } from 'react'
import { simulationAction } from './api'
import { buttonClass, primaryButtonClass } from './components/ui'
import { useLiveFeed } from './live'
import Alerts from './views/Alerts'
import Assistant from './views/Assistant'
import Evaluation from './views/Evaluation'
import Network from './views/Network'
import Overview from './views/Overview'
import Settings from './views/Settings'

type View = 'overview' | 'alerts' | 'network' | 'evaluation' | 'assistant' | 'settings'

const NAV: { id: View; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'network', label: 'Network' },
  { id: 'evaluation', label: 'Evaluation' },
  { id: 'assistant', label: 'Assistant' },
  { id: 'settings', label: 'Settings' },
]

export default function App() {
  const live = useLiveFeed()
  const [view, setView] = useState<View>('overview')
  const [selectedAlert, setSelectedAlert] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [manual, setManual] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)

  // Screens refetch whenever live events arrive (at most once a second) or the user changes something.
  const version = live.dataVersion + manual
  const bump = useCallback(() => setManual((m) => m + 1), [])

  const status = live.simulation?.status ?? 'stopped'

  async function toggleSimulation() {
    setActionError(null)
    try {
      if (status === 'stopped') await simulationAction('start', { events_per_second: 2, seed: 42, duplicate_rate: 0.05 })
      else if (status === 'running') await simulationAction('pause')
      else if (status === 'paused') await simulationAction('resume')
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Action failed')
    }
  }

  return (
    <div className="min-h-screen md:flex">
      <nav aria-label="Main" className="shrink-0 border-b border-navy-700 bg-navy-900 p-3 md:min-h-screen md:w-52 md:border-b-0 md:border-r">
        <div className="mb-3 px-2">
          <div className="text-lg font-semibold tracking-tight text-slate-100">GraphGuard</div>
          <div className="text-xs text-slate-400">Synthetic data only</div>
        </div>
        <ul className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => setView(item.id)}
                aria-current={view === item.id ? 'page' : undefined}
                className={`w-full whitespace-nowrap rounded-md px-3 py-2 text-left text-sm ${
                  view === item.id ? 'bg-emerald-500/15 text-emerald-200' : 'text-slate-300 hover:bg-navy-800'
                }`}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center gap-3 border-b border-navy-700 px-4 py-3">
          <h1 className="text-base font-semibold text-slate-100">{NAV.find((n) => n.id === view)?.label}</h1>
          <span className="text-xs text-slate-400">Patterns for review, not accusations</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2.5 py-0.5 text-xs ${live.connected ? 'border-emerald-500/40 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
              {live.connected ? 'Live' : 'Reconnecting...'}
            </span>
            <span className="rounded-full border border-navy-600 px-2.5 py-0.5 text-xs capitalize text-slate-300">Simulation: {status}</span>
            {status === 'error' ? (
              <span className="text-xs text-amber-300">Reset it in Settings</span>
            ) : (
              <button className={status === 'stopped' ? primaryButtonClass : buttonClass} onClick={() => void toggleSimulation()}>
                {status === 'stopped' ? 'Start simulation' : status === 'running' ? 'Pause' : 'Resume'}
              </button>
            )}
          </div>
        </header>
        {actionError && <p role="alert" className="px-4 pt-3 text-sm text-amber-300">{actionError}</p>}

        <main className="p-4">
          {view === 'overview' && (
            <Overview version={version} live={live} onOpenAlert={(id) => { setSelectedAlert(id); setView('alerts') }} />
          )}
          {view === 'alerts' && (
            <Alerts version={version} selectedId={selectedAlert} onSelect={setSelectedAlert} search={search} onSearch={setSearch} onChanged={bump}
  onAsk={(id) => { setSelectedAlert(id); setView('assistant') }} />
          )}
          {view === 'network' && (
            <Network version={version} onSearchAccount={(id) => { setSearch(id); setSelectedAlert(null); setView('alerts') }} />
          )}
          {view === 'evaluation' && <Evaluation version={version} />}
          {view === 'assistant' && <Assistant version={version} selectedAlert={selectedAlert} />}
          {view === 'settings' && <Settings version={version} onChanged={bump} />}
        </main>
      </div>
    </div>
  )
}