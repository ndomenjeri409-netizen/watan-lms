import { expect, test, type Page } from '@playwright/test'

const units = ['WTI', 'WTA', 'WDS', 'WCY'].map((code, index) => ({
  id: `unit-${index}`,
  code,
  name: `${code} Unit`,
  kind: 'TRAINING',
  currency: 'KES',
  modules: {},
  is_active: true,
}))

async function openTopbar(page: Page) {
  await page.route('**/api/v1/units**', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ count: units.length, next: null, previous: null, results: units }),
  }))
  await page.goto('/e2e/topbar.html')
  await expect(page.getByRole('combobox', { name: 'Business unit' })).toBeAttached()
}

async function measureHeader(page: Page) {
  return page.locator('header').evaluate((header) => {
    const controls = Array.from(header.querySelectorAll('button, select, input'))
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
      })
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          name: element.getAttribute('aria-label') ?? element.tagName,
          x: rect.x,
          y: rect.y,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        }
      })
    const overlaps = controls.flatMap((left, index) => controls.slice(index + 1)
      .filter((right) => (
        left.x < right.right - 1
        && left.right > right.x + 1
        && left.y < right.bottom - 1
        && left.bottom > right.y + 1
      ))
      .map((right) => `${left.name} / ${right.name}`))
    return {
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      controls,
      overlaps,
    }
  })
}

test('fits supported widths without horizontal overflow or overlapping topbar controls', async ({ page }) => {
  await openTopbar(page)

  for (const width of [320, 360, 375, 390, 414, 768, 1024, 1280]) {
    await page.setViewportSize({ width, height: 812 })
    const layout = await measureHeader(page)
    expect(layout.scrollWidth, `document overflow at ${width}px`).toBeLessThanOrEqual(layout.viewportWidth)
    expect(layout.overlaps, `overlapping controls at ${width}px`).toEqual([])

    if (width < 640) {
      for (const control of layout.controls) {
        expect(control.width, `${control.name} width at ${width}px`).toBeGreaterThanOrEqual(44)
        expect(control.height, `${control.name} height at ${width}px`).toBeGreaterThanOrEqual(44)
      }
      if (width === 320) {
        await expect(page.getByText('All', { exact: true })).toBeVisible()
        await page.getByRole('combobox', { name: 'Business unit' }).selectOption('unit-0')
        await expect(page.getByText('WTI', { exact: true })).toBeVisible()
        await page.getByRole('combobox', { name: 'Business unit' }).selectOption('all')
      }
      const byName = Object.fromEntries(layout.controls.map((control) => [control.name, control]))
      expect(byName['Open navigation menu'].x).toBeLessThan(byName['Business unit'].x)
      expect(byName['Business unit'].x).toBeLessThan(byName['Open search'].x)
      if (width >= 360) expect(byName['Open search'].x).toBeLessThan(byName['Switch to light mode'].x)
    } else {
      const byName = Object.fromEntries(layout.controls.map((control) => [control.name, control]))
      expect(byName.Search.x).toBeLessThan(byName['Business unit'].x)
      await expect(page.locator('header kbd')).toHaveCount(1)
      if (width >= 1024) await expect(page.locator('header kbd')).toBeVisible()
      else await expect(page.locator('header kbd')).toBeHidden()
    }
  }
})

test('keeps mobile keyboard order and opens/closes the search dialog', async ({ page }) => {
  await openTopbar(page)
  await page.setViewportSize({ width: 375, height: 812 })

  const menu = page.getByRole('button', { name: 'Open navigation menu' })
  await menu.focus()
  for (const name of [
    'Business unit',
    'Open search',
    'Switch to light mode',
    'Account menu for Admin Example',
  ]) {
    await page.keyboard.press('Tab')
    await expect(page.locator(':focus')).toHaveAttribute('aria-label', name)
  }

  await page.getByRole('button', { name: 'Open search' }).click()
  const dialog = page.getByRole('dialog', { name: 'Search' })
  await expect(dialog).toBeVisible()
  expect((await dialog.boundingBox())?.width).toBeGreaterThanOrEqual(350)
  await expect(dialog.getByRole('textbox', { name: 'Search' })).toBeFocused()
  await expect(dialog.getByText('Search is coming soon')).toBeVisible()
  const dialogControls = await dialog.locator('button, input').evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect()
    return { width: rect.width, height: rect.height }
  }))
  for (const control of dialogControls) {
    expect(control.width).toBeGreaterThanOrEqual(44)
    expect(control.height).toBeGreaterThanOrEqual(44)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
})

test('shows the theme toggle at 360px and moves it into the account menu below 360px', async ({ page }) => {
  await openTopbar(page)
  await page.setViewportSize({ width: 360, height: 812 })
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible()
  await page.getByRole('button', { name: 'Account menu for Admin Example' }).click()
  await expect(page.getByRole('menuitem', { name: 'Switch to light mode' })).toBeHidden()
  await page.keyboard.press('Escape')

  await page.setViewportSize({ width: 320, height: 812 })
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeHidden()
  await page.getByRole('button', { name: 'Account menu for Admin Example' }).click()
  const themeMenuItem = page.getByRole('menuitem', { name: 'Switch to light mode' })
  await expect(themeMenuItem).toBeVisible()
  const menuItemBounds = await themeMenuItem.boundingBox()
  expect(menuItemBounds?.width).toBeGreaterThanOrEqual(44)
  expect(menuItemBounds?.height).toBeGreaterThanOrEqual(44)
  await themeMenuItem.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('hides the shortcut hint without a fine hover pointer', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 812 },
    isMobile: true,
    hasTouch: true,
  })
  const page = await context.newPage()
  await openTopbar(page)
  expect(await page.evaluate(() => window.matchMedia('(hover:hover) and (pointer:fine)').matches)).toBe(false)
  await expect(page.locator('header kbd')).toBeHidden()
  await context.close()
})

test('uses the macOS shortcut label and supports light and dark themes', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' }))
  await openTopbar(page)
  await page.setViewportSize({ width: 1280, height: 812 })
  await expect(page.locator('header kbd')).toHaveText('⌘ K')
  await page.setViewportSize({ width: 390, height: 812 })

  await page.getByRole('button', { name: 'Switch to light mode' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: 'Switch to dark mode' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('fits a 320px effective viewport at 200% browser zoom', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 320, height: 812 },
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()
  await openTopbar(page)
  expect(await page.evaluate(() => window.devicePixelRatio)).toBe(2)

  const layout = await measureHeader(page)
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.viewportWidth)
  expect(layout.overlaps).toEqual([])
  for (const control of layout.controls) {
    expect(control.width).toBeGreaterThanOrEqual(44)
    expect(control.height).toBeGreaterThanOrEqual(44)
  }
  await context.close()
})
