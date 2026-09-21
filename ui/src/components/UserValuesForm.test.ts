import { describe, expect, it } from 'vitest'
import {
  flattenSchema,
  flattenValues,
  formatFieldError,
  unflatten,
  validateUserValues,
} from '../components/UserValuesForm'

describe('flattenSchema', () => {
  it('flattens simple schema with single field', () => {
    const schema = {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          title: 'Name',
        },
      },
    }

    const fields = flattenSchema(schema)
    expect(fields).toHaveLength(1)
    expect(fields[0].path).toBe('name')
    expect(fields[0].name).toBe('Name')
    expect(fields[0].type).toBe('string')
  })

  it('flattens nested schema with dot notation', () => {
    const schema = {
      type: 'object',
      properties: {
        ingress: {
          type: 'object',
          properties: {
            host: {
              type: 'string',
              title: 'Domain',
              pattern: '^.*$',
            },
          },
          required: ['host'],
        },
      },
      required: ['ingress'],
    }

    const fields = flattenSchema(schema)
    expect(fields).toHaveLength(1)
    expect(fields[0].path).toBe('ingress.host')
    expect(fields[0].name).toBe('Domain')
    expect(fields[0].pattern).toBe('^.*$')
    expect(fields[0].required).toBe(true)
  })

  it('uses path as name when title is not provided', () => {
    const schema = {
      type: 'object',
      properties: {
        user: {
          type: 'object',
          properties: {
            message: {
              type: 'string',
            },
          },
        },
      },
    }

    const fields = flattenSchema(schema)
    expect(fields).toHaveLength(1)
    expect(fields[0].path).toBe('user.message')
    expect(fields[0].name).toBe('user.message')
  })

  it('extracts all constraints from schema', () => {
    const schema = {
      type: 'object',
      properties: {
        count: {
          type: 'integer',
          title: 'Count',
          minimum: 1,
          maximum: 100,
        },
      },
    }

    const fields = flattenSchema(schema)
    expect(fields[0].type).toBe('integer')
    expect(fields[0].minimum).toBe(1)
    expect(fields[0].maximum).toBe(100)
  })

  it('returns empty array for null schema', () => {
    expect(flattenSchema(null)).toEqual([])
  })

  it('returns empty array for schema without properties', () => {
    expect(flattenSchema({ type: 'object' })).toEqual([])
  })
})

describe('flattenValues', () => {
  it('flattens simple defaults', () => {
    const defaults = { name: 'test' }
    expect(flattenValues(defaults)).toEqual({ name: 'test' })
  })

  it('flattens nested defaults with dot notation', () => {
    const defaults = {
      ingress: {
        host: 'example.com',
      },
      user: {
        message: 'Hello',
      },
    }

    expect(flattenValues(defaults)).toEqual({
      'ingress.host': 'example.com',
      'user.message': 'Hello',
    })
  })

  it('returns empty object for null defaults', () => {
    expect(flattenValues(null)).toEqual({})
  })
})

describe('unflatten', () => {
  it('unflattens simple values', () => {
    const values = { name: 'test' }
    expect(unflatten(values)).toEqual({ name: 'test' })
  })

  it('unflattens nested values', () => {
    const values = {
      'ingress.host': 'example.com',
      'user.message': 'Hello',
    }

    expect(unflatten(values)).toEqual({
      ingress: { host: 'example.com' },
      user: { message: 'Hello' },
    })
  })

  it('handles deep nesting', () => {
    const values = {
      'a.b.c.d': 'value',
    }

    expect(unflatten(values)).toEqual({
      a: { b: { c: { d: 'value' } } },
    })
  })
})

