import { Box } from '@mui/material'
import { CheckCircleOutline, WarningAmberOutlined } from '@mui/icons-material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listAllDeployments } from '../api/endpoints'
import { useAuth } from '../state/AuthContext'
import type { Deployment } from '../api/types'
import { formatLocalIso, parseUtc } from '../utils/formatDate'
import { DeploymentDialog } from './DeploymentDialog'

const columns: GridColDef<Deployment>[] = [
  {
    field: 'product',
    headerName: 'Product',
    flex: 1,
    minWidth: 120,
    valueGetter: (_value, row) => row.applied_template?.product?.name ?? row.desired_template?.product?.name ?? '',
  },
  {
    field: 'plan',
    headerName: 'Plan',
    flex: 0.8,
    minWidth: 100,
    valueGetter: (_value, row) => row.subscription?.plan_template?.plan?.name ?? '',
  },
  {
    field: 'hostname',
    headerName: 'Hostname',
    flex: 1.5,
    minWidth: 180,
    renderCell: ({ value }) =>
      value ? (
        <a href={`https://${value}`} target="_blank" rel="noopener noreferrer">
          {value}
        </a>
      ) : (
        ''
      ),
  },
  {
    field: 'email',
    headerName: 'Email',
    flex: 1.5,
    minWidth: 180,
    valueGetter: (_value, row) => row.user?.email ?? '',
  },
  {
    field: 'created_at',
    headerName: 'Created',
    flex: 1,
    minWidth: 160,
    valueGetter: (_value, row) => row.created_at ? parseUtc(row.created_at) : null,
    renderCell: ({ value }) => value ? formatLocalIso(value as Date) : '',
  },
  {
    field: 'last_reconcile_at',
    headerName: 'Last reconcile',
    flex: 1,
    minWidth: 160,
    valueGetter: (_value, row) => row.last_reconcile_at ? parseUtc(row.last_reconcile_at) : null,
    renderCell: ({ value }) => value ? formatLocalIso(value as Date) : '',
  },
  {
    field: 'status',
    headerName: 'Status',
    width: 110,
  },
  {
    field: 'up_to_date',
    headerName: 'Up to date',
    width: 100,
    valueGetter: (_value, row) => {
      const appliedId = row.applied_template?.id
      const canonicalId = row.applied_template?.product?.template_id
      if (appliedId == null || canonicalId == null) return false
      return appliedId === canonicalId
    },
    display: 'flex',
    renderCell: ({ value }) =>
      value ? (
        <CheckCircleOutline sx={{ color: 'success.main' }} />
      ) : (
        <WarningAmberOutlined sx={{ color: 'warning.main' }} />
      ),
  },
]

export function DeploymentsPanel() {
  const { user } = useAuth()
  const [selectedDeployment, setSelectedDeployment] = useState<Deployment | null>(null)

  const { data: deployments, isLoading } = useQuery({
    queryKey: ['admin-deployments'],
    queryFn: listAllDeployments,
    enabled: Boolean(user),
  })

  return (
    <Box sx={{ width: '100%' }}>
      <DataGrid
        rows={deployments ?? []}
        columns={columns}
        loading={isLoading}
        autoHeight
        disableRowSelectionOnClick
        onRowClick={(params, event) => {
          if ((event.target as HTMLElement).closest('a')) return
          setSelectedDeployment(params.row)
        }}
        initialState={{
          sorting: { sortModel: [{ field: 'last_reconcile_at', sort: 'desc' }] },
        }}
        pageSizeOptions={[25, 50, 100]}
        sx={{
          border: 0,
          '& .MuiDataGrid-columnHeaders': {
            bgcolor: 'action.hover',
          },
          '& .MuiDataGrid-row': {
            cursor: 'pointer',
          },
        }}
      />
      <DeploymentDialog
        deployment={selectedDeployment}
        onClose={() => setSelectedDeployment(null)}
      />
    </Box>
  )
}
