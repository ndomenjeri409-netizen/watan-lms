import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src')
const defaultPaletteClass =
  /\b(bg|text|border|ring|fill|stroke|from|to|via)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/
const rawColor = /#[\da-fA-F]{3,8}\b|\b(?:rgb|hsl)\s*\(/i
const paletteTokens = new Map([
  ['ink', '#0D0E12'],
  ['panel', '#181A22'],
  ['amber', '#FFAE1B'],
  ['violet', '#8F41FF'],
  ['white', '#FFFFFF'],
  ['mist', '#A0A5B5'],
  ['success', '#22C55E'],
  ['danger', '#EF4444'],
])
const errors = []

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(async (entry) => {
    const filePath = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(filePath)
    return /\.(?:ts|tsx|css)$/.test(entry.name) ? [filePath] : []
  }))
  return files.flat()
}

function themeBlock(css) {
  const start = css.indexOf('@theme {')
  if (start < 0) return null

  const open = css.indexOf('{', start)
  let depth = 0
  for (let index = open; index < css.length; index += 1) {
    if (css[index] === '{') depth += 1
    if (css[index] === '}') depth -= 1
    if (depth === 0) return { start, end: index + 1, text: css.slice(start, index + 1) }
  }
  return null
}

for (const filePath of await sourceFiles(sourceRoot)) {
  const contents = await readFile(filePath, 'utf8')
  const relativePath = path.relative(sourceRoot, filePath)
  const block = relativePath === 'index.css' ? themeBlock(contents) : null
  if (relativePath === 'index.css' && !block) {
    errors.push('src/index.css: missing balanced @theme block')
  }

  const checkedContents = block
    ? `${contents.slice(0, block.start)}${contents.slice(block.end)}`
    : contents
  if (rawColor.test(checkedContents)) {
    errors.push(`src/${relativePath}: raw hex, rgb(), or hsl() color outside the palette block`)
  }
  if (defaultPaletteClass.test(contents)) {
    errors.push(`src/${relativePath}: Tailwind default-palette color class`)
  }

  if (block) {
    const declarations = [...block.text.matchAll(/--color-(ink|panel|amber|violet|white|mist|success|danger):\s*(#[\da-fA-F]{6})\b/g)]
    const found = new Map(declarations.map(([, token, value]) => [token, value.toUpperCase()]))
    for (const [token, expected] of paletteTokens) {
      if (found.get(token) !== expected) {
        errors.push(`src/index.css: --color-${token} must be ${expected}`)
      }
    }
    if (found.size !== paletteTokens.size) {
      errors.push('src/index.css: @theme must declare exactly the eight approved palette colors')
    }
    const blockColors = [...block.text.matchAll(/#[\da-fA-F]{3,8}\b/g)]
    if (blockColors.length !== paletteTokens.size) {
      errors.push('src/index.css: @theme contains an unapproved or duplicate hex color')
    }
  }
}

if (errors.length > 0) {
  console.error(errors.map((error) => `Color check failed: ${error}`).join('\n'))
  process.exitCode = 1
} else {
  console.log('Color check passed: palette, semantic classes, and raw-color restrictions are valid.')
}
