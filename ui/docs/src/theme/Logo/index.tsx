import type { ReactNode } from 'react'
import useBaseUrl from '@docusaurus/useBaseUrl'
import { useThemeConfig } from '@docusaurus/theme-common'
import type { Props } from '@theme/Logo'

/**
 * The navbar brand, linking to the Freepod app at "/" like the app's own logo.
 * Replaces the theme's Logo because that one always prefixes the /docs/ baseUrl.
 */
export default function Logo({ imageClassName, titleClassName, ...rest }: Props): ReactNode {
  const {
    navbar: { title, logo },
  } = useThemeConfig()
  const src = useBaseUrl(logo?.src ?? '')
  const image = logo && <img src={src} alt={logo.alt ?? ''} height={logo.height} width={logo.width} />

  return (
    <a href="/" {...rest}>
      {image && (imageClassName ? <div className={imageClassName}>{image}</div> : image)}
      {title != null && <b className={titleClassName}>{title}</b>}
    </a>
  )
}
