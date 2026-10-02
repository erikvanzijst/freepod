import useBaseUrl from '@docusaurus/useBaseUrl'
import catalog from '@site/src/data/catalog.json'

/** Icon, category and summary for a catalog product, read from the synced catalog. */
export default function ProductHeader({ slug }: { slug: string }) {
  const product = catalog.find((p) => p.slug === slug)
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
