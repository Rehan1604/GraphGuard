import { useEffect, useReducer, useRef, useState } from 'react'
import { WS_URL, fetchSimulation, fetchTransactions } from './api'










export const initialLive = { connected: false, simulation: null, recent: [], lastSeq: null, changes: 0 }
const MAX_RECENT = 100

 





function newestFirst(a, b) {
  return a.timestamp === b.timestamp ? b.id.localeCompare(a.id) : b.timestamp.localeCompare(a.timestamp)
}

/** Pure function: given the old state and one event, return the new state. Easy to test. */
export function liveReducer(state, action) {
  switch (action.type) {
    case 'connected':
      return { ...state, connected: true }
    case 'disconnected':
      return { ...state, connected: false }
    case 'seed': {
      const known = new Set(state.recent.map((t) => t.id))
      const merged = [...state.recent, ...action.recent.filter((t) => !known.has(t.id))].sort(newestFirst)
      return { ...state, recent: merged.slice(0, MAX_RECENT), simulation: action.simulation }
    }
    case 'message': {
      const m = action.message
      if (m.type === 'hello') return { ...state, lastSeq: state.lastSeq ?? m.current_seq }
      if (m.type === 'resync_required') {
        return { ...state, lastSeq: m.current_seq, recent: [], changes: state.changes + 1 }
      }
      if (state.lastSeq !== null && m.seq <= state.lastSeq) return state // already processed: ignore
      const next = { ...state, lastSeq: m.seq }
      switch (m.type) {
        case 'transaction':
          if (state.recent.some((t) => t.id === m.data.id)) return next
          return { ...next, recent: [m.data, ...state.recent].slice(0, MAX_RECENT), changes: next.changes + 1 }
        case 'alert':
          return { ...next, changes: next.changes + 1 }
        case 'simulation':
          return { ...next, simulation: m.data }
        case 'reset':
          return { ...next, recent: [], changes: next.changes + 1 }
      }
    }
  }
}

/** Keeps one WebSocket open (reconnecting with growing delays) and turns events into state. */
export function useLiveFeed() {
  const [state, dispatch] = useReducer(liveReducer, initialLive)
  const lastSeq = useRef(null)
  const changes = useRef(0)
  const applied = useRef(0)
  const [dataVersion, setDataVersion] = useState(0)

  useEffect(() => {
    lastSeq.current = state.lastSeq
    changes.current = state.changes
  }, [state.lastSeq, state.changes])

  // At most once a second, tell the screens "refetch your data" (instead of once per event).
  useEffect(() => {
    const timer = setInterval(() => {
      if (changes.current !== applied.current) {
        applied.current = changes.current
        setDataVersion((v) => v + 1)
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    let socket = null
    let timer
    let attempt = 0
    let closed = false

    const seed = async () => {
      try {
        const [recent, simulation] = await Promise.all([fetchTransactions(50), fetchSimulation()])
        dispatch({ type: 'seed', recent, simulation })
      } catch {
        /* the connection indicator already tells the user the API is unreachable */
      }
    }

    const connect = () => {
      const resume = lastSeq.current !== null ? `?last_seq=${lastSeq.current}` : ''
      socket = new WebSocket(`${WS_URL}/ws/events${resume}`)
      socket.onopen = () => {
        attempt = 0
        dispatch({ type: 'connected' })
      }
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data ) 
        dispatch({ type: 'message', message })
        if (message.type === 'resync_required') void seed()
      }
      socket.onclose = () => {
        dispatch({ type: 'disconnected' })
        if (!closed) timer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 8000))
      }
    }

    void seed()
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [])

  return { ...state, dataVersion }
}