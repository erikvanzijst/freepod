import { useQuery } from '@tanstack/react-query'
import { listFeedback } from '../../../api/endpoints'

export const FEEDBACK_QUERY_KEY = ['admin-feedback'] as const

/** D13: the unread count, from a counts-only list request. */
export function useFeedbackUnread(): number {
  const { data } = useQuery({
    queryKey: [...FEEDBACK_QUERY_KEY, 'unread'],
    queryFn: () => listFeedback({ state: 'all', limit: 0 }),
    refetchOnWindowFocus: true,
  })
  return data?.unread ?? 0
}
