import { readonly, ref } from 'vue'

export const MOBILE_BREAKPOINT = 768
export const COMPACT_BREAKPOINT = 1200

const isMobile = ref(false)
const isCompact = ref(false)
let initialized = false

function initializeResponsiveState() {
  if (initialized || typeof window === 'undefined') {
    return
  }

  initialized = true
  const mobileQuery = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
  const compactQuery = window.matchMedia(`(max-width: ${COMPACT_BREAKPOINT - 1}px)`)

  const sync = () => {
    isMobile.value = mobileQuery.matches
    isCompact.value = compactQuery.matches
  }

  sync()
  mobileQuery.addEventListener('change', sync)
  compactQuery.addEventListener('change', sync)
}

export function useResponsive() {
  initializeResponsiveState()

  return {
    isMobile: readonly(isMobile),
    isCompact: readonly(isCompact)
  }
}
