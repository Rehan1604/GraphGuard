import { describe, expect, it } from 'vitest'
import { initialLive, liveReducer, type LiveState } from './live'
import type { ServerMessage, SimulationState, Transaction } from './types'

const tx = (id: string, ts = '2026-03-01T10:00:00Z'): Transaction => ({
  id, source_account_id: 'A', target_account_id: 'B', amount: '1.00', currency: 'USD', timestamp: ts, ingested_at: ts,
})
const sim: SimulationState = {
  status: 'running', events_emitted: 1, transactions_created: 1, duplicates_ignored: 0, errors: 0,
  events_per_second: 2, seed: 1, duplicate_rate: 0, sim_time: null,
}
const msg = (state: LiveState, message: ServerMessage) => liveReducer(state, { type: 'message', message })
const txMsg = (seq: number, id: string): ServerMessage => ({ seq, type: 'transaction', data: tx(id) })

describe('liveReducer', () => {
  it('remembers the first hello number so older events are not replayed to the screen', () => {
    let s = msg(initialLive, { type: 'hello', current_seq: 40, replayed: 0 })
    expect(s.lastSeq).toBe(40)
    s = msg(s, txMsg(40, 'old'))
    expect(s.recent).toHaveLength(0)
    s = msg(s, txMsg(41, 'new'))
    expect(s.recent.map((t) => t.id)).toEqual(['new'])
  })

  it('ignores an event number it has already processed', () => {
    let s = msg(initialLive, txMsg(1, 'a'))
    const again = msg(s, txMsg(1, 'a'))
    expect(again).toBe(s)
    s = msg(s, txMsg(2, 'b'))
    expect(s.recent.map((t) => t.id)).toEqual(['b', 'a'])
  })

  it('does not show the same transaction twice even under a new event number', () => {
    let s = msg(initialLive, txMsg(1, 'a'))
    s = msg(s, txMsg(2, 'a'))
    expect(s.recent).toHaveLength(1)
    expect(s.lastSeq).toBe(2)
  })

  it('marks data as changed for transactions, alerts and resets but not for simulation status', () => {
    let s = msg(initialLive, txMsg(1, 'a'))
    expect(s.changes).toBe(1)
    s = msg(s, { seq: 2, type: 'simulation', data: sim })
    expect(s.changes).toBe(1)
    expect(s.simulation?.status).toBe('running')
    s = msg(s, { seq: 3, type: 'reset', data: {} })
    expect(s.changes).toBe(2)
    expect(s.recent).toEqual([])
  })

  it('a resync request clears the feed and adopts the server number', () => {
    let s = msg(initialLive, txMsg(5, 'a'))
    s = msg(s, { type: 'resync_required', current_seq: 2 })
    expect(s.recent).toEqual([])
    expect(s.lastSeq).toBe(2)
  })

  it('seeding merges with live events without duplicates, newest first, capped', () => {
    let s = msg(initialLive, { seq: 1, type: 'transaction', data: tx('live', '2026-03-01T12:00:00Z') })
    s = liveReducer(s, { type: 'seed', simulation: sim, recent: [tx('live', '2026-03-01T12:00:00Z'), tx('old', '2026-03-01T09:00:00Z')] })
    expect(s.recent.map((t) => t.id)).toEqual(['live', 'old'])
    const many = Array.from({ length: 150 }, (_, i) => tx(`t${i}`, `2026-03-01T${String(i % 24).padStart(2, '0')}:00:00Z`))
    expect(liveReducer(initialLive, { type: 'seed', simulation: sim, recent: many }).recent).toHaveLength(100)
  })

  it('tracks connection state', () => {
    expect(liveReducer(initialLive, { type: 'connected' }).connected).toBe(true)
    expect(liveReducer({ ...initialLive, connected: true }, { type: 'disconnected' }).connected).toBe(false)
  })
})