import {
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  type SelectChangeEvent,
} from '@mui/material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateProduct } from '../api/endpoints'
import type { Product, ProductVisibility } from '../api/types'

interface ProductVisibilityControlProps {
  product: Product
  onError: (error: Error) => void
}

const HELPER_TEXT: Record<ProductVisibility, string> = {
  public: 'Offered to end users in the product catalog.',
  unlisted: 'Available via the API and CLI, hidden from the storefront.',
  admin: 'Hidden from end users; visible to administrators only.',
}

/**
 * Publish, unlist or withdraw a product from the end-user catalog.
 *
 * Visibility is runtime state rather than catalog state, so this control stays
 * available for every product — a change takes effect immediately instead of
 * waiting for a merge and a rollout.
 */
export function ProductVisibilityControl({ product, onError }: ProductVisibilityControlProps) {
  const queryClient = useQueryClient()

  const visibilityMutation = useMutation({
    mutationFn: (visibility: ProductVisibility) => updateProduct(product.id, { visibility }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['products'] }),
    onError,
  })

  function handleChange(event: SelectChangeEvent) {
    const next = event.target.value as ProductVisibility
    if (next !== product.visibility) visibilityMutation.mutate(next)
  }

  return (
    <FormControl size="small" sx={{ minWidth: 220 }}>
      <InputLabel id={`product-visibility-label-${product.id}`}>Visibility</InputLabel>
      <Select
        labelId={`product-visibility-label-${product.id}`}
        label="Visibility"
        value={product.visibility}
        onChange={handleChange}
        disabled={visibilityMutation.isPending}
      >
        <MenuItem value="public">Public</MenuItem>
        <MenuItem value="unlisted">Unlisted</MenuItem>
        <MenuItem value="admin">Admin only</MenuItem>
      </Select>
      <FormHelperText>{HELPER_TEXT[product.visibility]}</FormHelperText>
    </FormControl>
  )
}
