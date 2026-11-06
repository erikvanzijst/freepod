import Ajv2020 from 'ajv/dist/2020'
import { describe, expect, it } from 'vitest'
import { evaluateConditionals } from './schemaConditionals'

const ajv = new Ajv2020({ allErrors: true, strict: false })

const signInOff = {
  required: ['auth'],
  properties: { auth: { required: ['enabled'], properties: { enabled: { const: false } } } },
}

const nextcloud = {
  type: 'object',
  properties: {
    host: { type: 'string' },
    auth: { type: 'object', properties: { enabled: { type: 'boolean', default: true } } },
    NEXTCLOUD_ADMIN_PASSWORD: {
      type: 'string',
      'x-caelus-target': 'runtime',
      'x-caelus-sensitive': true,
    },
  },
  required: ['host'],
  if: signInOff,
  then: { required: ['NEXTCLOUD_ADMIN_PASSWORD'] },
}

const evaluate = (schema: Record<string, unknown>, document: Record<string, unknown>) => {
  const { hidden, required } = evaluateConditionals(ajv, schema, document)
  return { hidden: [...hidden].sort(), required: [...required].sort() }
}

describe('evaluateConditionals', () => {
  it('hides a var its branch mentions while the condition fails', () => {
    expect(evaluate(nextcloud, { host: 'h', auth: { enabled: true } })).toEqual({
      hidden: ['NEXTCLOUD_ADMIN_PASSWORD'],
      required: [],
    })
  })

  it('shows and requires it while the condition holds', () => {
    expect(evaluate(nextcloud, { host: 'h', auth: { enabled: false } })).toEqual({
      hidden: [],
      required: ['NEXTCLOUD_ADMIN_PASSWORD'],
    })
  })

  it('reads else when the condition fails', () => {
    const schema = {
      ...nextcloud,
      then: { properties: { ADMIN_USER: {} } },
      else: { properties: { ALLOWED_DOMAINS: {} } },
    }
    expect(evaluate(schema, { auth: { enabled: true } }).hidden).toEqual(['ADMIN_USER'])
    expect(evaluate(schema, { auth: { enabled: false } }).hidden).toEqual(['ALLOWED_DOMAINS'])
  })

  it('reads conditionals inside allOf', () => {
    const schema = {
      properties: {},
      allOf: [
        { if: signInOff, then: { required: ['PASSWORD'] } },
        { if: { required: ['SMTP_HOST'] }, then: { required: ['SMTP_PORT'] } },
      ],
    }
    expect(evaluate(schema, { auth: { enabled: false }, SMTP_HOST: 'mx' })).toEqual({
      hidden: [],
      required: ['PASSWORD', 'SMTP_PORT'],
    })
    expect(evaluate(schema, {}).hidden).toEqual(['PASSWORD', 'SMTP_PORT'])
  })

  it('reads dependentRequired as a branch applying while its trigger is present', () => {
    const schema = { dependentRequired: { SMTP_HOST: ['SMTP_PORT'] } }
    expect(evaluate(schema, {})).toEqual({ hidden: ['SMTP_PORT'], required: [] })
    expect(evaluate(schema, { SMTP_HOST: 'mx' })).toEqual({ hidden: [], required: ['SMTP_PORT'] })
  })

  it('never hides a property the root requires', () => {
    const schema = { ...nextcloud, then: { properties: { host: { minLength: 3 } } } }
    expect(evaluate(schema, { auth: { enabled: true } }).hidden).toEqual([])
  })

  it('evaluates types, not wire strings', () => {
    const schema = {
      if: { properties: { SIGNUPS: { const: true } }, required: ['SIGNUPS'] },
      then: { required: ['SIGNUP_DOMAIN'] },
    }
    expect(evaluate(schema, { SIGNUPS: true }).required).toEqual(['SIGNUP_DOMAIN'])
    expect(evaluate(schema, { SIGNUPS: 'true' }).required).toEqual([])
  })

  it('ignores then and else without an if, and handles no schema', () => {
    expect(evaluate({ then: { required: ['X'] } }, {})).toEqual({ hidden: [], required: [] })
    const none = evaluateConditionals(ajv, null, {})
    expect([...none.hidden, ...none.required]).toEqual([])
  })

  describe('inside an object property', () => {
    const custom = {
      properties: {
        hostname: { type: 'string' },
        auth: {
          type: 'object',
          properties: {
            enabled: { type: 'boolean' },
            access: { enum: ['anyone', 'listed'] },
            public: { type: 'array', items: { type: 'string' } },
            note: { type: 'string' },
          },
          if: { properties: { enabled: { const: true } }, required: ['enabled'] },
          then: { properties: { access: {}, public: {} }, required: ['note'] },
        },
      },
    }

    it("evaluates the object's own value and hides its fields by path", () => {
      expect(evaluate(custom, { auth: { enabled: false } })).toEqual({
        hidden: ['auth.access', 'auth.note', 'auth.public'],
        required: [],
      })
      expect(evaluate(custom, { auth: { enabled: true } })).toEqual({
        hidden: [],
        required: ['auth.note'],
      })
    })

    it('evaluates an absent object as empty', () => {
      expect(evaluate(custom, {}).hidden).toEqual(['auth.access', 'auth.note', 'auth.public'])
    })

    it("never hides a property its object's required names", () => {
      const schema = {
        properties: { auth: { ...custom.properties.auth, required: ['access'] } },
      }
      expect(evaluate(schema, { auth: { enabled: false } }).hidden).toEqual([
        'auth.note',
        'auth.public',
      ])
    })
  })
})
