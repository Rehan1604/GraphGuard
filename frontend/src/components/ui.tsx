import type { ReactNode } from 'react'
import { STATUS_LABELS } from '../format'
import type { FetchState } from '../hooks'
import type { Priority, Status } from '../types'

export function Card({ title, action, children, className = '' }: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border border-navy-700 bg-navy-900 p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-navy-700 bg-navy-900 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  )
}

const PRIORITY_STYLES: Record<Priority, string> = {
  low: 'border-slate-600 text-slate-300',
  medium: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  high: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${PRIORITY_STYLES[priority]}`}>
      {priority}
    </span>
  )
}

const STATUS_DOT: Record<Status, string> = {
  new: 'bg-emerald-400',
  in_review: 'bg-sky-400',
  escalated: 'bg-amber-400',
  dismissed: 'bg-slate-500',
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-navy-600 px-2 py-0.5 text-xs text-slate-200">
      <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status]}`} aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-navy-600 border-t-emerald-400" aria-hidden="true" />
      {label}...
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
      <p>{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded-md border border-amber-500/40 px-3 py-1 text-xs hover:bg-amber-500/10">
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-navy-600 p-6 text-center">
      <p className="font-medium text-slate-200">{title}</p>
      {children && <p className="mt-1 text-sm text-slate-400">{children}</p>}
    </div>
  )
}

/** Shows a spinner, an error, or the data. Keeps old data visible if a refresh fails. */
export function Async<T>({ state, children }: { state: FetchState<T>; children: (data: T) => ReactNode }) {
  if (state.data) {
    return (
      <>
        {state.error && <p className="mb-2 text-xs text-amber-300">Showing the last data we have: {state.error}</p>}
        {children(state.data)}
      </>
    )
  }
  if (state.error) return <ErrorBox message={state.error} onRetry={state.reload} />
  return <Spinner />
}

export function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-44 shrink-0 text-slate-300">{label}</span>
      <div className="h-2 flex-1 rounded bg-navy-700" aria-hidden="true">
        <div className="h-2 rounded bg-emerald-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 text-right tabular-nums text-slate-200">{value}</span>
    </div>
  )
}

export const inputClass =
  'w-full rounded-md border border-navy-600 bg-navy-800 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500'
export const buttonClass =
  'rounded-md border border-navy-600 bg-navy-800 px-3 py-1.5 text-sm text-slate-100 hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-40'
export const primaryButtonClass =
  'rounded-md border border-emerald-500/60 bg-emerald-500/15 px-3 py-1.5 text-sm font-medium text-emerald-200 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40'