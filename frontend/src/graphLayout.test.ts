import { describe, expect, it } from 'vitest'
import { buildEvidenceGraph, buildNetworkGraph, circlePositions, layoutForRule } from './graphLayout'
import type { AlertDetail, GraphData, Transaction } from './types'

const tx = (id: string, s: string, t: string, amount: string): Transaction => ({
  id, source_account_id: s, target_account_id: t, amount, currency: 'USD',
  timestamp: '2026-03-01T10:00:00Z', ingested_at: '2026-03-01T10:00:00Z',
})

const detail = (rule: AlertDetail['rule'], accounts: string[], evidence: Transaction[]): AlertDetail => ({
  id: 1, rule, risk_score: 50, priority: 'medium', summary: '', accounts, status: 'new', window_start: '',
  window_end: '', evidence_count: evidence.length, created_at: '', updated_at: '', contributions: [],
  evidence, notes: [], history: [], allowed_next_statuses: [], comment_required_for: [],
})

describe('layouts', () => {
  it('puts a chain on one horizontal line in money order', () => {
    const { positions, horizontal } = layoutForRule('pass_through_chain', ['A', 'B', 'C'])
    expect(horizontal).toBe(true)
    expect([positions.A.x, positions.B.x, positions.C.x]).toEqual([0, 240, 480])
    expect(new Set([positions.A.y, positions.B.y, positions.C.y]).size).toBe(1)
  })
  it('puts the focus account of a burst in the centre', () => {
    const { positions } = layoutForRule('burst', ['HUB', 'X', 'Y', 'Z'])
    expect(positions.HUB).toEqual({ x: 0, y: 0 })
    expect(positions.X).not.toEqual({ x: 0, y: 0 })
  })
  it('spreads points evenly on a circle', () => {
    const p = circlePositions(['a', 'b', 'c', 'd'], 100)
    for (const id of ['a', 'b', 'c', 'd']) expect(Math.hypot(p[id].x, p[id].y)).toBeCloseTo(100)
  })
  it('handles an empty account list', () => {
    expect(layoutForRule('cycle', []).positions).toEqual({})
  })
})

describe('buildEvidenceGraph', () => {
  it('draws one numbered arrow per hop of a chain', () => {
    const g = buildEvidenceGraph(detail('pass_through_chain', ['A', 'B', 'C'], [tx('1', 'A', 'B', '100'), tx('2', 'B', 'C', '95')]))
    expect(g.nodes.map((n) => n.id)).toEqual(['A', 'B', 'C'])
    expect(g.edges.map((e) => e.label)).toEqual(['1. $100.00', '2. $95.00'])
  })
  it('merges repeated transfers between the same two accounts', () => {
    const g = buildEvidenceGraph(detail('burst', ['A', 'B'], [tx('1', 'A', 'B', '10'), tx('2', 'A', 'B', '15'), tx('3', 'A', 'B', '5')]))
    expect(g.edges).toHaveLength(1)
    expect(g.edges[0].label).toBe('3 transfers, $30.00')
  })
  it('includes accounts that appear only in the evidence', () => {
    const g = buildEvidenceGraph(detail('cycle', ['A'], [tx('1', 'A', 'Z', '1')]))
    expect(g.nodes.map((n) => n.id).sort()).toEqual(['A', 'Z'])
  })
})

describe('buildNetworkGraph', () => {
  const data: GraphData = {
    nodes: [
      { id: 'A', name: 'A', account_type: 'individual', open_alerts: 2 },
      { id: 'B', name: 'B', account_type: 'business', open_alerts: 0 },
    ],
    edges: [{ source: 'A', target: 'B', transaction_count: 9, total_amount: '90.00', currency: 'USD' }],
    transactions_considered: 9,
  }
  it('outlines accounts with open alerts in amber and the selection in emerald', () => {
    const g = buildNetworkGraph(data, 'B')
    expect(String(g.nodes[0].style?.border)).toContain('#fbbf24')
    expect(String(g.nodes[1].style?.border)).toContain('#34d399')
  })
  it('makes busier links thicker but caps the thickness', () => {
    const thin = buildNetworkGraph({ ...data, edges: [{ ...data.edges[0], transaction_count: 1 }] }, null)
    const thick = buildNetworkGraph({ ...data, edges: [{ ...data.edges[0], transaction_count: 1000 }] }, null)
    expect(Number(thick.edges[0].style?.strokeWidth)).toBeGreaterThan(Number(thin.edges[0].style?.strokeWidth))
    expect(Number(thick.edges[0].style?.strokeWidth)).toBeLessThanOrEqual(4)
  })
})