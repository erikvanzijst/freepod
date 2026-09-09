import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormHelperText,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getCnameTarget } from '../api/endpoints'
import { useMySubdomain } from './subdomain/useMySubdomain'
import { HostnameField } from './HostnameField'
import { SensitiveVarField } from './SensitiveVarField'

const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)

/**
 * Which channel a property is submitted through.
 *
 * `chart` configures the Helm chart (`user_values_json`); `runtime` becomes an
 * environment variable in the pod (`vars`). Unmarked means `chart`, which is
 * what keeps every existing product's schema working unchanged.
 */
export type FieldTarget = 'chart' | 'runtime'

export interface SchemaField {
  path: string
  name: string
  type: string
  title?: string
  description?: string
  pattern?: string
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
  default?: unknown
  required: boolean
  target: FieldTarget
  /** Write-only: read back without its value, so it is never prefilled. */
  sensitive: boolean
}

/** One entry in the vars half of a submission. */
export interface VarSubmission {
  value: string
}

export function flattenSchema(
  schema: Record<string, unknown> | null,
  prefix = '',
  requiredPaths: string[] = [],
): SchemaField[] {
  if (!schema || typeof schema !== 'object') {
    return []
  }

  const fields: SchemaField[] = []
  const properties = schema.properties as Record<string, unknown> | undefined
  const schemaRequired = (schema.required as string[]) || []

  if (!properties) {
    return fields
  }

  for (const [key, value] of Object.entries(properties)) {
    const currentPath = prefix ? `${prefix}.${key}` : key
    const isRequired = schemaRequired.includes(key)

    if (isRequired) {
      requiredPaths.push(currentPath)
    }

    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      continue
    }

    const propSchema = value as Record<string, unknown>

    // If it has nested properties, it's an object type - recurse
    if (propSchema.properties) {
      fields.push(...flattenSchema(propSchema, currentPath, requiredPaths))
      continue
    }

    // It's a leaf field - add it. The routing markers are only ever read
    // here: the platform accepts `x-caelus-target: runtime` on a top-level
    // scalar and nowhere else, so a nested property is a chart value whatever
    // it claims, and the API rejects the schema that claimed otherwise.
    const target: FieldTarget =
      !prefix && propSchema['x-caelus-target'] === 'runtime' ? 'runtime' : 'chart'
    fields.push({
      target,
      sensitive: target === 'runtime' && propSchema['x-caelus-sensitive'] === true,
      path: currentPath,
      name: (propSchema.title as string) || currentPath,
      type: (propSchema.type as string) || 'string',
      title: propSchema.title as string | undefined,
      description: propSchema.description as string | undefined,
      pattern: propSchema.pattern as string | undefined,
      minLength: propSchema.minLength as number | undefined,
      maxLength: propSchema.maxLength as number | undefined,
      minimum: propSchema.minimum as number | undefined,
      maximum: propSchema.maximum as number | undefined,
      default: propSchema.default,
      required: requiredPaths.includes(currentPath),
    })
  }

  return fields
}

export function flattenValues(
  defaults: Record<string, unknown> | null,
  prefix = '',
): Record<string, unknown> {
  if (!defaults || typeof defaults !== 'object') {
    return {}
  }

  const result: Record<string, unknown> = {}

  for (const [key, value] of Object.entries(defaults)) {
    const currentPath = prefix ? `${prefix}.${key}` : key

    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      Object.assign(result, flattenValues(value as Record<string, unknown>, currentPath))
    } else {
      result[currentPath] = value
    }
  }

  return result
}

export function unflatten(values: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {}

  for (const [key, value] of Object.entries(values)) {
    const parts = key.split('.')
    let current = result

    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i]
      if (!(part in current)) {
        current[part] = {}
      }
      current = current[part] as Record<string, unknown>
    }

    current[parts[parts.length - 1]] = value
  }

  return result
}

interface UserValuesFormProps {
  valuesSchemaJson: Record<string, unknown> | null
  initialValuesJson?: Record<string, unknown> | null
  /** The deployment's current vars, for prefilling. Sensitive ones carry no value. */
  initialVars?: Record<string, { value?: string; sensitive: boolean }> | null
  onChange: (userValues: Record<string, unknown> | null) => void
  /**
   * The runtime half of the same submission.
   *
   * Reported separately from `onChange` rather than folded into one payload
   * so that the chart-values contract is unchanged for every caller: a schema
   * that marks nothing runtime never fires this at all.
   */
  onVarsChange?: (vars: Record<string, VarSubmission>) => void
  onHostnameValidationChange?: (valid: boolean) => void
  errors?: string[]
  initialHostname?: string
  readOnly?: boolean
}

