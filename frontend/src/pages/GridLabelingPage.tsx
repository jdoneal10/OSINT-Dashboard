import type { GridReviewItem } from '../api/types'
import TopicLabelingPage, { type TopicConfig } from '../components/labeling/TopicLabelingPage'
import { categoryLabel } from '../lib/priority'

const GRID: TopicConfig<GridReviewItem> = {
  topic: 'grid',
  title: 'Grid labeling',
  intro:
    'Judge the grid kind and indicators only. Wrong = no grid interaction or indicator at all.',
  correctTitle: 'The kind and every indicator are right',
  wrongTitle: 'No grid interaction or indicator at all',
  items: (item) => [
    ...(item.kind ? [{ key: 'kind', text: `Kind: ${categoryLabel(item.kind)}` }] : []),
    ...item.indicators.map((i) => ({
      key: i,
      text: `Indicator: ${categoryLabel(i)}`,
      dashed: true,
    })),
  ],
  empty: 'No events with a grid kind or indicator yet.',
}

/** Grid-verdict labeling (ADR 0014 step 6): the grid kind and energy indicators. */
export default function GridLabelingPage() {
  return <TopicLabelingPage config={GRID} />
}
