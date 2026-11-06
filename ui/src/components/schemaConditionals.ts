import type Ajv2020 from 'ajv/dist/2020'

type JsonObject = Record<string, unknown>

/** Which fields, by dotted path, a schema's conditionals hide or require right now. */
export interface ConditionalFields {
  hidden: Set<string>
  required: Set<string>
}

interface Branch {
  mentions: string[]
  requires: string[]
  applies: boolean
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((n): n is string => typeof n === 'string') : []
}

function branch(schema: JsonObject, applies: boolean): Branch {
  const requires = names(schema.required)
  const properties = isObject(schema.properties) ? Object.keys(schema.properties) : []
  return { mentions: [...new Set([...requires, ...properties])], requires, applies }
}

function holds(ajv: Ajv2020, condition: unknown, document: JsonObject): boolean {
  if (typeof condition === 'boolean') return condition
  try {
    return ajv.validate(condition as JsonObject, document) as boolean
  } catch {
    // An `if` the validator cannot compile (a `$ref` out of the subschema, say)
    // is treated as not holding; the platform has the final word.
    return false
  }
}

function branches(ajv: Ajv2020, schema: JsonObject, document: JsonObject): Branch[] {
  const found: Branch[] = []
  const conditionals = [schema, ...(Array.isArray(schema.allOf) ? schema.allOf : [])]
  for (const conditional of conditionals) {
    if (!isObject(conditional) || !('if' in conditional)) continue
    const ok = holds(ajv, conditional.if, document)
    if (isObject(conditional.then)) found.push(branch(conditional.then, ok))
    if (isObject(conditional.else)) found.push(branch(conditional.else, !ok))
  }
  if (isObject(schema.dependentRequired)) {
    for (const [trigger, dependents] of Object.entries(schema.dependentRequired)) {
      const requires = names(dependents)
      found.push({ mentions: requires, requires, applies: trigger in document })
    }
  }
  return found
}

/**
 * Evaluate a schema's conditionals against the document a submission would
 * form. Supported, at the root and inside every object property: `if`/`then`/
 * `else`, the same inside `allOf` entries, and `dependentRequired`. An object
 * property's conditionals are evaluated against that object's own value.
 *
 * A property a branch mentions (in its `required` or `properties`) is shown
 * only while such a branch applies, unless its object's `required` names it;
 * one no branch mentions is always shown. An applying branch's `required`
 * makes its properties required.
 */
export function evaluateConditionals(
  ajv: Ajv2020,
  schema: JsonObject | null,
  document: JsonObject,
): ConditionalFields {
  const hidden = new Set<string>()
  const required = new Set<string>()
  if (schema) evaluateObject(ajv, schema, document, '', hidden, required)
  return { hidden, required }
}

function evaluateObject(
  ajv: Ajv2020,
  schema: JsonObject,
  document: JsonObject,
  prefix: string,
  hidden: Set<string>,
  required: Set<string>,
): void {
  const path = (name: string) => (prefix ? `${prefix}.${name}` : name)
  const found = branches(ajv, schema, document)
  const alwaysShown = new Set(names(schema.required))
  const shown = new Set<string>()
  for (const { mentions, requires, applies } of found) {
    if (!applies) continue
    mentions.forEach((name) => shown.add(name))
    requires.forEach((name) => required.add(path(name)))
  }
  for (const { mentions } of found) {
    for (const name of mentions) {
      if (!shown.has(name) && !alwaysShown.has(name)) hidden.add(path(name))
    }
  }

  if (!isObject(schema.properties)) return
  for (const [name, child] of Object.entries(schema.properties)) {
    if (!isObject(child) || !isObject(child.properties)) continue
    const value = document[name]
    evaluateObject(ajv, child, isObject(value) ? value : {}, path(name), hidden, required)
  }
}
