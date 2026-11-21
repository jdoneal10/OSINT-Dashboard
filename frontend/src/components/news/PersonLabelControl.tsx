import { useState } from 'react'
import type { LabelRecord, Verdict } from '../../api/types'
import {
  PERSON_FIELDS,
  SAFEGUARD_FIELDS,
  SAFEGUARD_LABELS,
  type LabelChange,
} from '../../lib/labels'

const VERDICTS: { value: Verdict; label: string; tone: string }[] = [
  { value: 'correct', label: 'Correct', tone: 'border-emerald-500 bg-emerald-500/20 text-emerald-200' },
  { value: 'partial', label: 'Partly wrong', tone: 'border-amber-500 bg-amber-500/20 text-amber-200' },
  { value: 'incorrect', label: 'Wrong', tone: 'border-rose-500 bg-rose-500/20 text-rose-200' },
] // prettier-ignore

interface Props {
  current: LabelRecord | undefined
  busy: boolean
  onSave: (change: LabelChange) => void
}

/**
 * One verdict per person per document (ADR 0013), plus hard-rule-3 safeguard flags that can
 * go with any verdict: any flag is a violation and fails the Phase 3 exit criterion.
 */
export default function PersonLabelControl({ current, busy, onSave }: Props) {
  const saved = current?.field ? current.field.split(',') : []
  const [wrong, setWrong] = useState<string[]>(saved.filter((f) => PERSON_FIELDS.includes(f)))
  const [flags, setFlags] = useState<string[]>(saved.filter((f) => SAFEGUARD_FIELDS.includes(f)))
  const [verdict, setVerdict] = useState<Verdict | null>(current?.verdict ?? null)
  const [note, setNote] = useState(current?.note ?? '')

  const save = (v: Verdict, w: string[], f: string[]) =>
    onSave({
      verdict: v,
      field: [...(v === 'partial' ? w : []), ...f].sort().join(','),
      note: note || null,
    })
  const toggle = (list: string[], key: string, on: boolean) =>
    on ? [...list, key] : list.filter((x) => x !== key)

  return (
    <div className="w-56 space-y-1.5">
      <div className="flex gap-1" role="group" aria-label="Person verdict">
        {VERDICTS.map((v) => (
          <button
            key={v.value}
            type="button"
            disabled={busy}
            aria-pressed={verdict === v.value}
            onClick={() => {
              setVerdict(v.value)
              if (v.value !== 'partial') save(v.value, [], flags)
            }}
            className={`flex-1 rounded border px-1 py-0.5 text-[11px] ${
              verdict === v.value ? v.tone : 'border-ink-700 text-ink-300 hover:bg-ink-800'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>
      {verdict === 'partial' && (
        <div className="border-ink-700 flex flex-wrap gap-1 rounded border p-1.5">
          {PERSON_FIELDS.map((f) => (
            <label key={f} className="flex items-center gap-1 text-[11px]">
              <input
                type="checkbox"
                className="accent-amber-500"
                checked={wrong.includes(f)}
                onChange={(e) => setWrong(toggle(wrong, f, e.target.checked))}
              />
              {f.replace('_', ' ')}
            </label>
          ))}
          <button
            type="button"
            disabled={busy || wrong.length === 0}
            onClick={() => save('partial', wrong, flags)}
            className="w-full rounded bg-amber-600 py-0.5 text-[11px] font-medium text-white disabled:opacity-40"
          >
            Save partial
          </button>
        </div>
      )}
      <fieldset className="space-y-0.5 rounded border border-rose-900/60 p-1.5">
        <legend className="px-1 text-[10px] text-rose-300 uppercase">Safeguard violations</legend>
        {SAFEGUARD_FIELDS.map((f) => (
          <label key={f} className="flex items-center gap-1 text-[11px] text-rose-200">
            <input
              type="checkbox"
              className="accent-rose-500"
              checked={flags.includes(f)}
              disabled={busy}
              onChange={(e) => {
                const next = toggle(flags, f, e.target.checked)
                setFlags(next)
                save(verdict ?? 'incorrect', wrong, next)
                if (!verdict) setVerdict('incorrect')
              }}
            />
            {SAFEGUARD_LABELS[f]}
          </label>
        ))}
      </fieldset>
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={() => verdict && save(verdict, wrong, flags)}
        placeholder="Note (optional)"
        className="border-ink-700 bg-ink-800 w-full rounded border px-1.5 py-0.5 text-[11px]"
      />
    </div>
  )
}
