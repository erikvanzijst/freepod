import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostnameField } from './HostnameField'

const checkHostnameMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  checkHostname: (...args: unknown[]) => checkHostnameMock(...args),
}))

describe('HostnameField', () => {
  describe('mode selection', () => {
    it('defaults to custom mode when the account has no domain name yet', () => {
      const onChange = vi.fn()
      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.queryByText('Free domain')).not.toBeInTheDocument()
    })

    it('defaults to Freepod mode when the account holds a domain name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.getByText('.app.example.com')).toBeInTheDocument()
      expect(screen.getByText('Free domain')).toBeInTheDocument()
      expect(screen.getByText('Custom domain')).toBeInTheDocument()
    })

    it('switches from Freepod to custom mode', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      fireEvent.click(screen.getByText('Custom domain'))
      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
    })

    it('switches from custom back to Freepod mode', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      fireEvent.click(screen.getByText('Custom domain'))
      fireEvent.click(screen.getByText('Free domain'))
      expect(screen.getByText('.app.example.com')).toBeInTheDocument()
    })
  })

  describe('value composition', () => {
    it('combines the app name with the account domain name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'myapp.app.example.com', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'myapp' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('myapp.app.example.com')
      })
    })

    it('uses full value in custom mode', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'myapp.custom.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'myapp.custom.com' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('myapp.custom.com')
      })
    })

    it('does not call onChange for an empty app name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      expect(onChange).not.toHaveBeenCalled()
    })
  })

  describe('debounced validation', () => {
    it('calls checkHostname after debounce', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'test.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

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

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      // Type something then clear it
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'x' } })
      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: '' } })

      // Wait longer than the debounce
      await new Promise((r) => setTimeout(r, 500))
      expect(checkHostnameMock).not.toHaveBeenCalled()
    })

    it('shows success icon when hostname is usable', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'good.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'good.example.com' } })

      await waitFor(() => {
        expect(screen.getByTestId('CheckCircleIcon')).toBeInTheDocument()
      })
    })

    it('shows error icon and helper text for invalid hostname', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'bad', usable: false, reason: 'invalid' })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'bad' } })

      await waitFor(() => {
        expect(screen.getByTestId('ErrorIcon')).toBeInTheDocument()
        expect(screen.getByText('Invalid hostname format')).toBeInTheDocument()
      })
    })

    it('shows in-use error message', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'taken.example.com', usable: false, reason: 'in_use' })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'taken.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Already in use')).toBeInTheDocument()
      })
    })

    it('shows reserved error message', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'smtp.example.com', usable: false, reason: 'reserved' })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'smtp.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Hostname is reserved')).toBeInTheDocument()
      })
    })
  })

  describe('app name dot stripping', () => {
    it('strips dots from the app name', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'foobar.app.example.com', usable: true, reason: null })

      render(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'foo.bar' } })

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith('foobar.app.example.com')
      })
    })

    it('allows dots in custom mode', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'foo.bar.example.com', usable: true, reason: null })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

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

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.other.example.com' } })

      await waitFor(() => {
        expect(
          screen.getByText('That domain name belongs to another account'),
        ).toBeInTheDocument()
      })
    })

    it('renders no message for the retired nested_subdomain reason', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'a.b.example.com', usable: false, reason: 'nested_subdomain' })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

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

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} cnameTarget="dev.freepod.eu" />)

      // Custom-mode helper text reflects the environment-specific target
      expect(
        screen.getByText('Point your domain at Freepod: create a CNAME record → dev.freepod.eu'),
      ).toBeInTheDocument()

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Create a CNAME record pointing to dev.freepod.eu')).toBeInTheDocument()
      })
    })

    it('falls back to freepod.eu when cnameTarget is not provided', async () => {
      const onChange = vi.fn()
      checkHostnameMock.mockResolvedValue({ fqdn: 'app.example.com', usable: false, reason: 'not_resolving' })

      render(<HostnameField value="" onChange={onChange} accountFqdn={null} />)

      fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'app.example.com' } })

      await waitFor(() => {
        expect(screen.getByText('Create a CNAME record pointing to freepod.eu')).toBeInTheDocument()
      })
    })
  })

  describe('async account domain name', () => {
    it('switches to Freepod mode when the account domain name arrives after mount', () => {
      const onChange = vi.fn()
      const { rerender } = render(
        <HostnameField value="" onChange={onChange} accountFqdn={null} />,
      )

      // Initially in custom mode: no account domain name yet
      expect(screen.getByLabelText('Hostname')).toBeInTheDocument()
      expect(screen.queryByText('Free domain')).not.toBeInTheDocument()

      // Domains arrive asynchronously
      rerender(
        <HostnameField value="" onChange={onChange} accountFqdn="app.example.com" />,
      )

      // Switched to Freepod mode, rendering the account's own suffix
      expect(screen.getByText('Free domain')).toBeInTheDocument()
      expect(screen.getByText('.app.example.com')).toBeInTheDocument()
    })
  })

  describe('initial value sync', () => {
    it('splits an initial value into app name and account domain name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value="myapp.app.example.com"
          onChange={onChange}
          accountFqdn="app.example.com"
        />,
      )

      expect(screen.getByLabelText('Hostname')).toHaveValue('myapp')
    })

    it('falls back to custom mode when the value sits under no account domain name', () => {
      const onChange = vi.fn()
      render(
        <HostnameField
          value="myapp.other.com"
          onChange={onChange}
          accountFqdn="app.example.com"
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
          accountFqdn={null}
          error="Server rejected hostname"
        />,
      )

      expect(screen.getByText('Server rejected hostname')).toBeInTheDocument()
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
          accountFqdn={null}
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
          accountFqdn={null}
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
          accountFqdn={null}
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
