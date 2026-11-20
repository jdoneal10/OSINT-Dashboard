/** Priority border-threat categories (ADR 0007): labels and chip colours. */
export const BORDER_THREATS: Record<string, { label: string; tone: string }> = {
  human_smuggling: { label: 'Human smuggling', tone: 'border-amber-500/50 text-amber-300' },
  uas_incursion: { label: 'Drone (UAS) incursion', tone: 'border-rose-500/50 text-rose-300' },
  laser_strike: { label: 'Laser strike', tone: 'border-rose-500/50 text-rose-300' },
  gunfire: { label: 'Gunfire at the border', tone: 'border-rose-500/50 text-rose-300' },
  assault_on_personnel: {
    label: 'Assault on border personnel',
    tone: 'border-rose-500/50 text-rose-300',
  },
  tunnel: { label: 'Cross-border tunnel', tone: 'border-amber-500/50 text-amber-300' },
  other_border_threat: { label: 'Other border threat', tone: 'border-amber-500/50 text-amber-300' },
}

export const threatLabel = (t: string) => BORDER_THREATS[t]?.label ?? t
