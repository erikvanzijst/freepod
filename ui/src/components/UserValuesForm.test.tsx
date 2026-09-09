import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { UserValuesForm } from '../components/UserValuesForm'

vi.mock('../api/endpoints', () => ({
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

function Wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('UserValuesForm', () => {
  const schema = {
    type: 'object',
    properties: {
      ingress: {
        type: 'object',
        properties: {
          host: {
            type: 'string',
            title: 'Domain name',
            minLength: 1,
            maxLength: 64,
          },
        },
        required: ['host'],
      },
      user: {
        type: 'object',
        properties: {
          message: {
            type: 'string',
            title: 'Message',
            maxLength: 2000,
          },
        },
      },
    },
    required: ['ingress'],
  }

  const defaults = {
    ingress: {
      host: 'default.example.com',
    },
    user: {
      message: 'Hello World',
    },
  }
  const booleanSchema = {
    type: 'object',
    properties: {
      federation: {
        type: 'object',
        properties: {
          enabled: {
            type: 'boolean',
            title: 'federation.enabled',
          },
        },
      },
    },
  }

  it('renders form when schema is provided', () => {
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={schema}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    expect(screen.getAllByText('Domain name').length).toBeGreaterThan(0)
  })

  it('prefills form with default values', async () => {
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={schema}
        initialValuesJson={defaults}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      const inputs = document.querySelectorAll('input')
      const hostInput = Array.from(inputs).find((input) => input.value === 'default.example.com')
      expect(hostInput).toBeInTheDocument()
    })
  })

  it('calls onChange with defaults when loaded', async () => {
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={schema}
        initialValuesJson={defaults}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({
        ingress: { host: 'default.example.com' },
        user: { message: 'Hello World' },
      })
    })
  })

  it('returns null when schema is null', () => {
    const onChange = vi.fn()
    const { container } = render(
      <UserValuesForm
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    expect(container.firstChild).toBeNull()
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('returns null when schema has no properties', () => {
    const onChange = vi.fn()
    const { container } = render(
      <UserValuesForm
        valuesSchemaJson={{ type: 'object', properties: {} }}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    expect(container.firstChild).toBeNull()
  })

  it('prefills boolean defaults as booleans', async () => {
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={booleanSchema}
        initialValuesJson={{ federation: { enabled: false } }}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({
        federation: { enabled: false },
      })
    })
  })

  it('updates checkbox values as booleans', async () => {
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={booleanSchema}
        initialValuesJson={{ federation: { enabled: false } }}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({
        federation: { enabled: true },
      })
    })
  })

  it('renders HostnameField for fields with title "hostname"', () => {
    const hostnameSchema = {
      type: 'object',
      properties: {
        host: {
          type: 'string',
          title: 'hostname',
        },
      },
    }
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={hostnameSchema}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    // HostnameField renders a "Hostname" labeled input in custom mode (no wildcard domains)
    expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
    // It should NOT render a regular TextField with label "hostname"
    expect(screen.queryByLabelText('hostname')).not.toBeInTheDocument()
  })

  it('renders HostnameField case-insensitively', () => {
    const hostnameSchema = {
      type: 'object',
      properties: {
        domain: {
          type: 'string',
          title: 'Hostname',
        },
      },
    }
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={hostnameSchema}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    // HostnameField's custom-mode input has label "Hostname"
    expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
  })

  it('prefills form with schema default values', async () => {
    const schemaWithDefaults = {
      type: 'object',
      properties: {
        host: {
          type: 'string',
          title: 'hostname',
        },
        mattermost: {
          type: 'object',
          properties: {
            extraEnv: {
              type: 'object',
              properties: {
                TZ: {
                  type: 'string',
                  title: 'Timezone',
                  default: 'Europe/Amsterdam',
                },
              },
            },
          },
        },
      },
      required: ['host'],
    }
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={schemaWithDefaults}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({
        mattermost: { extraEnv: { TZ: 'Europe/Amsterdam' } },
      })
    })
  })

  it('prefers initialValuesJson over schema default annotations', async () => {
    const schemaWithDefaults = {
      type: 'object',
      properties: {
        region: {
          type: 'string',
          title: 'Region',
          default: 'us-east-1',
        },
      },
    }
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={schemaWithDefaults}
        initialValuesJson={{ region: 'eu-west-1' }}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith({ region: 'eu-west-1' })
    })
  })

  it('renders regular TextField for non-hostname fields', () => {
    const regularSchema = {
      type: 'object',
      properties: {
        message: {
          type: 'string',
          title: 'Message',
        },
      },
    }
    const onChange = vi.fn()
    render(
      <UserValuesForm
        valuesSchemaJson={regularSchema}
        initialValuesJson={null}
        onChange={onChange}
      />,
      { wrapper: Wrapper },
    )

    expect(screen.getByLabelText('Message')).toBeInTheDocument()
  })
})
