/** Admiralty (NATO) grading: source reliability A–F and information credibility 1–6. */

export const RELIABILITY: Record<string, string> = {
  A: 'Completely reliable',
  B: 'Usually reliable',
  C: 'Fairly reliable',
  D: 'Not usually reliable',
  E: 'Unreliable',
  F: 'Reliability cannot be judged',
}

export const CREDIBILITY: Record<number, string> = {
  1: 'Confirmed by independent sources',
  2: 'Probably true',
  3: 'Possibly true',
  4: 'Doubtful',
  5: 'Improbable',
  6: 'Truth cannot be judged',
}

/** "B2" → "Usually reliable source; probably true". */
export function describeGrade(grade: string | null): string {
  if (!grade) return 'Not graded'
  const rel = RELIABILITY[grade[0]] ?? 'Unknown reliability'
  const cred = CREDIBILITY[Number(grade.slice(1))] ?? 'unknown credibility'
  return `${rel} source; ${cred.toLowerCase()}`
}

/** Tailwind classes by credibility: corroborated green → doubtful red. */
export function gradeTone(grade: string | null): string {
  const cred = grade ? Number(grade.slice(1)) : NaN
  if (cred <= 2) return 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
  if (cred === 3) return 'border-sky-500/50 bg-sky-500/10 text-sky-300'
  if (cred === 4) return 'border-amber-500/50 bg-amber-500/10 text-amber-300'
  if (cred >= 5) return 'border-rose-500/50 bg-rose-500/10 text-rose-300'
  return 'border-ink-700 bg-ink-800 text-ink-500'
}
