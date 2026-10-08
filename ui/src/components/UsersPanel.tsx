import { Box, InputAdornment, TextField } from '@mui/material'
import { Search } from '@mui/icons-material'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { listAllDeployments, listUsers } from '../api/endpoints'
import { useAuth } from '../state/AuthContext'
import type { User } from '../api/types'
import { formatLocalIso, parseUtc } from '../utils/formatDate'

interface UserRow extends User {
  deployment_count: number
}

const columns: GridColDef<UserRow>[] = [
  { field: 'id', headerName: 'ID', width: 80 },
  { field: 'email', headerName: 'Email', flex: 1.5, minWidth: 200 },
  {
    field: 'is_admin',
    headerName: 'Admin',
    width: 90,
    renderCell: ({ value }) => (value ? 'Yes' : 'No'),
  },
  { field: 'wildcard_domain', headerName: 'Subdomain', flex: 1.5, minWidth: 200 },
  {
    field: 'created_at',
    headerName: 'Joined',
    flex: 1,
    minWidth: 160,
    valueGetter: (_value, row) => (row.created_at ? parseUtc(row.created_at) : null),
    renderCell: ({ value }) => (value ? formatLocalIso(value as Date) : ''),
  },
  { field: 'deployment_count', headerName: 'Deployments', width: 120 },
]

export function UsersPanel() {
  const { user } = useAuth()
  const [search, setSearch] = useState('')

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: listUsers,
    enabled: Boolean(user),
  })
  const { data: deployments, isLoading: deploymentsLoading } = useQuery({
    queryKey: ['admin-deployments'],
    queryFn: listAllDeployments,
    enabled: Boolean(user),
  })

  const rows = useMemo<UserRow[]>(() => {
    const counts = new Map<number, number>()
    for (const d of deployments ?? []) {
      counts.set(d.user_id, (counts.get(d.user_id) ?? 0) + 1)
    }
    return (users ?? []).map((u) => ({ ...u, deployment_count: counts.get(u.id) ?? 0 }))
  }, [users, deployments])

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => r.email.toLowerCase().includes(q))
  }, [rows, search])

  return (
    <Box sx={{ width: '100%' }}>
      <TextField
        size="small"
        placeholder="Search by email"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ mb: 1, width: 320 }}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <Search fontSize="small" />
            </InputAdornment>
          ),
        }}
      />
      <DataGrid
        rows={filteredRows}
        columns={columns}
        loading={usersLoading || deploymentsLoading}
        autoHeight
        disableRowSelectionOnClick
        initialState={{
          sorting: { sortModel: [{ field: 'created_at', sort: 'desc' }] },
        }}
        pageSizeOptions={[25, 50, 100]}
        sx={{
          border: 0,
          '& .MuiDataGrid-columnHeaders': {
            bgcolor: 'action.hover',
          },
        }}
      />
    </Box>
  )
}
