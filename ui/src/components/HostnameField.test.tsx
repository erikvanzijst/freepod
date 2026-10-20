import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HostnameField } from './HostnameField'

const checkHostnameMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  checkHostname: (...args: unknown[]) => checkHostnameMock(...args),
}))

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('HostnameField', () => {
  describe('mode selection', () => {
    it('defaults to custom mode when the account has no domain name yet', () => {
      const onChange = vi.fn()
      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.queryByText('Freepod address')).not.toBeInTheDocument()
    })

    it('defaults to Freepod mode when the account holds a domain name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.getByText('-alice.freepod.app')).toBeInTheDocument()
      expect(screen.getByText('Freepod address')).toBeInTheDocument()
      expect(screen.getByText('Custom domain')).toBeInTheDocument()
    })

    it('switches from Freepod to custom mode', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      fireEvent.click(screen.getByText('Custom domain'))
      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
    })

    it('switches from custom back to Freepod mode', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      fireEvent.click(screen.getByText('Custom domain'))
      fireEvent.click(screen.getByText('Freepod address'))
      expect(screen.getByText('-alice.freepod.app')).toBeInTheDocument()
    })
  })

  describe('value composition', () => {
    it('combines the app name with the account domain name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'myapp-alice.freepod.app', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'myapp' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('myapp-alice.freepod.app')
      })
    })

    it('uses full value in custom mode', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'myapp.custom.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'myapp.custom.com' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('myapp.custom.com')
      })
    })

    it('does not call onChange for an empty app name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      expect(onChange).not.toHaveBeenCalled()
    })
  })

  describe('debounced validation', () => {
    it('calls checkHostname after debounce', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'test.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'test.example.com' } })

      // Synchronously after typing: API should not yet be called (debounce pending)
      expect(checkHostnameMock).not.toHaveBeenCalled()

      // After the debounce fires
      await waitFor(() => {
        expect(checkHostnameMock).toHaveBeenCalledWith('test.example.com')
      })
    })

    it('does not call API when input is empty', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockClear()

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      // Type something then clear it
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'x' } })
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: '' } })

      await act(() => vi.advanceTimersByTimeAsync(500))
      expect(checkHostnameMock).not.toHaveBeenCalled()
    })

    it('shows success icon when hostname is usable', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'good.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'good.example.com' } })

      await waitFor(() => {
        expect(screen.getByTestId('CheckCircleIcon')).toBeInTheDocument()
      })
    })

    it('shows error icon and helper text for invalid hostname', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'bad', usable: false, reason: 'invalid' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'bad' } })

      await waitFor(() => {
        expect(screen.getByTestId('ErrorIcon')).toBeInTheDocument()
        expect(screen.getByText('Invalid hostname format')).toBeInTheDocument()
      })
    })

    it('shows in-use error message', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'taken.example.com', usable: false, reason: 'in_use' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'taken.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Already in use')).toBeInTheDocument()
      })
    })

    it('shows reserved error message', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'smtp.example.com', usable: false, reason: 'reserved' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'smtp.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Hostname is reserved')).toBeInTheDocument()
      })
    })
  })

  describe('app name dot stripping', () => {
    it('strips dots from the app name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'foobar-alice.freepod.app', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'foo.bar' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('foobar-alice.freepod.app')
      })
    })

    it('allows dashes in the app name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'my-photos-alice.freepod.app', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'my-photos' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('my-photos-alice.freepod.app')
      })
    })

    it('allows dots in custom mode', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'foo.bar.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'foo.bar.example.com' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('foo.bar.example.com')
      })
    })
  })

  describe('claimed reason label', () => {
    it('names another account as the holder', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'app.other.example.com', usable: false, reason: 'claimed' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.other.example.com' } })

      await waitFor(() => {
        expect(
          screen.getByText('That address belongs to another account'),
        ).toBeInTheDocument()
      })
    })

    it('renders no message for the retired nested_subdomain reason', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'a.b.example.com', usable: false, reason: 'nested_subdomain' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'a.b.example.com' } })

      await waitFor(() => {
        expect(
          screen.queryByText('Only a single subdomain level is allowed'),
        ).not.toBeInTheDocument()
      })
    })
  })

  describe('CNAME target', () => {
    it('uses the provided cnameTarget in the not_resolving message and helper text', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'app.example.com', usable: false, reason: 'not_resolving' })

      render(<HostnameField value="" onChange={onChange} suffix={null} cnameTarget="dev.freepod.app" />)

      // Custom-mode helper text reflects the environment-specific target
      expect(
        screen.getByText(
          'Point your domain at Freepod: a CNAME record → dev.freepod.app, or for a root domain (example.com), A/AAAA records with the same addresses as dev.freepod.app',
        ),
      ).toBeInTheDocument()

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.example.com' } })

      await waitFor(() => {
        expect(
          screen.getByText(
            'Create a CNAME record pointing to dev.freepod.app, or for a root domain, A/AAAA records with the same addresses as dev.freepod.app',
          ),
        ).toBeInTheDocument()
      })
    })

    it('falls back to freepod.app when cnameTarget is not provided', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'app.example.com', usable: false, reason: 'not_resolving' })

      render(<HostnameField value="" onChange={onChange} suffix={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.example.com' } })

      await waitFor(() => {
        expect(
          screen.getByText(
            'Create a CNAME record pointing to freepod.app, or for a root domain, A/AAAA records with the same addresses as freepod.app',
          ),
        ).toBeInTheDocument()
      })
    })
  })

  describe('async account domain name', () => {
    it('switches to Freepod mode when the account domain name arrives after mount', () => {
      const onChange = vi.fn()
      const { rerender } = render(
        <HostnameField value="" onChange={onChange} suffix={null} />,
      )

      // Initially in custom mode: no account domain name yet
      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.queryByText('Freepod address')).not.toBeInTheDocument()

      // Domains arrive asynchronously
      rerender(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      // Switched to Freepod mode, rendering the account's own suffix
      expect(screen.getByText('Freepod address')).toBeInTheDocument()
      expect(screen.getByText('-alice.freepod.app')).toBeInTheDocument()
    })
  })

  describe('initial value sync', () => {
    it('splits an initial tenant hostname back into its app name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value="myapp-alice.freepod.app"
          onChange={onChange}
          suffix="-alice.freepod.app"
        />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('myapp')
    })

    it('treats another account\'s address as a custom value', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="myapp-bob.freepod.app" onChange={onChange} suffix="-alice.freepod.app" />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('myapp-bob.freepod.app')
    })

    it('falls back to custom mode when the value does not end in the suffix', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value="myapp.other.com"
          onChange={onChange}
          suffix="-alice.freepod.app"
        />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('myapp.other.com')
    })
  })

  describe('external error prop', () => {
    it('displays external error message', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value=""
          onChange={onChange}
          suffix={null}
          error="Server rejected hostname"
        />,
      )

      expect(screen.getByText('Server rejected hostname')).toBeInTheDocument()
    })
  })

  describe('default prefix prefill', () => {
    it('prefills the name under the account domain', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'hello-world-alice.freepod.app', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" defaultPrefix="hello-world" />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('hello-world')
      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('hello-world-alice.freepod.app')
      })
    })

    it('prefills once the account domain arrives after mount', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'hello-world-alice.freepod.app', usable: true, reason: null })

      const { rerender } = render(
        <HostnameField value="" onChange={onChange} suffix={null} defaultPrefix="hello-world" />,
      )
      expect(screen.getByLabelText('Hostname')).toHaveValue('')

      rerender(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" defaultPrefix="hello-world" />,
      )

      await waitFor(() => {
        expect(screen.getByLabelText('Hostname')).toHaveValue('hello-world')
        expect(onChange).toHaveBeenCalledWith('hello-world-alice.freepod.app')
      })
    })

    it('prefers an initial value over the default prefix', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value="myapp-alice.freepod.app"
          onChange={onChange}
          suffix="-alice.freepod.app"
          defaultPrefix="hello-world"
        />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('myapp')
    })
  })

  describe('unavailable prefill retry', () => {
    it('appends a number until the name is available', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockImplementation(async (fqdn: string) =>
        fqdn === 'hello-world-2-alice.freepod.app'
          ? { fqdn, usable: true, reason: null }
          : { fqdn, usable: false, reason: 'in_use' },
      )

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" defaultPrefix="hello-world" />,
      )

      await waitFor(() => {
        expect(screen.getByLabelText('Hostname')).toHaveValue('hello-world-2')
        expect(screen.getByTestId('CheckCircleIcon')).toBeInTheDocument()
      })
      expect(onChange).toHaveBeenCalledWith('hello-world-2-alice.freepod.app')
    })

    it('gives up after three tries', async () => {
      checkHostnameMock.mockClear()
      checkHostnameMock.mockResolvedValue({ fqdn: '', usable: false, reason: 'in_use' })

      render(
        <HostnameField value="" onChange={vi.fn()} suffix="-alice.freepod.app" defaultPrefix="hello-world" />,
      )

      // Three debounced checks outlast waitFor's default window.
      await waitFor(() => {
        expect(screen.getByText('Already in use')).toBeInTheDocument()
      }, { timeout: 2000 })
      expect(screen.getByLabelText('Hostname')).toHaveValue('hello-world-3')
      expect(checkHostnameMock).toHaveBeenCalledTimes(3)
    })

    it('stops retrying once the user edits the prefilled name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: '', usable: false, reason: 'in_use' })

      render(
        <HostnameField value="" onChange={onChange} suffix="-alice.freepod.app" defaultPrefix="hello-world" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'myname' } })

      await waitFor(() => {
        expect(screen.getByText('Already in use')).toBeInTheDocument()
      })
      expect(screen.getByLabelText('Hostname')).toHaveValue('myname')
      expect(checkHostnameMock).not.toHaveBeenCalledWith('myname-2-alice.freepod.app')
    })

  })

  describe('initialHostname bypass', () => {
    it('skips API validation when hostname matches initialHostname', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockClear()

      render(
        <HostnameField
          value="existing.example.com"
          onChange={onChange}
          suffix={null}
          initialHostname="existing.example.com"
        />,
      )

      // Wait for mount effects to settle
      await waitFor(() => {
        expect(screen.getByTestId('CheckCircleIcon')).toBeInTheDocument()
      })

      // API should not have been called
      expect(checkHostnameMock).not.toHaveBeenCalled()
    })

    it('calls API when hostname differs from initialHostname', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockClear()
      checkHostnameMock.mockResolvedValue({ fqdn: 'changed.example.com', usable: true, reason: null })

      render(
        <HostnameField
          value=""
          onChange={onChange}
          suffix={null}
          initialHostname="existing.example.com"
        />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'changed.example.com' } })

      await waitFor(() => {
        expect(checkHostnameMock).toHaveBeenCalledWith('changed.example.com')
      })
    })

    it('skips API again when hostname reverts to initialHostname', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockClear()
      checkHostnameMock.mockResolvedValue({ fqdn: 'different.example.com', usable: true, reason: null })

      render(
        <HostnameField
          value=""
          onChange={onChange}
          suffix={null}
          initialHostname="original.example.com"
        />,
      )

      // Change away from initial
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'different.example.com' } })
      await waitFor(() => {
        expect(checkHostnameMock).toHaveBeenCalledWith('different.example.com')
      })

      checkHostnameMock.mockClear()

      // Revert to initial
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'original.example.com' } })
      await waitFor(() => {
        expect(screen.getByTestId('CheckCircleIcon')).toBeInTheDocument()
      })

      // API should not have been called for the revert
      expect(checkHostnameMock).not.toHaveBeenCalled()
    })
  })
})
