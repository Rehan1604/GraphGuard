import { afterEach, describe, expect, it, vi } from 'vitest'

async function load(url?: string) {
  vi.resetModules()
  if (url !== undefined) vi.stubEnv('VITE_API_URL', url)
  return import('./api')
}

afterEach(() => vi.unstubAllEnvs())

describe('API address', () => {
  it('uses the local backend by default', async () => {
    vi.stubEnv('VITE_API_URL', undefined as unknown as string)
    const m = await import('./api')
    expect(m.API_URL.startsWith('http')).toBe(true)
  })

  it('removes trailing slashes so paths do not become //api', async () => {
    const m = await load('https://graphguard-api.onrender.com/')
    expect(m.API_URL).toBe('https://graphguard-api.onrender.com')
  })

  it('uses wss for https and ws for http', async () => {
    expect((await load('https://api.example.com')).WS_URL).toBe('wss://api.example.com')
    expect((await load('http://localhost:8000')).WS_URL).toBe('ws://localhost:8000')
  })
})
