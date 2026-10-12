import {
  Avatar,
  Box,
  Card,
  CardActionArea,
  CardContent,
  Grid,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import { useMemo } from 'react'
import { resolveApiPath } from '../api/client'
import type { Product } from '../api/types'

interface ProductListProps {
  products?: Product[]
  selectedProductId: number | 'new' | null
  onSelectProduct: (productId: number | 'new') => void
  showNewCard?: boolean
}

export function ProductList({ products, selectedProductId, onSelectProduct, showNewCard }: ProductListProps) {
  const sorted = useMemo(
    () => [...(products ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [products],
  )

  return (
    <Grid container spacing={2}>
      {sorted.map((product) => (
        <Grid key={product.id} size={{ xs: 6, sm: 4, md: 3 }}>
          <Card
            sx={{
              height: '100%',
              border: selectedProductId === product.id
                ? '2px solid'
                : '2px solid transparent',
              borderColor: selectedProductId === product.id
                ? 'primary.main'
                : 'transparent',
            }}
          >
            <CardActionArea
              onClick={() => onSelectProduct(product.id)}
              sx={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'stretch' }}
            >
              <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 1 }}>
                <Avatar
                  src={product.icon_url ? resolveApiPath(product.icon_url) : undefined}
                  alt={product.name}
                  variant="rounded"
                  sx={{ width: 48, height: 48 }}
                >
                  {product.name[0]}
                </Avatar>
                <Box sx={{ minWidth: 0, width: '100%' }}>
                  <Typography variant="subtitle2" noWrap>{product.name}</Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }}
                  >
                    {product.tagline || product.description || 'No description'}
                  </Typography>
                </Box>
              </CardContent>
            </CardActionArea>
          </Card>
        </Grid>
      ))}
      {showNewCard && (
        <Grid size={{ xs: 6, sm: 4, md: 3 }}>
          <Card
            sx={{
              height: '100%',
              border: selectedProductId === 'new'
                ? '2px solid'
                : '2px dashed',
              borderColor: selectedProductId === 'new'
                ? 'primary.main'
                : 'divider',
            }}
          >
            <CardActionArea
              onClick={() => onSelectProduct('new')}
              sx={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'stretch' }}
            >
              <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', gap: 1 }}>
                <Avatar
                  variant="rounded"
                  sx={{ width: 48, height: 48, bgcolor: 'action.hover' }}
                >
                  <AddIcon />
                </Avatar>
                <Typography variant="subtitle2" color="text.secondary">
                  New product
                </Typography>
              </CardContent>
            </CardActionArea>
          </Card>
        </Grid>
      )}
    </Grid>
  )
}
