import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)

export const DATE_TIME_FORMAT = 'YYYY-MM-DD HH:mm:ss'
export const SHORT_DATE_TIME_FORMAT = 'MM-DD HH:mm:ss'

const timezonePattern = /(?:Z|[+-]\d{2}:?\d{2})$/i

function normalizeUtcInput(value) {
  if (typeof value !== 'string') return value

  const trimmed = value.trim()
  if (!trimmed) return trimmed

  const isoLike = trimmed.replace(' ', 'T')
  return timezonePattern.test(isoLike) ? isoLike : `${isoLike}Z`
}

function normalizeWallClockInput(value) {
  return typeof value === 'string' ? value.trim().replace(' ', 'T') : value
}

function normalizeUtc8WallClockInput(value) {
  const normalized = normalizeWallClockInput(value)
  if (typeof normalized !== 'string' || !normalized) return normalized

  return timezonePattern.test(normalized) ? normalized : `${normalized}+08:00`
}

export function parseUtcDate(value) {
  if (!value) return null

  const parsed = dayjs.utc(normalizeUtcInput(value))
  return parsed.isValid() ? parsed.toDate() : null
}

export function formatUtc8DateTime(value, pattern = DATE_TIME_FORMAT, fallback = '-') {
  if (!value) return fallback

  const parsed = dayjs.utc(normalizeUtcInput(value))
  return parsed.isValid() ? parsed.utcOffset(8).format(pattern) : fallback
}

export function formatUtc8AsBackendUtc(value, pattern = DATE_TIME_FORMAT, fallback = '') {
  if (!value) return fallback

  // Interpret the picker value as UTC+8 wall-clock time before converting to backend UTC.
  const parsed = dayjs.utc(normalizeUtc8WallClockInput(value))
  return parsed.isValid() ? parsed.format(pattern) : fallback
}
