import { describe, expect, it } from 'vitest'
import { formatMoney, formatTime, matchesSearch, timeOnly } from './format'
import type { AlertSummary } from './types'

const alert: AlertSummary = {
  id: 12, rule: 'pass_through_chain', risk_score: 50, priority: 'medium', summary: 'Money moved A -> B',
  accounts: ['SIM-A03', 'SIM-A22'], status: 'new', window_start: '', window_end: '', evidence_count: 3,
  created_at: '', updated_at: '',
}

describe('formatMoney', () => {
  it('formats decimal text as currency', () => {
    expect(formatMoney('1234.5', 'USD')).toBe('$1,234.50')
  })
  it('does not crash on odd input', () => {
    expect(formatMoney('abc', 'USD')).toBe('abc USD')
    expect(formatMoney('5', 'NOT-A-CURRENCY')).toContain('5.00')
  })
})

describe('time formatting', () => {
  it('always shows UTC', () => {
    expect(formatTime('2026-03-01T04:30:00Z')).toBe('2026-03-01 04:30:00 UTC')
    expect(timeOnly('2026-03-01T04:30:09Z')).toBe('04:30:09')
  })
  it('returns the original text if it is not a date', () => {
    expect(formatTime('nope')).toBe('nope')
  })
})

describe('matchesSearch', () => {
  it('matches account ids, #ids, pattern names and ignores case', () => {
    expect(matchesSearch(alert, 'sim-a22')).toBe(true)
    expect(matchesSearch(alert, '#12')).toBe(true)
    expect(matchesSearch(alert, 'pass-through')).toBe(true)
    expect(matchesSearch(alert, 'cycle')).toBe(false)
  })
  it('an empty search matches everything', () => {
    expect(matchesSearch(alert, '   ')).toBe(true)
  })
})