export function UserValuesForm({
  valuesSchemaJson,
  initialValuesJson,
  initialVars,
  onChange,
  onVarsChange,
  onHostnameValidationChange,
  errors = [],
  initialHostname,
  readOnly,
}: UserValuesFormProps) {
  const fields = useMemo(() => flattenSchema(valuesSchemaJson), [valuesSchemaJson])
  const initialValues = useMemo(() => flattenValues(initialValuesJson ?? null), [initialValuesJson])

  const hasHostnameField = useMemo(
    () => fields.some((f) => f.title?.toLowerCase() === 'hostname'),
    [fields],
  )
  const subdomainQuery = useMySubdomain()
  const cnameTargetQuery = useQuery({
    queryKey: ['cname-target'],
    queryFn: getCnameTarget,
    enabled: hasHostnameField,
    staleTime: 5 * 60 * 1000,
  })

  const [formData, setFormData] = useState<Record<string, unknown>>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  // Sensitive fields the user has actually typed into. Everything else is
  // submitted with no `value` at all, which is what "leave it unchanged"
  // means on the wire -- an empty string is a real value and would wipe the
  // stored secret.
  const [touchedSensitive, setTouchedSensitive] = useState<Set<string>>(new Set())

  useEffect(() => {
    const initialData: Record<string, unknown> = {}
    for (const field of fields) {
      if (field.target === 'runtime') {
        // A sensitive var is read back without its value, so there is nothing
        // to prefill and nothing to reveal; the field starts empty and says
        // so. A non-sensitive one prefills from what the deployment holds.
        const current = initialVars?.[field.path]
        if (!field.sensitive && current?.value !== undefined) {
          initialData[field.path] =
            field.type === 'boolean' ? current.value === 'true' : current.value
          continue
        }
      }
      const defaultValue = field.path in initialValues ? initialValues[field.path] : field.default
      if (defaultValue !== undefined) {
        if (field.type === 'boolean') {
          initialData[field.path] = Boolean(defaultValue)
        } else {
          initialData[field.path] = defaultValue
        }
      } else if (field.type === 'boolean') {
        initialData[field.path] = false
      }
    }
    setFormData(initialData)
    setTouchedSensitive(new Set())
  }, [fields, initialValues, initialVars])

  useEffect(() => {
    if (fields.length === 0) {
      onChange(null)
      onVarsChange?.({})
      return
    }

    // One form, two payloads. The split is by `target` and nothing else, so a
    // property moving between channels is a schema edit and not a UI change.
    const chartData: Record<string, unknown> = {}
    const vars: Record<string, VarSubmission> = {}

    for (const field of fields) {
      if (field.target !== 'runtime') {
        if (field.path in formData) {
          chartData[field.path] = formData[field.path]
        }
        continue
      }

      // An untouched sensitive field submits nothing at all: no entry means
      // no `value`, which keeps the stored secret and is also the only thing
      // that works on a create, where there is no stored value to leave alone.
      if (field.sensitive && !touchedSensitive.has(field.path)) {
        continue
      }
      const raw = formData[field.path]
      const empty = raw === undefined || raw === null || raw === ''
      // A var the user never filled in is not submitted as an empty one --
      // unless the deployment already holds it, where blanking the field is a
      // deliberate clear rather than an omission.
      if (empty && initialVars?.[field.path] === undefined) {
        continue
      }
      // Always a string on the wire, whatever the schema declares: that is
      // what a process environment holds, and the platform coerces it back to
      // the declared type to validate it.
      vars[field.path] = { value: typeof raw === 'boolean' ? String(raw) : String(raw ?? '') }
    }

    onVarsChange?.(vars)

    const hasValues = Object.values(chartData).some((v) => {
      if (typeof v === 'string') {
        return v !== ''
      }
      return v !== undefined && v !== null
    })
    if (!hasValues) {
      onChange(null)
      return
    }

    onChange(unflatten(chartData))
  }, [formData, fields, initialVars, touchedSensitive, onChange, onVarsChange])

  useEffect(() => {
    if (errors.length > 0) {
      const newErrors: Record<string, string> = {}
      for (const error of errors) {
        // Try to match error to field
        for (const field of fields) {
          if (error.toLowerCase().includes(field.path.toLowerCase())) {
            newErrors[field.path] = error
            break
          }
        }
      }
      setFieldErrors(newErrors)
    }
  }, [errors, fields])

  const handleChange = (path: string, value: unknown, fieldType: string, sensitive = false) => {
    let processedValue = value

    if (fieldType === 'boolean') {
      processedValue = value === true || value === 'true'
    }

    setFormData((prev) => ({ ...prev, [path]: processedValue }))

    if (sensitive) {
      setTouchedSensitive((prev) => (prev.has(path) ? prev : new Set(prev).add(path)))
    }

    // Clear error when user starts typing
    if (fieldErrors[path]) {
      setFieldErrors((prev) => {
        const next = { ...prev }
        delete next[path]
        return next
      })
    }
  }

  if (fields.length === 0) {
    return null
  }

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        Configure application values:
      </Typography>
      {errors.length > 0 && Object.keys(fieldErrors).length === 0 && (
        <Box sx={{ p: 1, bgcolor: 'error.light', borderRadius: 1 }}>
          {errors.map((error, i) => (
            <Typography key={i} variant="body2" color="error.contrastText">
              {error}
            </Typography>
          ))}
        </Box>
      )}
      {fields.map((field) => {
        if (field.title?.toLowerCase() === 'hostname') {
          return (
            <HostnameField
              key={field.path}
              value={typeof formData[field.path] === 'string' ? (formData[field.path] as string) : ''}
              onChange={(hostname) => handleChange(field.path, hostname, 'string')}
              onValidationChange={onHostnameValidationChange}
              accountFqdn={subdomainQuery.data?.fqdn}
              cnameTarget={cnameTargetQuery.data || undefined}
              required={field.required}
              error={fieldErrors[field.path]}
              description={field.description}
              initialHostname={initialHostname}
              readOnly={readOnly}
            />
          )
        }

        if (field.sensitive) {
          return (
            <SensitiveVarField
              key={field.path}
              label={field.title || field.path}
              description={field.description}
              required={field.required}
              error={fieldErrors[field.path]}
              readOnly={readOnly}
              alreadySet={initialVars?.[field.path] !== undefined}
              touched={touchedSensitive.has(field.path)}
              value={typeof formData[field.path] === 'string' ? (formData[field.path] as string) : ''}
              onChange={(value) => handleChange(field.path, value, 'string', true)}
            />
          )
        }

        return (
          <FormControl key={field.path} fullWidth error={!!fieldErrors[field.path]}>
            {field.type === 'boolean' ? (
              <>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={formData[field.path] === true}
                      onChange={(e) => handleChange(field.path, e.target.checked, 'boolean')}
                      disabled={readOnly}
                    />
                  }
                  label={field.title || field.path}
                />
                {field.description && !fieldErrors[field.path] && (
                  <FormHelperText>{field.description}</FormHelperText>
                )}
              </>
            ) : (
              <TextField
                label={field.title || field.path}
                helperText={fieldErrors[field.path] || field.description}
                value={
                  typeof formData[field.path] === 'string' || typeof formData[field.path] === 'number'
                    ? formData[field.path]
                    : ''
                }
                onChange={(e) => handleChange(field.path, e.target.value, field.type)}
                type={
                  field.type === 'integer' || field.type === 'number'
                    ? 'number'
                    : field.pattern
                      ? 'text'
                      : 'text'
                }
                inputProps={
                  field.pattern
                    ? { title: field.description || field.title || field.path }
                    : undefined
                }
                required={field.required}
                error={!!fieldErrors[field.path]}
                slotProps={readOnly ? { input: { readOnly: true } } : undefined}
              />
            )}
            {fieldErrors[field.path] && <FormHelperText>{fieldErrors[field.path]}</FormHelperText>}
          </FormControl>
        )
      })}
    </Stack>
  )
}

