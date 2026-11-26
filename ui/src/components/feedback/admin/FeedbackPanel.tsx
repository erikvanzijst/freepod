import { Box, FormControl, InputLabel, MenuItem, Select, ToggleButton, ToggleButtonGroup, Tooltip } from '@mui/material'
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'
import { DataGrid, type GridColDef, type GridPaginationModel } from '@mui/x-data-grid'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { listFeedback } from '../../../api/endpoints'
import type { FeedbackState, FeedbackSummary, FeedbackTopic } from '../../../api/types'
import { formatLocalIso } from '../../../utils/formatDate'
import { TOPIC_LABELS, TOPICS } from '../topics'
import { FEEDBACK_QUERY_KEY } from './useFeedbackUnread'

const STATES: FeedbackState[] = ['open', 'resolved', 'all']

const columns: GridColDef<FeedbackSummary>[] = [
  {
    field: 'read',
    headerName: '',
    width: 36,
    sortable: false,
    renderCell: ({ value }) =>
      value ? null : (
        <Tooltip title="Unread">
          <FiberManualRecordIcon aria-label="Unread" color="secondary" sx={{ fontSize: 10 }} />
        </Tooltip>
      ),
  },
  { field: 'created_at', headerName: 'Sent', width: 170, sortable: false, renderCell: ({ value }) => formatLocalIso(value) },
  { field: 'topic', headerName: 'Topic', width: 160, sortable: false, renderCell: ({ value }) => TOPIC_LABELS[value as FeedbackTopic] },
  { field: 'email', headerName: 'From', flex: 1, minWidth: 180, sortable: false },
  { field: 'page', headerName: 'Page', flex: 1, minWidth: 140, sortable: false },
  { field: 'excerpt', headerName: 'Message', flex: 2, minWidth: 240, sortable: false },
  {
    field: 'has_screenshot',
    headerName: '',
    width: 44,
    sortable: false,
    renderCell: ({ value }) =>
      value ? (
        <Tooltip title="Has a screenshot">
          <ImageOutlinedIcon aria-label="Has a screenshot" fontSize="small" sx={{ color: 'text.secondary' }} />
        </Tooltip>
      ) : null,
  },
]

export function FeedbackPanel() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const rawState = params.get('state') as FeedbackState | null
  const state: FeedbackState = rawState && STATES.includes(rawState) ? rawState : 'open'
  const rawTopic = params.get('topic') as FeedbackTopic | null
  const topic = rawTopic && rawTopic in TOPIC_LABELS ? rawTopic : null
  const [pagination, setPagination] = useState<GridPaginationModel>({ page: 0, pageSize: 25 })

  const { data, isLoading } = useQuery({
    queryKey: [...FEEDBACK_QUERY_KEY, 'list', state, topic, pagination],
    queryFn: () =>
      listFeedback({ state, topic, offset: pagination.page * pagination.pageSize, limit: pagination.pageSize }),
    placeholderData: keepPreviousData,
  })

  const setFilter = (key: 'state' | 'topic', value: string | null) => {
    setPagination((p) => ({ ...p, page: 0 }))
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (!value || (key === 'state' && value === 'open')) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )
  }

  return (
    <Box sx={{ width: '100%' }}>
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mb: 1.5, flexWrap: 'wrap' }}>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={state}
          onChange={(_e, value) => value && setFilter('state', value)}
          aria-label="Which feedback"
        >
          <ToggleButton value="open">Open</ToggleButton>
          <ToggleButton value="resolved">Resolved</ToggleButton>
          <ToggleButton value="all">All</ToggleButton>
        </ToggleButtonGroup>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="feedback-topic-label">Topic</InputLabel>
          <Select
            labelId="feedback-topic-label"
            label="Topic"
            value={topic ?? ''}
            onChange={(e) => setFilter('topic', e.target.value || null)}
          >
            <MenuItem value="">All topics</MenuItem>
            {TOPICS.map((t) => (
              <MenuItem key={t.value} value={t.value}>
                {t.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>
      <DataGrid
        rows={data?.items ?? []}
        columns={columns}
        loading={isLoading}
        rowCount={data?.total ?? 0}
        paginationMode="server"
        paginationModel={pagination}
        onPaginationModelChange={setPagination}
        pageSizeOptions={[25, 50, 100]}
        autoHeight
        disableRowSelectionOnClick
        disableColumnMenu
        onRowClick={({ id }) => navigate(`/admin/feedback/${id}`)}
        getRowClassName={({ row }) => (row.read ? '' : 'feedback-unread')}
        localeText={{ noRowsLabel: state === 'open' ? 'No open feedback' : 'No feedback' }}
        sx={{
          border: 0,
          '& .MuiDataGrid-columnHeaders': { bgcolor: 'action.hover' },
          '& .MuiDataGrid-row': { cursor: 'pointer' },
          '& .feedback-unread': { fontWeight: 600 },
        }}
      />
    </Box>
  )
}
