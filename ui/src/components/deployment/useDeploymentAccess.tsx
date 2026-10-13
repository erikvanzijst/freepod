import { useEffect, useRef, useState } from 'react'
import type { Deployment } from '../../api/types'
import { isTransitionalStatus } from '../../utils/deploymentStatus'
import { useSftpCredentials } from '../SftpAccessPanel'
import { SftpAccessDialog } from '../SftpAccessDialog'
import { useDatabaseDetails } from '../DatabasePanel'
import { DatabaseAccessDialog } from '../DatabaseAccessDialog'

/**
 * Files and Database access: each appears only once its details resolve, so
 * products without them show nothing. Nothing is requested until `enabled`,
 * since every row asking on mount is two calls per app. Returns the dialogs to
 * render.
 */
export function useDeploymentAccess(userId: number, deployment: Deployment, enabled = true) {
  const [open, setOpen] = useState<'files' | 'database' | null>(null)
  const sftp = useSftpCredentials(userId, deployment.id, enabled)
  const database = useDatabaseDetails(userId, deployment.id, enabled)
  // An absent database or SFTP account on a transitional deployment is the
  // deployment's own state, so ask again the moment it settles. Only on that
  // change: refetch() ignores `enabled`, and on expand it would cancel and
  // repeat the request enabling just started.
  const transitional = isTransitionalStatus(deployment.status)
  const wasTransitional = useRef(transitional)
  const { data: sftpData, refetch: refetchSftp } = sftp
  const { data: dbData, refetch: refetchDb } = database
  useEffect(() => {
    const settledNow = wasTransitional.current && !transitional
    wasTransitional.current = transitional
    if (!settledNow || !enabled) return
    if (!sftpData) refetchSftp()
    if (!dbData) refetchDb()
  }, [transitional, enabled, sftpData, dbData, refetchSftp, refetchDb])

  const dialogs = (
    <>
      {open === 'files' && (
        <SftpAccessDialog userId={userId} deploymentId={deployment.id} hostname={deployment.hostname} onClose={() => setOpen(null)} />
      )}
      {open === 'database' && (
        <DatabaseAccessDialog userId={userId} deploymentId={deployment.id} hostname={deployment.hostname} onClose={() => setOpen(null)} />
      )}
    </>
  )

  return {
    files: sftpData ? () => setOpen('files') : undefined,
    database: dbData ? () => setOpen('database') : undefined,
    dialogs,
  }
}
