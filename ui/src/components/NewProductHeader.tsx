import { useCallback, useRef, useState } from 'react'
import {
  Avatar,
  Badge,
  Button,
  Stack,
  TextField,
} from '@mui/material'
import AddPhotoAlternateIcon from '@mui/icons-material/AddPhotoAlternate'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createProduct } from '../api/endpoints'

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
  const [iconPreview, setIconPreview] = useState<string | null>(null)
  const iconInputRef = useRef<HTMLInputElement>(null)

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

  const handleIconClick = useCallback(() => {
    iconInputRef.current?.click()
  }, [])

  const handleIconChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return
      if (iconInputRef.current) iconInputRef.current.value = ''
      if (!file.type.startsWith('image/')) return
      setIconFile(file)
      const url = URL.createObjectURL(file)
      setIconPreview(url)
    },
    [],
  )

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
        <Badge
          overlap="circular"
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          badgeContent={
            <AddPhotoAlternateIcon
              sx={{
                width: 18,
                height: 18,
                bgcolor: 'primary.main',
                color: 'white',
                borderRadius: '50%',
                p: 0.3,
              }}
            />
          }
          sx={{ cursor: 'pointer', flexShrink: 0 }}
          onClick={handleIconClick}
        >
          <Avatar
            src={iconPreview || undefined}
            variant="rounded"
            sx={{ width: 64, height: 64, bgcolor: 'action.hover' }}
          >
            {name.trim() ? name.trim()[0].toUpperCase() : '?'}
          </Avatar>
        </Badge>
      </Stack>
    </Stack>
  )
}
