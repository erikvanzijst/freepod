import useBaseUrl from '@docusaurus/useBaseUrl'
import { usePluginData } from '@docusaurus/useGlobalData'

interface Product {
  slug: string
  name: string
  description: string
  category: string | null
  icon: string
}

/** Icon, category and summary for a catalog product, read from products/catalog. */
export default function ProductHeader({ slug }: { slug: string }) {
  const { products } = usePluginData('freepod-catalog') as { products: Product[] }
  const product = products.find((p) => p.slug === slug)
  const icon = useBaseUrl(product?.icon ?? '')
  if (!product) throw new Error(`unknown catalog product: ${slug}`)
  return (
    <div className="product-header">
      <img src={icon} alt="" width={48} height={48} />
      <div>
        <div className="product-header__category">{product.category}</div>
        <div>{product.description}</div>
      </div>
    </div>
  )
}
