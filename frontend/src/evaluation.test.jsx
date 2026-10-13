import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { comparisonRows, formatRate } from './format'
import Evaluation from './views/Evaluation'


afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const rate = (n, d) => ({ numerator: n, denominator: d, value: d ? n / d : null })

const detector = (over = {}) => ({
  name: 'x', findings: 82, precision: rate(59, 82), recall: rate(40, 40), recall_lenient: rate(40, 40), f1: 0.8369,
  per_kind_recall: { cycle: rate(10, 10), burst: rate(10, 10) },
  confusion: { true_positive: 40, false_negative: 0, false_positive: 13, true_negative: 23 },
  false_positive_findings: 23, false_positives_from_benign_lookalikes: 17, false_positives_from_near_misses: 1,
  false_positives_mixed_overlap: 4, false_positives_background_only: 1, benign_lookalikes_flagged: rate(12, 12),
  near_misses_flagged: rate(1, 24), background_only_findings_per_1000_background: 1.43, ...over,
})

const report = {
  dataset: { name: 'benchmark', seed: 42, transactions: 1053, background_transactions: 700, episodes_by_role: { positive: 40, near_miss: 24 }, positives_by_kind: { cycle: 10 } },
  graph: detector(),
  baseline: detector({ findings: 168, precision: rate(39, 168), recall: rate(20, 40), f1: 0.317, per_kind_recall: { cycle: rate(0, 10), burst: rate(10, 10) } }),
  delay: { detected: 40, median_minutes_from_first_transfer: 7.16, max_minutes_from_first_transfer: 48.72, median_minutes_after_last_transfer: -0.44, flagged_before_pattern_finished: rate(25, 40), median_by_kind: { burst: 2.38 } },
  sweeps: [{ parameter: 'chain_hop_window_minutes', description: 'Max minutes between hops', default: 30, points: [{ value: 5, findings: 69, precision: 0.74, recall: 0.8, f1: 0.77 }, { value: 30, findings: 82, precision: 0.72, recall: 1, f1: 0.84 }] }],
  negative_control: { description: 'Answer key moved onto random transactions.', recall: rate(0, 40) },
  timing: { streaming_seconds: 1.5, milliseconds_per_transaction: 1.4 },
  caveats: ['This is a SYNTHETIC benchmark. Precision depends on the mix of look-alikes I planted.'],
}

function mockApi(evaluation) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = url.replace('http://localhost:8000', '')
    calls.push(path)
    if (path.startsWith('/api/evaluation')) return evaluation()
    return new Response(JSON.stringify({ total: 3, by_status: { new: 3, in_review: 0, escalated: 0, dismissed: 0 }, by_priority: { low: 1, medium: 2, high: 0 }, by_rule: { pass_through_chain: 1, cycle: 2, burst: 0, fan: 0 } }))
  }))
  return calls
}

describe('formatting', () => {
  it('always shows the denominator and says n/a when a fraction is undefined', () => {
    expect(formatRate(rate(59, 82))).toBe('59 / 82 (72.0%)')
    expect(formatRate(rate(0, 0))).toBe('0 / 0 (n/a)')
    expect(formatRate(rate(0, 40))).toBe('0 / 40 (0.0%)')
  })
  it('builds one comparison row per measure and spells out where false positives came from', () => {
    const rows = comparisonRows(detector(), detector({ findings: 168 }))
    expect(rows.map((r) => r.label)).toContain('Look-alikes flagged')
    expect(rows[0]).toMatchObject({ label: 'Alerts to read', graph: '82', baseline: '168' })
    expect(rows.at(-1)?.graph).toContain('17 look-alikes, 1 near-misses, 4 partial overlap, 1 pure background')
    expect(comparisonRows(detector({ f1: null }), detector())[4].graph).toBe('n/a')
  })
})

describe('Evaluation view', () => {
  it('does not show any accuracy numbers until the benchmark has been run, and warns up front', async () => {
    mockApi(() => new Response(JSON.stringify(report)))
    render(<Evaluation version={0} />)
    expect(screen.getByText(/that we planted/)).toBeTruthy()
    expect(screen.getByText('Not run yet')).toBeTruthy()
    expect(screen.queryByText(/59 \/ 82/)).toBeNull()
  })

  it('runs the benchmark with the chosen seed and shows both detectors with their denominators', async () => {
    const calls = mockApi(() => new Response(JSON.stringify(report)))
    render(<Evaluation version={0} />)
    fireEvent.change(screen.getByLabelText('Seed'), { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run benchmark' }))
    await waitFor(() => expect(screen.getAllByText('59 / 82 (72.0%)').length).toBeGreaterThan(0))
    expect(calls).toContain('/api/evaluation?dataset=benchmark&seed=7&n_events=240')
    expect(screen.getByText('39 / 168 (23.2%)')).toBeTruthy()
    expect(screen.getAllByText('0 / 10 (0.0%)').length).toBeGreaterThan(0) // the baseline cannot see loops
    expect(screen.getByText(/Recall fell to 0 \/ 40/)).toBeTruthy()
    expect(screen.getByText(/SYNTHETIC benchmark/)).toBeTruthy()
    expect(screen.getByText('default')).toBeTruthy()
  })

  it('shows the event count box only for the simulator dataset', async () => {
    mockApi(() => new Response(JSON.stringify(report)))
    render(<Evaluation version={0} />)
    expect(screen.queryByLabelText(/Events/)).toBeNull()
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'simulator' } })
    expect(screen.getByLabelText(/Events/)).toBeTruthy()
  })

  it('shows the server message when the evaluation fails', async () => {
    mockApi(() => new Response(JSON.stringify({ detail: 'seed must be >= 0' }), { status: 422 }))
    render(<Evaluation version={0} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run benchmark' }))
    await waitFor(() => expect(screen.getByText('seed must be >= 0')).toBeTruthy())
  })
})