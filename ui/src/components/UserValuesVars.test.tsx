import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { UserValuesForm, flattenSchema } from '../components/UserValuesForm'

vi.mock('../api/endpoints', () => ({
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

function Wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

/** A schema with both channels, as a product that has adopted vars would have. */
const MIXED_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    host: { type: 'string', title: 'Host' },
    LOG_LEVEL: { type: 'string', title: 'Log level', 'x-caelus-target': 'runtime' },
    SIGNUPS_ALLOWED: {
      type: 'boolean',
      title: 'Allow signups',
      'x-caelus-target': 'runtime',
      default: false,
    },
    ADMIN_TOKEN: {
      type: 'string',
      title: 'Admin token',
      'x-caelus-target': 'runtime',
      'x-caelus-sensitive': true,
    },
  },
}

const UNMARKED_SCHEMA = {
  type: 'object',
  properties: {
    host: { type: 'string', title: 'Host' },
    replicas: { type: 'integer', title: 'Replicas' },
  },
}

describe('flattenSchema routing markers', () => {
  it('carries target and sensitive onto the field', () => {
    const fields = flattenSchema(MIXED_SCHEMA)
    const byPath = Object.fromEntries(fields.map((f) => [f.path, f]))

    expect(byPath.host.target).toBe('chart')
    expect(byPath.host.sensitive).toBe(false)
    expect(byPath.LOG_LEVEL.target).toBe('runtime')
    expect(byPath.LOG_LEVEL.sensitive).toBe(false)
    expect(byPath.ADMIN_TOKEN.target).toBe('runtime')
    expect(byPath.ADMIN_TOKEN.sensitive).toBe(true)
  })

  it('treats an unmarked schema as entirely chart values', () => {
    for (const field of flattenSchema(UNMARKED_SCHEMA)) {
      expect(field.target).toBe('chart')
      expect(field.sensitive).toBe(false)
    }
  })

  it('ignores a marker on a nested property', () => {
    // The platform rejects such a schema outright; the UI must not route on it
    // in the meantime, because a nested var has no environment variable name.
    const fields = flattenSchema({
      type: 'object',
      properties: {
        group: {
          type: 'object',
          properties: {
            NESTED: { type: 'string', 'x-caelus-target': 'runtime' },
          },
        },
      },
    })
    expect(fields).toHaveLength(1)
    expect(fields[0].path).toBe('group.NESTED')
    expect(fields[0].target).toBe('chart')
  })
})

describe('UserValuesForm partitioning', () => {
  it('splits a mixed schema into two payloads', async () => {
    const onChange = vi.fn()
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        onChange={onChange}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({ host: 'app.example.test' })
    })
    // The chart half carries no runtime property...
    const chart = onChange.mock.calls.at(-1)![0] as Record<string, unknown>
    expect(chart).not.toHaveProperty('LOG_LEVEL')
    expect(chart).not.toHaveProperty('ADMIN_TOKEN')

    // ...and the vars half carries only runtime ones, as strings.
    const vars = onVarsChange.mock.calls.at(-1)![0] as Record<string, { value: string }>
    expect(vars).toEqual({ SIGNUPS_ALLOWED: { value: 'false' } })
    expect(vars).not.toHaveProperty('host')
  })

  it('submits a typed var as a string whatever the schema declares', async () => {
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        onChange={vi.fn()}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    fireEvent.click(screen.getByLabelText('Allow signups'))

    await waitFor(() => {
      const vars = onVarsChange.mock.calls.at(-1)![0]
      expect(vars.SIGNUPS_ALLOWED).toEqual({ value: 'true' })
    })
  })

  it('submits everything as chart values for an unmarked schema', async () => {
    const onChange = vi.fn()
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={UNMARKED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test', replicas: 2 }}
        onChange={onChange}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({ host: 'app.example.test', replicas: 2 })
    })
    expect(onVarsChange).toHaveBeenLastCalledWith({})
  })
})

describe('a sensitive var field', () => {
  const currentVars = {
    LOG_LEVEL: { value: 'debug', sensitive: false },
    ADMIN_TOKEN: { sensitive: true },
  }

  it('renders as a password input with no stored value shown', async () => {
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={vi.fn()}
      />,
      { wrapper: Wrapper },
    )

    const input = screen.getByLabelText('Admin token') as HTMLInputElement
    expect(input.type).toBe('password')
    expect(input.value).toBe('')
    expect(screen.getByText(/leave blank to keep it/i)).toBeInTheDocument()
  })

  it('submits no value while untouched', async () => {
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(onVarsChange).toHaveBeenCalled())
    const vars = onVarsChange.mock.calls.at(-1)![0] as Record<string, { value?: string }>

    // An empty string would wipe the secret; a null would delete the var.
    // Neither may be inferred from a field the user never touched.
    expect(vars.ADMIN_TOKEN?.value).toBeUndefined()
    expect('ADMIN_TOKEN' in vars).toBe(false)
    // The non-sensitive var beside it is prefilled and round-trips unchanged.
    expect(vars.LOG_LEVEL).toEqual({ value: 'debug' })
  })

  it('submits the new value once touched', async () => {
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    fireEvent.change(screen.getByLabelText('Admin token'), { target: { value: 'rotated' } })

    await waitFor(() => {
      const vars = onVarsChange.mock.calls.at(-1)![0]
      expect(vars.ADMIN_TOKEN).toEqual({ value: 'rotated' })
    })
  })

  it('offers no reveal control while empty', () => {
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={vi.fn()}
      />,
      { wrapper: Wrapper },
    )

    // The stored value was never sent to the browser, so there is nothing to
    // reveal until the user types something of their own.
    expect(screen.queryByLabelText(/show|reveal/i)).toBeNull()
  })

  it('reveals what the user typed, and hides it again', () => {
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={vi.fn()}
      />,
      { wrapper: Wrapper },
    )

    const input = screen.getByLabelText('Admin token') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'rotated' } })

    fireEvent.click(screen.getByLabelText('Show password'))
    expect(input.type).toBe('text')
    expect(input.value).toBe('rotated')

    fireEvent.click(screen.getByLabelText('Hide password'))
    expect(input.type).toBe('password')
  })

  it('re-masks a field that is cleared after being revealed', () => {
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        initialVars={currentVars}
        onChange={vi.fn()}
        onVarsChange={vi.fn()}
      />,
      { wrapper: Wrapper },
    )

    const input = screen.getByLabelText('Admin token') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'rotated' } })
    fireEvent.click(screen.getByLabelText('Show password'))
    fireEvent.change(input, { target: { value: '' } })

    // Whatever is typed next starts masked again.
    expect(input.type).toBe('password')
    expect(screen.queryByLabelText(/show|reveal/i)).toBeNull()
  })

  it('does not submit an empty var the deployment does not already hold', async () => {
    const onVarsChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={MIXED_SCHEMA}
        initialValuesJson={{ host: 'app.example.test' }}
        onChange={vi.fn()}
        onVarsChange={onVarsChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => expect(onVarsChange).toHaveBeenCalled())
    const vars = onVarsChange.mock.calls.at(-1)![0]
    expect('LOG_LEVEL' in vars).toBe(false)
  })
})
