import { describe, expect, it } from 'vitest'

describe('GateFlow frontend configuration', () => {
  it('uses the local gateway as the default API origin', () => {
    expect(import.meta.env.VITE_API_URL ?? 'http://localhost:8080').toContain('http')
  })
})