/**
 * The chart half of a schema: the same partition the platform derives.
 *
 * Chart values are validated against this rather than against the whole
 * schema, because a runtime property is submitted through `vars` and never
 * appears in `user_values_json` — so a schema that *requires* one would
 * otherwise fail validation here and block a launch that the platform would
 * have accepted.
 */
function chartProjection(
  valuesSchemaJson: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (!valuesSchemaJson) {
    return null
  }
  const properties = valuesSchemaJson.properties as Record<string, unknown> | undefined
  if (!properties) {
    return valuesSchemaJson
  }
  const isRuntime = (key: string) => {
    const prop = properties[key] as Record<string, unknown> | undefined
    return prop?.['x-caelus-target'] === 'runtime'
  }
  const required = (valuesSchemaJson.required as string[] | undefined) ?? []
  return {
    ...valuesSchemaJson,
    properties: Object.fromEntries(
      Object.entries(properties).filter(([key]) => !isRuntime(key)),
    ),
    required: required.filter((key) => !isRuntime(key)),
  }
}

export function validateUserValues(
  valuesSchemaJson: Record<string, unknown> | null,
  userValues: Record<string, unknown> | null,
): string[] {
  if (!valuesSchemaJson || !userValues) {
    return []
  }

  const validate = ajv.compile(chartProjection(valuesSchemaJson)!)
  const valid = validate(userValues)

  if (valid) {
    return []
  }

  return (validate.errors || []).map((err) => {
    const path = err.instancePath || '/'
    return `${path}: ${err.message}`
  })
}
