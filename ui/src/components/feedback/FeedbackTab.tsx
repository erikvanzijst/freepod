import { Box, ButtonBase } from '@mui/material'
import RateReviewOutlinedIcon from '@mui/icons-material/RateReviewOutlined'
import { accent, fg, ink, SANS } from '../landing/landingTokens'
import { FEEDBACK_UI_ATTR } from './capture'

export function FeedbackTab({ onClick }: { onClick: () => void }) {
  return (
    <ButtonBase
      onClick={onClick}
      aria-label="Feedback"
      {...{ [FEEDBACK_UI_ATTR]: '' }}
      sx={{
        position: 'fixed',
        right: 0,
        top: '50%',
        transform: 'translateY(-50%)',
        zIndex: (theme) => theme.zIndex.speedDial,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 1,
        px: { xs: 0.75, sm: 1 },
        py: { xs: 1, sm: 1.5 },
        color: fg.primary,
        background: `linear-gradient(180deg, ${ink.raised}, #161d38)`,
        border: '1px solid rgba(255,255,255,0.12)',
        borderRight: 0,
        borderRadius: '10px 0 0 10px',
        boxShadow: '0 6px 24px rgba(0,0,0,0.35)',
        fontFamily: SANS,
        fontWeight: 600,
        fontSize: 13,
        letterSpacing: '0.02em',
        transition: 'padding 120ms ease, color 120ms ease',
        '&:hover': { color: accent.blue, pr: { sm: 1.5 } },
        '&.Mui-focusVisible': { outline: `2px solid ${accent.blue}`, outlineOffset: 2 },
      }}
    >
      <RateReviewOutlinedIcon fontSize="small" sx={{ color: accent.blue }} />
      <Box
        component="span"
        aria-hidden
        sx={{
          display: { xs: 'none', sm: 'block' },
          writingMode: 'vertical-rl',
          transform: 'rotate(180deg)',
        }}
      >
        Feedback
      </Box>
    </ButtonBase>
  )
}

export default FeedbackTab
