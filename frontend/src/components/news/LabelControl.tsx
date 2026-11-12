import { useState } from 'react'
import type { LabelRecord, LabelTarget, Verdict } from '../../api/types'
import { RECORD_FIELDS, type LabelChange } from '../../lib/labels'

const VERDICTS: { value: Verdict; label: string; tone: string }[] = [
  {
    value: 'correct',
    label: 'Correct',
    tone: 'border-emerald-500 bg-emerald-500/20 text-emerald-200',
  },
  {
    value: 'partial',
    label: 'Partly wrong',
    tone: 'border-amber-500 bg-amber-500/20 text-amber-200',
  },
  { value: 'incorrect', label: 'Wrong', tone: 'border-rose-500 bg-rose-500/20 text-rose-200' },
]

interface Props {
  table: Exclude<LabelTarget, 'documents'>
  current: LabelRecord | undefined
  busy: boolean
  onSave: (change: LabelChange) => void
}

/** One verdict per record: correct, partly wrong (naming the wrong fields), or wrong. */
export default function LabelControl({ table, current, busy, onSave }: Props) {
  const [partial, setPartial] = useState<string[]>(
    current?.verdict === 'partial' && current.field ? current.field.split(',') : [],
  )
  const [note, setNote] = useState(current?.note ?? '')
  const [open, setOpen] = useState(current?.verdict === 'partial')

  const choose = (v: Verdict) => {
    if (v === 'partial') {
      setOpen(true)
      return
    }
    setOpen(false)
    onSave({ verdict: v, field: '', note: note || null })
  }

  return (
    <div className="w-44 space-y-1.5">
      <div className="flex gap-1" role="group" aria-label="Verdict">
        {VERDICTS.map((v) => {
          const active = current?.verdict === v.value || (v.value === 'partial' && open)
          return (
            <button
              key={v.value}
              type="button"
              disabled={busy}
              aria-pressed={active}
              onClick={() => choose(v.value)}
              className={`flex-1 rounded border px-1 py-0.5 text-[11px] ${
                active ? v.tone : 'border-ink-700 text-ink-300 hover:bg-ink-800'
              }`}
            >
              {v.label}
            </button>
          )
        })}
      </div>
      {open && (
        <div className="border-ink-700 space-y-1 rounded border p-1.5">
          <div className="flex flex-wrap gap-1">
            {RECORD_FIELDS[table].map((f) => (
              <label key={f} className="flex items-center gap-1 text-[11px]">
                <input
                  type="checkbox"
                  className="accent-amber-500"
                  checked={partial.includes(f)}
                  onChange={(e) =>
                    setPartial(e.target.checked ? [...partial, f] : partial.filter((x) => x !== f))
                  }
                />
                {f}
              </label>
            ))}
          </div>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional)"
            className="border-ink-700 bg-ink-800 w-full rounded border px-1.5 py-0.5 text-[11px]"
          />
          <button
            type="button"
            disabled={busy || partial.length === 0}
            onClick={() =>
              onSave({ verdict: 'partial', field: partial.sort().join(','), note: note || null })
            }
            className="w-full rounded bg-amber-600 py-0.5 text-[11px] font-medium text-white disabled:opacity-40"
          >
            Save partial
          </button>
        </div>
      )}
    </div>
  )
}
