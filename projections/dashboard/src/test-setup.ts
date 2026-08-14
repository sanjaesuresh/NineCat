import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// vite.config.ts doesn't set test.globals, so RTL's own auto-cleanup (which
// relies on a global afterEach) never registers -- without this, rendered
// components from one test file leak into the next test's DOM.
afterEach(() => {
  cleanup()
})
