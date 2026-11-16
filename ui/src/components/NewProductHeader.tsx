import { useState } from 'react'
import { Button, Stack, TextField } from '@mui/material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createProduct } from '../api/endpoints'
import { IconPicker } from './image/IconPicker'
import { useObjectUrl } from './image/useObjectUrl'

interface NewProductHeaderProps {
  onCreated: (productId: number) => void
  onError: (error: Error) => void
}

export function NewProductHeader({ onCreated, onError }: NewProductHeaderProps) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [tagline, setTagline] = useState('')
  const [description, setDescription] = useState('')
  const [license, setLicense] = useState('')
  const [category, setCategory] = useState('')
  const [replaces, setReplaces] = useState('')
  const [iconFile, setIconFile] = useState<File | null>(null)

  const createProductMutation = useMutation({
    mutationFn: () =>
      createProduct(
        {
          name: name.trim(),
          tagline: tagline.trim() || null,
          description: description.trim() || null,
          license: license.trim() || null,
          category: category.trim() || null,
          replaces: replaces.trim() || null,
        },
        iconFile || undefined,
      ),
    onSuccess: (product) => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      onCreated(product.id)
    },
    onError,
  })

  const iconPreview = useObjectUrl(iconFile)

  return (
    <Stack spacing={1} sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="flex-start">
        <Stack spacing={0.5} sx={{ minWidth: 0, flex: 1 }}>
          <TextField
            value={name}
            onChange={(e) => setName(e.target.value)}
            variant="standard"
            placeholder="Product name"
            autoFocus
            slotProps={{ input: { sx: { fontSize: '1.5rem', fontWeight: 500 } } }}
          />
          <TextField
            value={tagline}
            onChange={(e) => setTagline(e.target.value)}
            variant="standard"
            placeholder="Tagline: one sentence for the storefront (optional)"
          />
          <TextField
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            variant="standard"
            multiline
            minRows={3}
            placeholder="Description, Markdown (optional)"
          />
          <TextField
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            variant="standard"
            placeholder="Category (optional)"
          />
          <TextField
            value={replaces}
            onChange={(e) => setReplaces(e.target.value)}
            variant="standard"
            placeholder="Replaces (optional)"
          />
          <TextField
            value={license}
            onChange={(e) => setLicense(e.target.value)}
            variant="standard"
            placeholder="License, e.g. AGPL-3.0 (optional)"
          />
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 1 }}>
            <Button
              variant="contained"
              size="small"
              disabled={!name.trim() || createProductMutation.isPending}
              onClick={() => createProductMutation.mutate()}
            >
              {createProductMutation.isPending ? 'Creating...' : 'Create product'}
            </Button>
          </Stack>
        </Stack>
        <IconPicker
          src={iconPreview}
          fallback={name.trim() ? name.trim()[0].toUpperCase() : '?'}
          onPick={setIconFile}
        />
      </Stack>
    </Stack>
  )
}
