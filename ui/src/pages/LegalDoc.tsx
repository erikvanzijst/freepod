import { useEffect } from 'react'
import { Link as RouterLink, Navigate, useParams } from 'react-router-dom'
import { Box, Button, Container, GlobalStyles, Stack } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PrintIcon from '@mui/icons-material/Print'
import { LEGAL_DOCS } from '../content/legal'
import { LegalDocBody } from '../components/LegalDocBody'

/** Hide on-screen chrome and reset the page background when printing. */
const printGlobals = (
  <GlobalStyles
    styles={{
      '@media print': {
        body: { background: '#fff !important' },
        '.legal-no-print': { display: 'none !important' },
      },
    }}
  />
)

/**
 * Public, print-friendly renderer for a single legal document. Rendered outside
 * the AppShell/landing chrome so it prints cleanly (browser "Save as PDF" yields
 * just the document). Available to anonymous and signed-in visitors alike.
 */
export function LegalDoc() {
  const { slug } = useParams<{ slug: string }>()
  const doc = slug ? LEGAL_DOCS[slug] : undefined

  useEffect(() => {
    if (!doc) return
    const previous = document.title
    document.title = `${doc.title} · Freepod`
    return () => {
      document.title = previous
    }
  }, [doc])

  // Unknown slug → back to home rather than a blank page.
  if (!doc) return <Navigate to="/" replace />

  return (
    <Box sx={{ bgcolor: '#fff', minHeight: '100vh' }}>
      {printGlobals}
      <Box
        className="legal-no-print"
        sx={{
          position: 'sticky',
          top: 0,
          zIndex: 1,
          bgcolor: 'rgba(255,255,255,0.9)',
          backdropFilter: 'blur(8px)',
          borderBottom: '1px solid #e5e7eb',
        }}
      >
        <Container maxWidth="md">
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ py: 1.5 }}>
            <Button component={RouterLink} to="/" startIcon={<ArrowBackIcon />} size="small" sx={{ color: '#374151' }}>
              Back to Freepod
            </Button>
            <Button onClick={() => window.print()} startIcon={<PrintIcon />} size="small" variant="outlined">
              Print / Save as PDF
            </Button>
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="md" sx={{ py: { xs: 4, md: 6 } }}>
        <LegalDocBody content={doc.content} />
      </Container>
    </Box>
  )
}

export default LegalDoc
