import { describe, expect, it } from 'vitest'
import { splitCitations } from './citations'

describe('splitCitations', () => {
  it('recognises case-memory citations such as [C1]', () => {
    expect(splitCitations('Seen before [C1, F2].')).toEqual([
      { kind: 'text', value: 'Seen before ' },
      { kind: 'cite', ids: ['C1', 'F2'] },
      { kind: 'text', value: '.' },
    ])
  })

  it('separates text from citation markers', () => {
    expect(splitCitations('Fast hops [F2] and a loop [K1].')).toEqual([
      { kind: 'text', value: 'Fast hops ' },
      { kind: 'cite', ids: ['F2'] },
      { kind: 'text', value: ' and a loop ' },
      { kind: 'cite', ids: ['K1'] },
      { kind: 'text', value: '.' },
    ])
  })
  it('handles several ids in one bracket', () => {
    expect(splitCitations('x [F1, K3]')).toEqual([{ kind: 'text', value: 'x ' }, { kind: 'cite', ids: ['F1', 'K3'] }])
  })
  it('leaves other brackets and plain text alone', () => {
    expect(splitCitations('see [note] and [F] and [X1]')).toEqual([{ kind: 'text', value: 'see [note] and [F] and [X1]' }])
    expect(splitCitations('')).toEqual([])
  })
})