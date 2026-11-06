/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

function color(token: string): string {
  const match = css.match(new RegExp(`--color-${token}:\\s*(#[\\da-f]{6})`, 'i'))
  if (!match) throw new Error(`Missing color token: ${token}`)
  return match[1]
}

function luminance(hex: string): number {
  const channels = hex.match(/[\da-f]{2}/gi)?.map((channel) => Number.parseInt(channel, 16) / 255)
  if (!channels || channels.length !== 3) throw new Error(`Invalid color: ${hex}`)
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

function mix(foreground: string, background: string, foregroundPercent: number): string {
  const toChannels = (hex: string) => hex.match(/[\da-f]{2}/gi)!.map((channel) => Number.parseInt(channel, 16))
  const foregroundChannels = toChannels(foreground)
  const backgroundChannels = toChannels(background)
  const mixed = foregroundChannels.map((channel, index) =>
    Math.round(channel * foregroundPercent + backgroundChannels[index] * (1 - foregroundPercent)),
  )
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
}

describe('palette contrast', () => {
  it.each([
    ['white', 'ink', 4.5],
    ['white', 'panel', 4.5],
    ['mist', 'ink', 4.5],
    ['mist', 'panel', 4.5],
    ['amber', 'ink', 4.5],
    ['amber', 'panel', 4.5],
    ['ink', 'amber', 4.5],
    ['white', 'violet', 4.5],
    ['violet', 'ink', 3],
    ['violet', 'panel', 3],
  ])('allowed palette pair meets its contrast threshold', (foreground, background, minimum) => {
    expect(contrast(color(foreground), color(background))).toBeGreaterThanOrEqual(minimum)
  })

  it('keeps muted light-theme text readable on white', () => {
    const muted = mix(color('ink'), color('white'), 0.62)
    expect(contrast(muted, color('white'))).toBeGreaterThanOrEqual(4.5)
  })
})
