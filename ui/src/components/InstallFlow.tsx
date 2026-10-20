import { useRef, useState } from 'react'
import type { ProductSummary } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { DeployDialog } from './DeployDialog'
import { ClaimHandleDialog } from './handle/ClaimHandleDialog'
import { useMyHandle } from './handle/useMyHandle'

interface InstallFlowProps {
  product: ProductSummary
  /** The name of a plan to preselect in the deploy dialog. */
  plan?: string
  onClose: () => void
  /** Called instead of `onClose` once a launch succeeds. */
  onLaunched?: () => void
}

/**
 * Launching an app, over whatever page asked for it: the deploy dialog, preceded
 * by a handle claim when the user holds none. The claim gates the dialog
 * rather than sitting inside it, so no half-filled form is thrown away to ask
 * for a handle.
 */
export function InstallFlow({ product, plan, onClose, onLaunched }: InstallFlowProps) {
  const { user } = useAuth()
  const handle = useMyHandle()
  const [claimed, setClaimed] = useState(false)
  // The claim dialog closes itself after a claim; that close must not end the flow.
  const claimedRef = useRef(false)

  if (!user || !handle.isSuccess) return null

  if (!handle.data.handle && !claimed) {
    return (
      <ClaimHandleDialog
        open
        domain={handle.data.domain}
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
      initialPlan={plan}
      onClose={onClose}
      onLaunched={onLaunched}
    />
  )
}

export default InstallFlow
