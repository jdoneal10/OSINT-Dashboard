/** Colors for ACLED event types (shared by map points and legends). */
export const EVENT_TYPE_COLORS: Record<string, string> = {
  Battles: '#f43f5e',
  'Violence against civilians': '#f59e0b',
  'Explosions/Remote violence': '#a78bfa',
  Riots: '#38bdf8',
  Protests: '#34d399',
  'Strategic developments': '#94a3b8',
}

export const OTHER_EVENT_COLOR = '#e6ebf1'

export const eventColor = (type: string) => EVENT_TYPE_COLORS[type] ?? OTHER_EVENT_COLOR
