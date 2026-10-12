import { useRef, useState } from 'react'
import type { ProductSummary } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { DeployDialog } from './DeployDialog'
import { ClaimSubdomainDialog } from './subdomain/ClaimSubdomainDialog'
import { useMySubdomain } from './subdomain/useMySubdomain'

interface InstallFlowProps {
  product: ProductSummary
  /** A plan to preselect in the deploy dialog. */
  planId?: number
  onClose: () => void
  /** Called instead of `onClose` once a launch succeeds. */
  onLaunched?: () => void
}

/**
 * Launching an app, over whatever page asked for it: the deploy dialog, preceded
 * by a subdomain claim when the user holds none. The claim gates the dialog
 * rather than sitting inside it, so no half-filled form is thrown away to ask
 * for a domain name.
 */
export function InstallFlow({ product, planId, onClose, onLaunched }: InstallFlowProps) {
  const { user } = useAuth()
  const subdomain = useMySubdomain()
  const [claimed, setClaimed] = useState(false)
  // The claim dialog closes itself after a claim; that close must not end the flow.
  const claimedRef = useRef(false)

  if (!user || !subdomain.isSuccess) return null

  if (!subdomain.data.subdomain && !claimed) {
    if (!subdomain.data.domain) return null
    return (
      <ClaimSubdomainDialog
        open
        domain={subdomain.data.domain}
        email={user.email}
        onClaimed={() => {
          claimedRef.current = true
          setClaimed(true)
        }}
        onClose={() => {
          if (!claimedRef.current) onClose()
        }}
      />
    )
  }

  return (
    <DeployDialog
      product={product}
      userId={user.id}
      initialPlanId={planId}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  )
}

export default InstallFlow
