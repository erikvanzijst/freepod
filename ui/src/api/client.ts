import { getStoredAuthHeaders } from '../state/useAuthEmail'
import { recordApiFailure } from '../components/feedback/diagnostics'

export class ApiError extends Error {
  status: number
  /**
   * The platform's stable identifier for the failing check, when it supplied
   * one. Branch on this rather than on `message`: several conditions share a
   * status code, and the prose is free to be reworded.
   */
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const envUrl = import.meta.env.VITE_API_URL as string | undefined

export const API_URL = envUrl ?? '/api'

/** Resolve an absolute API path (e.g. /api/static/icons/foo.png) to a full URL. */
export function resolveApiPath(absolutePath: string): string {
  const origin = API_URL.replace(/\/api\/?$/, '')
  return `${origin}${absolutePath}`
}

function toErrorMessage(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
          return item.msg
        }
        return null
      })
      .filter(Boolean) as string[]
    if (messages.length > 0) return messages.join('; ')
  }
  return fallback
}

async function readJson<T>(response: Response): Promise<T> {
  let data: ({ detail?: unknown; code?: unknown } & T) | null = null
  try {
    data = (await response.json()) as { detail?: unknown; code?: unknown } & T
  } catch {
    if (!response.ok) {
      throw new ApiError(response.statusText || 'Request failed', response.status)
    }
    throw new Error('Invalid JSON response')
  }
  if (!response.ok) {
    throw new ApiError(
      toErrorMessage(data?.detail, response.statusText || 'Request failed'),
      response.status,
      typeof data?.code === 'string' ? data.code : undefined,
    )
  }
  return data as T
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = init.method ?? 'GET'
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, init)
  } catch (error) {
    recordApiFailure(method, `${API_URL}${path}`, null)
    throw error
  }
  if (response.status >= 400) recordApiFailure(method, `${API_URL}${path}`, response.status)
  return response
}

export async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const { headers, ...rest } = options
  const authHeaders = getStoredAuthHeaders()
  const response = await apiFetch(path, {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      // Mark this as an API request so oauth2-proxy answers anonymous calls
      // with a 401 (which the SPA handles) rather than an HTML login redirect.
      Accept: 'application/json',
      ...authHeaders,
      ...(headers ?? {}),
    },
  })

  if (response.status === 204) {
    return null as T
  }

  return readJson<T>(response)
}

/** A non-JSON representation of a resource, negotiated with `Accept`. */
export async function requestBlob(path: string, accept: string): Promise<Blob> {
  const response = await apiFetch(path, {
    headers: { Accept: accept, ...getStoredAuthHeaders() },
  })
  if (!response.ok) {
    let detail: unknown
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail
    } catch {
      detail = undefined
    }
    throw new ApiError(
      toErrorMessage(detail, response.statusText || 'Request failed'),
      response.status,
    )
  }
  return response.blob()
}

export async function requestMultipart<T>(
  path: string,
  payload: object,
  file?: { field: string; file: File | Blob },
  options: RequestInit = {},
  method: string = 'POST',
): Promise<T> {
  const { headers, ...rest } = options
  const authHeaders = getStoredAuthHeaders()
  const formData = new FormData()
  formData.append('payload', JSON.stringify(payload))
  if (file) {
    formData.append(file.field, file.file)
  }

  const response = await apiFetch(path, {
    ...rest,
    method,
    body: formData,
    headers: {
      ...authHeaders,
      ...(headers ?? {}),
    },
  })

  return readJson<T>(response)
}

/** A multipart form of plain fields, plus files, answered with JSON. */
export async function requestForm<T>(path: string, form: FormData, method: string = 'POST'): Promise<T> {
  const response = await apiFetch(path, {
    method,
    body: form,
    headers: { Accept: 'application/json', ...getStoredAuthHeaders() },
  })
  return readJson<T>(response)
}
