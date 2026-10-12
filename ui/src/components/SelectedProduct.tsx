import { useCallback, useRef, useState } from 'react'
import {
  Avatar,
  Badge,
  Button,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteProduct, getProductListing, updateProduct } from '../api/endpoints'
import { resolveApiPath } from '../api/client'
import type { Product } from '../api/types'
import { formatDateTime } from '../utils/format'
import { CatalogManagedNotice } from './CatalogManagedNotice'
import { ConfirmDeleteDialog } from './ConfirmDeleteDialog'
import { InlineEditField } from './InlineEditField'
import { ProductVisibilityControl } from './ProductVisibilityControl'

interface SelectedProductProps {
  product: Product
  onError: (error: Error) => void
}

export function SelectedProduct({ product, onError }: SelectedProductProps) {
  const queryClient = useQueryClient()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState('')
  const iconInputRef = useRef<HTMLInputElement>(null)
  // Everything the catalog declares is read-only for a curated product. Only
  // `visibility` stays editable, since it is runtime state the catalog does not
  // own and withdrawing a product is often incident response.
  const curated = product.curated

  // The license is listing content, which product reads leave out.
  const listingQuery = useQuery({
    queryKey: ['product-listing', product.id],
    queryFn: () => getProductListing(product.id),
  })

  const updateProductMutation = useMutation({
    mutationFn: (payload: {
      name?: string
      tagline?: string | null
      description?: string | null
      license?: string | null
      category?: string | null
      replaces?: string | null
    }) => updateProduct(product.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: ['product-listing', product.id] })
    },
    onError,
  })

  const uploadIconMutation = useMutation({
    mutationFn: (file: File) => updateProduct(product.id, {}, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
    onError,
  })

  const handleIconClick = useCallback(() => {
    iconInputRef.current?.click()
  }, [])

  const handleIconChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return
      if (iconInputRef.current) iconInputRef.current.value = ''
      if (!file.type.startsWith('image/')) return
      uploadIconMutation.mutate(file)
    },
    [uploadIconMutation],
  )

  const deleteProductMutation = useMutation({
    mutationFn: () => deleteProduct(product.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
    onError,
  })

  function saveName() {
    const trimmed = draftName.trim()
    if (trimmed && trimmed !== product.name) {
      updateProductMutation.mutate({ name: trimmed })
    }
    setEditingName(false)
  }

  return (
    <Stack spacing={1} sx={{ p: 2 }}>
      <input
        ref={iconInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleIconChange}
      />
      <Stack direction="row" spacing={2} alignItems="flex-start">
        <Stack spacing={0.5} sx={{ minWidth: 0, flex: 1 }}>
          {curated ? (
            <Typography variant="h5">{product.name}</Typography>
          ) : editingName ? (
            <TextField
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveName()
                if (e.key === 'Escape') setEditingName(false)
              }}
              variant="standard"
              autoFocus
              slotProps={{ input: { sx: { fontSize: '1.5rem', fontWeight: 500 } } }}
            />
          ) : (
            <Typography
              variant="h5"
              onClick={() => {
                setDraftName(product.name)
                setEditingName(true)
              }}
              sx={{ cursor: 'pointer', '&:hover': { color: 'primary.main' } }}
            >
              {product.name}
            </Typography>
          )}
          <InlineEditField
            value={product.tagline}
            emptyText="No tagline set."
            readOnly={curated}
            onSave={(tagline) => updateProductMutation.mutate({ tagline })}
          />
          <InlineEditField
            value={product.description}
            emptyText="No description provided."
            multiline
            readOnly={curated}
            onSave={(description) => updateProductMutation.mutate({ description })}
          />
          <InlineEditField
            value={product.category}
            emptyText="No category set."
            readOnly={curated}
            onSave={(category) => updateProductMutation.mutate({ category })}
          />
          <InlineEditField
            value={product.replaces}
            emptyText="No 'replaces' set."
            readOnly={curated}
            onSave={(replaces) => updateProductMutation.mutate({ replaces })}
          />
          <InlineEditField
            value={listingQuery.data?.license}
            emptyText="No license set."
            readOnly={curated}
            onSave={(license) => updateProductMutation.mutate({ license })}
          />
          {curated && (
            <CatalogManagedNotice
              product={product}
              detail="visibility stays editable here"
            />
          )}
          <Stack direction="row" spacing={2} alignItems="flex-start" sx={{ pt: 1 }}>
            <ProductVisibilityControl product={product} onError={onError} />
          </Stack>
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography variant="body2" color="text.secondary">
              Created {formatDateTime(product.created_at)}
            </Typography>
            {/* Deletion of a curated product is refused even with force: the
                next reconciliation would recreate it under a new id. */}
            <Button
              variant="outlined"
              color="secondary"
              size="small"
              disabled={curated}
              title={
                curated
                  ? 'Remove the product from the catalog first, then delete it.'
                  : undefined
              }
              onClick={() => setConfirmingDelete(true)}
            >
              Delete
            </Button>
            {confirmingDelete && (
              <ConfirmDeleteDialog
                name={product.name}
                subject="product"
                onConfirm={() => {
                  setConfirmingDelete(false)
                  deleteProductMutation.mutate()
                }}
                onCancel={() => setConfirmingDelete(false)}
              />
            )}
          </Stack>
        </Stack>
        {/* The icon is catalog state as well, so a curated product loses the
            edit affordance rather than offering an upload the API refuses. */}
        <Badge
          overlap="circular"
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          badgeContent={
            curated ? undefined : (
              <EditIcon
                sx={{
                  width: 18,
                  height: 18,
                  bgcolor: 'primary.main',
                  color: 'white',
                  borderRadius: '50%',
                  p: 0.3,
                }}
              />
            )
          }
          sx={{ cursor: curated ? 'default' : 'pointer', flexShrink: 0 }}
          onClick={curated ? undefined : handleIconClick}
        >
          <Avatar
            src={product.icon_url ? resolveApiPath(product.icon_url) : undefined}
            alt={product.name}
            variant="rounded"
            sx={{ width: 64, height: 64 }}
          >
            {product.name[0]}
          </Avatar>
        </Badge>
      </Stack>
    </Stack>
  )
}
