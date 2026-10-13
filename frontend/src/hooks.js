import { useCallback, useEffect, useRef, useState } from 'react'








/** Load data when the component appears and whenever `deps` change (use simple values: numbers, strings).
 *  Old data stays on screen while refreshing, so the page never flashes empty. */
export function useFetch(fetcher, deps) {
  const [result, setResult] = useState({ data: null, error: null })
  const [tick, setTick] = useState(0)
  const key = JSON.stringify(deps)

  // Always call the newest version of the fetch function without making it a dependency.
  const latest = useRef(fetcher)
  useEffect(() => {
    latest.current = fetcher
  })

  useEffect(() => {
    let cancelled = false // ignore answers that arrive after we've moved on
    latest.current().then(
      (data) => {
        if (!cancelled) setResult({ data, error: null })
      },
      (err) => {
        if (!cancelled) {
          setResult((r) => ({ data: r.data, error: err instanceof Error ? err.message : 'Something went wrong' }))
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { ...result, loading: result.data === null && result.error === null, reload }
}