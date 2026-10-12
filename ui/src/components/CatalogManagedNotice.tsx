import { Alert, Typography } from '@mui/material'
import type { Product } from '../api/types'

/** The catalog file that declares a product, mirroring the API's error text. */
export function catalogFileFor(product: Product): string {
  const slug = product.slug ?? product.name
  return `products/catalog/${slug}/${slug}.yaml`
}

interface CatalogManagedNoticeProps {
  product: Product
  /** Extra sentence describing what is read-only in this particular place. */
  detail?: string
}

/**
 * Explains why a curated product's fields cannot be edited here.
 *
 * The admin UI does not enforce the rule — the service layer does, identically
 * for REST and the CLI — so this notice exists to name the file an operator
 * should edit instead of leaving them to discover the refusal by clicking.
 */
export function CatalogManagedNotice({ product, detail }: CatalogManagedNoticeProps) {
  return (
    <Alert severity="info" variant="outlined" sx={{ py: 0.5 }}>
      <Typography variant="body2">
        Managed by the catalog. Edit <code>{catalogFileFor(product)}</code> and merge the change
        to update this product{detail ? `; ${detail}` : ''}.
      </Typography>
    </Alert>
  )
}