describe('validateUserValues', () => {
  it('returns empty array for valid values', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string' },
      },
    }

    const values = { name: 'test' }
    expect(validateUserValues(schema, values)).toEqual([])
  })

  it('returns errors for invalid values', () => {
    const schema = {
      type: 'object',
      properties: {
        count: { type: 'integer' },
      },
    }

    const values = { count: 'not a number' }
    const errors = validateUserValues(schema, values)
    expect(errors.length).toBeGreaterThan(0)
  })

  it('returns empty array for null schema', () => {
    expect(validateUserValues(null, { name: 'test' })).toEqual([])
  })

  it('returns empty array for null values', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string' },
      },
    }

    expect(validateUserValues(schema, null)).toEqual([])
  })

  it('validates draft-2020-12 schemas on first call', () => {
    const schema = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      type: 'object',
      properties: {
        federation: {
          type: 'object',
          properties: {
            enabled: { type: 'boolean' },
          },
          required: ['enabled'],
        },
      },
      required: ['federation'],
    }

    expect(validateUserValues(schema, { federation: { enabled: true } })).toEqual([])
    const errors = validateUserValues(schema, { federation: { enabled: 'true' } })
    expect(errors).toEqual(['user_values_json.federation.enabled: failed constraint "type"'])
  })

  it('reports in the server format, naming the missing property', () => {
    const schema = {
      type: 'object',
      properties: {
        admin: {
          type: 'object',
          properties: { name: { type: 'string', minLength: 2 } },
          required: ['name'],
        },
      },
    }

    expect(validateUserValues(schema, { admin: { name: 'd' } })).toEqual([
      'user_values_json.admin.name: failed constraint "minLength"',
    ])
    expect(validateUserValues(schema, { admin: {} })).toEqual([
      'user_values_json.admin.name: failed constraint "required"',
    ])
  })
})

describe('schema flattening integration', () => {
  it('round-trips defaults through flatten and unflatten', () => {
    const defaults = {
      ingress: {
        host: 'example.com',
      },
      user: {
        message: 'Hello World',
      },
    }

    const flattened = flattenValues(defaults)
    const unflattened = unflatten(flattened)

    expect(unflattened).toEqual(defaults)
  })

  it('matches schema fields with default values', () => {
    const schema = {
      type: 'object',
      properties: {
        ingress: {
          type: 'object',
          properties: {
            host: { type: 'string', title: 'Domain' },
          },
          required: ['host'],
        },
        user: {
          type: 'object',
          properties: {
            message: { type: 'string', title: 'Message' },
          },
        },
      },
      required: ['ingress'],
    }

    const defaults = {
      ingress: {
        host: 'example.com',
      },
      user: {
        message: 'Hello',
      },
    }

    const fields = flattenSchema(schema)
    const flatDefaults = flattenValues(defaults)

    expect(fields).toHaveLength(2)
    expect(flatDefaults['ingress.host']).toBe('example.com')
    expect(flatDefaults['user.message']).toBe('Hello')
  })
})

describe('formatFieldError', () => {
  const field = {
    path: 'PHOTOPRISM_ADMIN_PASSWORD',
    name: 'Password',
    type: 'string',
    title: 'Password',
    minLength: 8,
    maxLength: 72,
    required: true,
    target: 'runtime' as const,
    sensitive: true,
  }

  it('drops the property prefix and restates minLength', () => {
    const message = 'vars.PHOTOPRISM_ADMIN_PASSWORD: failed constraint "minLength"'
    expect(formatFieldError(message, field)).toBe('Must be at least 8 characters')
  })

  it('restates maxLength against the schema', () => {
    const message = 'vars.PHOTOPRISM_ADMIN_PASSWORD: failed constraint "maxLength"'
    expect(formatFieldError(message, field)).toBe('Must be at most 72 characters')
  })

  it('reports a rejected pattern without naming the property', () => {
    const message = 'vars.PHOTOPRISM_ADMIN_PASSWORD: failed constraint "pattern"'
    const result = formatFieldError(message, field)
    expect(result).toBe('Contains characters that are not allowed')
    expect(result).not.toContain('PHOTOPRISM_ADMIN_PASSWORD')
  })

  it('names the expected type', () => {
    const boolField = { ...field, type: 'boolean', minLength: undefined }
    const message = 'vars.SIGNUPS_ALLOWED: failed constraint "type"'
    expect(formatFieldError(message, boolField)).toBe('Must be a boolean')
  })

  it('falls back to the server wording for an unrecognised constraint', () => {
    const message = 'vars.PHOTOPRISM_ADMIN_PASSWORD: failed constraint "uniqueItems"'
    expect(formatFieldError(message, field)).toBe('failed constraint "uniqueItems"')
  })

  it('leaves a message without a prefix intact', () => {
    expect(formatFieldError('Something went wrong', field)).toBe('Something went wrong')
  })
})
