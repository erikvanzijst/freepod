import useBaseUrl from '@docusaurus/useBaseUrl'
import { usePluginData } from '@docusaurus/useGlobalData'

interface Product {
  slug: string
  name: string
  tagline: string | null
  category: string | null
  icon: string | null
}

/** Icon, category and summary for a catalog product, read from products/catalog. */
export default function ProductHeader({ slug }: { slug: string }) {
  const { products } = usePluginData('freepod-catalog') as { products: Product[] }
  const product = products.find((p) => p.slug === slug)
  const icon = useBaseUrl(product?.icon ?? '')
  if (!product) throw new Error(`unknown catalog product: ${slug}`)
  return (
    <div className="product-header">
      {product.icon && <img src={icon} alt="" width={48} height={48} />}
      <div>
        <div className="product-header__category">{product.category}</div>
        {product.tagline && <div>{product.tagline}</div>}
      </div>
    </div>
  )
}
