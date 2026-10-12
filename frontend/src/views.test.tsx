import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AlertDetail from './components/AlertDetail'
import { initialLive } from './live'
import Overview from './views/Overview'
import type { AlertDetail as Detail } from './types'

// React Flow needs real browser layout APIs that the test environment lacks, so swap in a stub.
vi.mock('./components/FlowGraph', () => ({ default: () => <div data-testid="graph" /> }))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function mockApi(routes: Record<string, unknown>, failing: string[] = []) {
  const calls: { url: string; method: string; body?: string }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace('http://localhost:8000', '')
    calls.push({ url: path, method: init?.method ?? 'GET', body: init?.body as string | undefined })
    if (failing.some((f) => path.startsWith(f))) return new Response(JSON.stringify({ detail: 'Cannot do that' }), { status: 409 })
    const key = Object.keys(routes).find((k) => path.startsWith(k))
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200 })
  }))
  return calls
}

const live = { ...initialLive, dataVersion: 0 }

describe('Overview', () => {
  it('shows a loading indicator, then real numbers from the API', async () => {
    mockApi({
      '/api/stats': { accounts: 40, transactions: 123, alerts_total: 7, alerts_open: 5 },
      '/api/metrics/alerts': { total: 7, by_status: {}, by_priority: { low: 4, medium: 2, high: 1 }, by_rule: {} },
      '/api/alerts': [],
      '/api/simulation': { status: 'stopped', events_emitted: 0, transactions_created: 0, duplicates_ignored: 0, errors: 0 },
    })
    render(<Overview version={0} live={live} onOpenAlert={() => {}} />)
    expect(screen.getAllByRole('status').length).toBeGreaterThan(0)
    await waitFor(() => expect(screen.getByText('123')).toBeTruthy())
    expect(screen.getByText('Open alerts')).toBeTruthy()
    expect(screen.getByText('No open alerts')).toBeTruthy()
  })

  it('shows a clear error with a retry button when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('failed to fetch') }))
    render(<Overview version={0} live={live} onOpenAlert={() => {}} />)
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
    expect(screen.getAllByText(/Cannot reach the API/).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'Try again' }).length).toBeGreaterThan(0)
  })
})

const detail = (overrides: Partial<Detail> = {}): Detail => ({
  id: 3, rule: 'cycle', risk_score: 60, priority: 'medium', summary: 'Money looped A -> B -> C -> A', accounts: ['A', 'B', 'C'],
  status: 'in_review', window_start: '2026-03-01T10:00:00Z', window_end: '2026-03-01T10:40:00Z', evidence_count: 1,
  created_at: '2026-03-01T10:00:00Z', updated_at: '2026-03-01T10:00:00Z',
  contributions: [{ reason: 'Money returned to its starting account after 3 transfers', points: 45 }, { reason: 'Amounts are similar', points: 15 }],
  evidence: [{ id: 'T1', source_account_id: 'A', target_account_id: 'B', amount: '500.00', currency: 'USD', timestamp: '2026-03-01T10:00:00Z', ingested_at: '' }],
  notes: [{ id: 1, alert_id: 3, author: 'priya', body: 'Checked <b>KYC</b>', created_at: '2026-03-01T11:00:00Z' }],
  history: [{ id: 1, event: 'created', from_status: null, to_status: null, actor: 'system', comment: null, created_at: '2026-03-01T10:00:00Z' }],
  allowed_next_statuses: ['escalated', 'dismissed'], comment_required_for: ['escalated', 'dismissed'],
  ...overrides,
})

describe('AlertDetail', () => {
  it('shows evidence, the score breakdown and only the moves the server allows', async () => {
    mockApi({ '/api/alerts/3': detail() })
    render(<AlertDetail alertId={3} refreshKey={0} onChanged={() => {}} />)
    await waitFor(() => expect(screen.getByText('$500.00')).toBeTruthy())
    expect(screen.getByText('+45')).toBeTruthy()
    expect(screen.getByText(/not a probability of fraud/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Mark escalated' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Mark dismissed' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /in review/i })).toBeNull() // the server did not allow it
  })

  it('renders note text as plain text, never as HTML', async () => {
    mockApi({ '/api/alerts/3': detail() })
    const { container } = render(<AlertDetail alertId={3} refreshKey={0} onChanged={() => {}} />)
    await waitFor(() => expect(screen.getByText('Checked <b>KYC</b>')).toBeTruthy())
    expect(container.querySelector('b')).toBeNull()
  })

  it('keeps dismiss disabled until a reason is typed, then sends it with the analyst name', async () => {
    const calls = mockApi({ '/api/alerts/3': detail() })
    render(<AlertDetail alertId={3} refreshKey={0} onChanged={() => {}} />)
    const dismiss = await screen.findByRole('button', { name: 'Mark dismissed' }) as HTMLButtonElement
    expect(dismiss.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'Payroll account' } })
    expect(dismiss.disabled).toBe(false)
    fireEvent.click(dismiss)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/alerts/3/status')).toBe(true))
    const post = calls.find((c) => c.url === '/api/alerts/3/status')!
    expect(JSON.parse(post.body!)).toEqual({ status: 'dismissed', comment: 'Payroll account', actor: 'analyst' })
  })

  it('shows the server message if a status change is rejected', async () => {
    mockApi({ '/api/alerts/3': detail() }, ['/api/alerts/3/status'])
    render(<AlertDetail alertId={3} refreshKey={0} onChanged={() => {}} />)
    fireEvent.change(await screen.findByLabelText(/Reason/), { target: { value: 'because' } })
    fireEvent.click(screen.getByRole('button', { name: 'Mark escalated' }))
    await waitFor(() => expect(screen.getByText('Cannot do that')).toBeTruthy())
  })

  it('lets an analyst save a note', async () => {
    const calls = mockApi({ '/api/alerts/3': detail() })
    render(<AlertDetail alertId={3} refreshKey={0} onChanged={() => {}} />)
    const save = await screen.findByRole('button', { name: 'Save note' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Add a note'), { target: { value: 'Called the branch' } })
    fireEvent.click(save)
    await waitFor(() => expect(calls.some((c) => c.url === '/api/alerts/3/notes')).toBe(true))
  })
})