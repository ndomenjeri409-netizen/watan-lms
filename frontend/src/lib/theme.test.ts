import { beforeEach, describe, expect, it } from 'vitest'
import { getTheme, setTheme } from './theme'

describe('theme preference', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to dark when there is no saved preference', () => {
    expect(getTheme()).toBe('dark')
  })

  it('honors and persists a saved preference', () => {
    setTheme('light')
    expect(getTheme()).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
