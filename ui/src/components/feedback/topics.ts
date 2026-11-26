import type { FeedbackTopic } from '../../api/types'

export const TOPICS: { value: FeedbackTopic; label: string }[] = [
  { value: 'bug', label: 'Something is wrong' },
  { value: 'idea', label: 'An idea' },
  { value: 'other', label: 'Something else' },
]

export const TOPIC_LABELS: Record<FeedbackTopic, string> = Object.fromEntries(
  TOPICS.map((t) => [t.value, t.label]),
) as Record<FeedbackTopic, string>

export const THANKS_MS = 2500
