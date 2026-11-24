import type { UxsReviewItem } from '../api/types'
import TopicLabelingPage, { type TopicConfig } from '../components/labeling/TopicLabelingPage'
import { categoryLabel } from '../lib/priority'

const UXS: TopicConfig<UxsReviewItem> = {
  topic: 'uxs',
  title: 'UxS labeling',
  intro:
    'Judge the unmanned-system fields only: activity, platform, missions and payloads. ' +
    'Wrong = no criminal unmanned system at all (for example a police or military drone, or ' +
    'drone use that belongs to another event).',
  correctTitle: 'Activity, platform, every mission and every payload are right',
  wrongTitle: 'No criminal unmanned system at all',
  items: (item) => [
    { key: 'activity', text: `Activity: ${categoryLabel(item.activity)}` },
    { key: 'platform', text: `Platform: ${categoryLabel(item.platform)}` },
    ...item.missions.map((m) => ({ key: m, text: `Mission: ${categoryLabel(m)}`, dashed: true })),
    ...item.payloads.map((p) => ({ key: p, text: `Payload: ${categoryLabel(p)}`, dashed: true })),
  ],
  empty: 'No events with UxS fields yet.',
}

/** UxS-verdict labeling (ADR 0009 amendment 1): the unmanned-system fields of an event. */
export default function UxsLabelingPage() {
  return <TopicLabelingPage config={UXS} />
}
