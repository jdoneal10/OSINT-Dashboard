import { describe, expect, it } from 'vitest'
import type { LabelRecord } from '../api/types'
import { relevanceAnswer, relevanceVerdict } from './labels'

const label = (verdict: 'correct' | 'incorrect', judged: 'relevant' | 'not_relevant' | null) =>
  ({ verdict, judged_decision: judged }) as LabelRecord

describe('relevance labels', () => {
  it('stores the answer as a judgment of the pipeline decision', () => {
    expect(relevanceVerdict(true, true)).toBe('correct')
    expect(relevanceVerdict(true, false)).toBe('incorrect') // filter missed it
    expect(relevanceVerdict(false, false)).toBe('correct')
    expect(relevanceVerdict(false, true)).toBe('incorrect')
  })

  it('reads the answer back from the frozen decision, not the current status', () => {
    // Labeled "not relevant" while rejected; the document was later re-filtered in.
    expect(relevanceAnswer(label('correct', 'not_relevant'), true)).toBe(false)
    expect(relevanceAnswer(label('incorrect', 'not_relevant'), true)).toBe(true)
    expect(relevanceAnswer(label('correct', null), true)).toBe(true) // legacy label
    expect(relevanceAnswer(undefined, true)).toBeNull()
  })
})
