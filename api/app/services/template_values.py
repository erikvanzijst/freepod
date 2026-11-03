from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, NamedTuple

from jsonschema import SchemaError, ValidationError
from jsonschema import validate as jsonschema_validate

from app.services.errors import CaelusException, IntegrityException, ValidationException


def bytes_to_k8s_size(n: int) -> str:
    """Convert byte count to the largest clean Kubernetes binary size unit."""
    if n == 0:
        return "0"
    for unit, divisor in [("Ti", 1 << 40), ("Gi", 1 << 30), ("Mi", 1 << 20), ("Ki", 1 << 10)]:
        if n >= divisor and n % divisor == 0:
            return f"{n // divisor}{unit}"
    return str(n)


def deep_merge(base: Any, override: Any) -> Any:
    """Deep-merge two JSON-like values, recursively merging object keys."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged: dict[str, Any] = {k: deepcopy(v) for k, v in base.items()}
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)


# Routing markers (D1/D2 of the deployment-vars design). A property carrying
# `x-caelus-target: runtime` is a process environment variable, not a chart
# value; anything else, marker or not, configures the chart. `x-` keeps the
# keywords from colliding with a future JSON Schema draft.
TARGET_KEY = "x-caelus-target"
TARGET_RUNTIME = "runtime"
TARGET_CHART = "chart"
SENSITIVE_KEY = "x-caelus-sensitive"
VARS_ADDITIONAL_KEY = "x-caelus-vars-additional"

# A runtime property's name *is* the environment variable's name -- nothing
# flattens or renames it anywhere -- so it has to be a legal one.
VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Names the platform itself injects into a pod, plus one reserved ahead of
# need. `RAILPACK_` is Railpack's own namespace and takes precedence over what
# a plan declares; no var reaches a build today, but reserving a prefix *later*
# breaks whoever has already set one.
RESERVED_VAR_PREFIXES = ("CAELUS_", "AWS_", "S3_", "RAILPACK_")
RESERVED_VAR_NAMES = ("BUCKET_NAME", "PORT")

# `x-caelus-target: runtime` is legal only on a scalar, and only at the root.
# Nesting would need a flattening convention (`signups.allowed` ->
# `signups__allowed`) written twice, in the UI to build the payload and in the
# API to undo it -- the same rule in two languages, free to drift.
SCALAR_TYPES = ("string", "number", "integer", "boolean")

# Root keywords that relate properties to one another, and so may span both
# halves. They are left out of the chart projection and evaluated against the
# full document only (validate-full-values-document D1).
DOCUMENT_KEYWORDS = frozenset(
    {
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
    }
)

# Root keywords that decide which keys the object may hold. Each projection
# decides that for its own half, so the full document is validated without
# them (D2).
KEY_SET_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "unevaluatedProperties",
        "patternProperties",
        "propertyNames",
        "minProperties",
        "maxProperties",
    }
)


class SchemaProjections(NamedTuple):
    """The two halves one template schema is partitioned into.

    Both are ``None`` when the template declares no schema, which is how a
    template that takes no values at all is distinguished from one that takes
    none *of a given kind*.
    """

    chart: dict[str, Any] | None
    vars: dict[str, Any] | None


def _target(prop: Any) -> str:
    """A property's channel. Unmarked means chart, which is what keeps every
    existing catalog schema working with no edit at all."""
    if isinstance(prop, dict) and prop.get(TARGET_KEY) == TARGET_RUNTIME:
        return TARGET_RUNTIME
    return TARGET_CHART


def schema_declares_vars(values_schema_json: dict[str, Any] | None) -> bool:
    """Whether a template schema routes any top-level property to the runtime."""
    if not isinstance(values_schema_json, dict):
        return False
    properties = values_schema_json.get("properties")
    if not isinstance(properties, dict):
        return False
    return any(_target(prop) == TARGET_RUNTIME for prop in properties.values())


def derive_projections(values_schema_json: dict[str, Any] | None) -> SchemaProjections:
    """Partition one schema into a chart schema and a vars schema.

    `properties` is a single JSON object, so its keys are unique by
    construction and the two halves are disjoint subsets of one namespace: a
    template author cannot declare a name that means one thing in one channel
    and something else in the other.

    Closed-by-default costs nothing here. A schema that marks nothing runtime
    derives an empty vars projection forbidding unknown keys, so a product
    opts out of vars by saying nothing -- no per-product boilerplate to write,
    and none to forget.
    """
    if not values_schema_json:
        return SchemaProjections(chart=None, vars=None)

    properties = values_schema_json.get("properties")
    if not isinstance(properties, dict):
        # Nothing to partition: the schema is the chart's, and vars are closed.
        properties = {}

    required = values_schema_json.get("required")
    required = required if isinstance(required, list) else []

    chart = {
        k: deepcopy(v)
        for k, v in values_schema_json.items()
        if k not in ("properties", "required") and k not in DOCUMENT_KEYWORDS
    }
    chart["properties"] = {
        k: deepcopy(v) for k, v in properties.items() if _target(v) == TARGET_CHART
    }
    chart["required"] = [
        k for k in required if _target(properties.get(k)) == TARGET_CHART
    ]

    vars_schema: dict[str, Any] = {}
    if "$schema" in values_schema_json:
        vars_schema["$schema"] = values_schema_json["$schema"]
    vars_schema["type"] = "object"
    # Not inherited from the root: `custom` must keep its chart half closed
    # while its vars half accepts anything, because it runs tenant-supplied
    # code and cannot enumerate that code's environment in advance.
    vars_schema["additionalProperties"] = bool(
        values_schema_json.get(VARS_ADDITIONAL_KEY, False)
    )
    vars_schema["properties"] = {
        # The routing marker itself does not survive into the projection: it
        # has done its job. `x-caelus-sensitive` does, because the vars service
        # reads sensitivity back out of the projection.
        k: {pk: deepcopy(pv) for pk, pv in v.items() if pk != TARGET_KEY}
        if isinstance(v, dict)
        else deepcopy(v)
        for k, v in properties.items()
        if _target(v) == TARGET_RUNTIME
    }
    vars_schema["required"] = [
        k for k in required if _target(properties.get(k)) == TARGET_RUNTIME
    ]
    return SchemaProjections(chart=chart, vars=vars_schema)


def validate_user_values(
    user_values_json: dict[str, Any],
    values_schema_json: dict[str, Any] | None,
) -> None:
    """Validate user-scoped values against the schema's **chart** projection.

    The chart projection rather than the whole schema, so that a property
    routed to the pod's environment is not also demanded as a chart value --
    and so that submitting one as a chart value is rejected by the projection's
    `additionalProperties` rather than silently accepted.
    """
    if not values_schema_json and not user_values_json:
        return
    elif user_values_json and not values_schema_json:
        raise IntegrityException("user_values_json not supported on this product template")

    try:
        jsonschema_validate(
            instance=user_values_json, schema=derive_projections(values_schema_json).chart
        )
    except SchemaError as exc:
        # SchemaError is a *sibling* of ValidationError, not a subclass, so it
        # would otherwise escape as an unhandled 500. It means the template's
        # own schema is broken, not the user's values. Templates created since
        # the meta-validation in `templates.create_template` cannot hit this;
        # this is a safety net for any that predate it.
        raise IntegrityException(
            f"product template has an invalid values_schema_json: {exc.message}"
        ) from exc
    except ValidationError as exc:
        raise IntegrityException(f"user_values_json is invalid: {exc.message}") from exc


def check_var_name(name: str) -> None:
    """Reject a var key that cannot be an environment variable, or is ours.

    Applied both to a schema's runtime properties and to a caller's keys on an
    open projection, so `custom` -- whose schema declares no keys at all --
    gets the same rules as a curated product.
    """
    if not VAR_NAME_RE.match(name):
        raise ValidationException(
            f"{name}: a var's name is an environment variable name and must "
            "match ^[A-Za-z_][A-Za-z0-9_]{0,63}$"
        )
    if name in RESERVED_VAR_NAMES:
        raise ValidationException(f"{name}: {name} is reserved by the platform")
    for prefix in RESERVED_VAR_PREFIXES:
        if name.startswith(prefix):
            raise ValidationException(
                f"{name}: the {prefix}* namespace is reserved by the platform"
            )


def _marked_nodes(node: Any, path: str) -> list[tuple[str, dict[str, Any]]]:
    """Every dict anywhere in the document carrying a routing marker."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if TARGET_KEY in node or SENSITIVE_KEY in node:
            found.append((path, node))
        for key, value in node.items():
            found.extend(_marked_nodes(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_marked_nodes(value, f"{path}[{index}]"))
    return found


def check_var_markers(values_schema_json: dict[str, Any] | None) -> None:
    """Reject a schema whose routing markers are not usable (design.md D2).

    Enforced when a template is created and when the catalog is loaded, so a
    bad marker fails in front of its author instead of at some tenant's next
    deployment -- by which time the template is already the one their
    deployment points at.
    """
    if not values_schema_json:
        return
    if not isinstance(values_schema_json.get(VARS_ADDITIONAL_KEY, False), bool):
        raise ValidationException(f"{VARS_ADDITIONAL_KEY} must be true or false")

    properties = values_schema_json.get("properties")
    properties = properties if isinstance(properties, dict) else {}

    for path, node in _marked_nodes(values_schema_json, ""):
        if any(node is prop for prop in properties.values()):
            continue
        raise ValidationException(
            f"{path}: routing markers are legal only on a top-level property"
        )

    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        target = prop.get(TARGET_KEY, TARGET_CHART)
        if target not in (TARGET_CHART, TARGET_RUNTIME):
            raise ValidationException(
                f"{name}: {TARGET_KEY} must be {TARGET_CHART!r} or {TARGET_RUNTIME!r}"
            )
        if target != TARGET_RUNTIME:
            if SENSITIVE_KEY in prop:
                raise ValidationException(
                    f"{name}: {SENSITIVE_KEY} is legal only on a "
                    f"{TARGET_KEY}: {TARGET_RUNTIME} property"
                )
            continue

        if not isinstance(prop.get(SENSITIVE_KEY, False), bool):
            raise ValidationException(f"{name}: {SENSITIVE_KEY} must be true or false")
        if prop.get("type") not in SCALAR_TYPES:
            raise ValidationException(
                f"{name}: a {TARGET_RUNTIME} property must be one of "
                + ", ".join(SCALAR_TYPES)
            )
        # The property name *is* the environment variable name -- there is no
        # spelling of `signups.allowed` that reaches a pod.
        check_var_name(name)


_INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
_NUMBER_RE = re.compile(r"^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$")


def _coerce_var(value: Any, declared: dict[str, Any] | None) -> Any:
    """Coerce a wire string to the type the projection declares (design.md D7).

    Vars are strings on the wire, because that is what a process environment
    holds and what the Kubernetes Secret carries. A value that does not spell
    its declared type is returned untouched, so the failure surfaces as an
    ordinary `type` violation rather than as a parse error here.

    The regexes are not decoration: `int("1_0")` is 10 in Python, and
    `float("nan")` succeeds. Neither is what a user typed.
    """
    if not isinstance(value, str) or not isinstance(declared, dict):
        return value
    declared_type = declared.get("type")
    if declared_type == "boolean":
        return {"true": True, "false": False}.get(value, value)
    if declared_type == "integer":
        return int(value) if _INTEGER_RE.match(value) else value
    if declared_type == "number":
        return float(value) if _NUMBER_RE.match(value) else value
    return value


def _var_error(exc: ValidationError) -> str:
    """Describe a failure without quoting what failed.

    `ValidationError.message` embeds the offending instance -- a bad
    `ADMIN_TOKEN` produces `'hunter2' is not of type 'boolean'` -- and that
    message reaches both the caller and the logs, which ship to Loki. The path
    and the violated keyword say everything actionable and leak nothing.
    """
    path = exc.json_path
    location = "vars" + path[1:] if path.startswith("$") else path
    return f'{location}: failed constraint "{exc.validator}"'


def validate_vars(
    vars: dict[str, Any],
    vars_projection: dict[str, Any] | None,
) -> None:
    """Validate submitted vars against a template's derived vars projection.

    `vars_projection` is `None` only when the template declares no schema at
    all, which rejects vars outright -- mirroring `validate_user_values`.

    Raises `ValidationException` (400) rather than the `IntegrityException`
    (409) its chart-side sibling raises: a var that fails its schema is a
    malformed request, not a conflict with stored state, and the vars API
    contract answers 400 for it.

    An empty `vars` is still validated when the template has a projection, so
    that emptying a deployment's vars cannot slip past a `required` the schema
    declares. Only a template with no schema at all short-circuits -- exactly
    the shape of `validate_user_values`.
    """
    if not vars and not vars_projection:
        return
    if not vars_projection:
        raise ValidationException("vars are not supported on this product template")

    declared = vars_projection.get("properties") or {}
    if not vars_projection.get("additionalProperties", False):
        # Checked ahead of jsonschema for the error message alone: an
        # `additionalProperties` violation reports the root as its path, which
        # would leave the caller guessing which key was refused. Key names are
        # not secret; values are, and none appears here.
        undeclared = sorted(set(vars) - set(declared))
        if undeclared:
            raise ValidationException(
                "vars not declared by this product template: " + ", ".join(undeclared)
            )

    instance = {k: _coerce_var(v, declared.get(k)) for k, v in vars.items()}
    failure: str | None = None
    try:
        jsonschema_validate(instance=instance, schema=vars_projection)
    except SchemaError as exc:
        raise IntegrityException(
            f"product template has an invalid values_schema_json: {exc.message}"
        ) from exc
    except ValidationError as exc:
        failure = _var_error(exc)
    if failure is not None:
        # Raised outside the handler so the ValidationError, which holds the
        # value, is not even attached as `__context__`.
        raise ValidationException(failure)


def _document_error(
    exc: ValidationError, values_schema_json: dict[str, Any], var_keys: set[str]
) -> str:
    """Locate a full-document failure in the channel it belongs to.

    Like `_var_error`, never quotes `exc.message`: the document carries var
    values. A missing key is named from the schema, so a `required` failure
    points at the field to fill in rather than at the object holding it.
    """
    path: list[Any] = list(exc.absolute_path)
    instance = exc.instance
    if isinstance(instance, dict):
        if exc.validator == "required" and isinstance(exc.validator_value, list):
            path.extend([k for k in exc.validator_value if k not in instance][:1])
        elif exc.validator == "dependentRequired" and isinstance(exc.validator_value, dict):
            path.extend(
                [
                    dep
                    for trigger, deps in exc.validator_value.items()
                    if trigger in instance and isinstance(deps, list)
                    for dep in deps
                    if dep not in instance
                ][:1]
            )
    constraint = f'failed constraint "{exc.validator}"'
    if not path:
        return f"values: {constraint}"
    top = path[0]
    properties = values_schema_json.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    if top in properties:
        is_var = _target(properties[top]) == TARGET_RUNTIME
    else:
        # Undeclared: a submitted var, or one a rule demands of an open vars half.
        is_var = top in var_keys or values_schema_json.get(VARS_ADDITIONAL_KEY) is True
    channel = "vars" if is_var else "user_values_json"
    return f"{channel}.{'.'.join(str(p) for p in path)}: {constraint}"


def validate_document(
    user_values_json: dict[str, Any] | None,
    vars: dict[str, Any],
    values_schema_json: dict[str, Any] | None,
    *,
    error: type[CaelusException] = IntegrityException,
) -> None:
    """Validate chart values and vars together against the whole schema.

    The document is the shape a client submits: both halves merged into one
    object, vars coerced as `validate_vars` coerces them. This is what makes a
    root conditional spanning both halves work. It runs in addition to the
    per-projection checks, which still decide which keys each half may hold,
    so the schema is applied without its root key-set keywords (D2).

    `error` is the caller's status contract (D4): 409 on the deployment
    endpoints, 400 on the vars API.
    """
    if not values_schema_json:
        return
    declared = (derive_projections(values_schema_json).vars or {}).get("properties") or {}
    document = dict(user_values_json or {})
    document.update({k: _coerce_var(v, declared.get(k)) for k, v in vars.items()})
    schema = {k: v for k, v in values_schema_json.items() if k not in KEY_SET_KEYWORDS}
    failure: str | None = None
    try:
        jsonschema_validate(instance=document, schema=schema)
    except SchemaError as exc:
        raise IntegrityException(
            f"product template has an invalid values_schema_json: {exc.message}"
        ) from exc
    except ValidationError as exc:
        failure = _document_error(exc, values_schema_json, set(vars))
    if failure is not None:
        raise error(failure)  # outside the handler, as in `validate_vars`


def merge_values_scoped(
    defaults: dict[str, Any] | None,
    user_scope_delta: dict[str, Any] | None,
    system_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge defaults + user scope + system overrides with deterministic precedence."""
    if defaults is not None and not isinstance(defaults, dict):
        raise IntegrityException("defaults must be an object")
    if user_scope_delta is not None and not isinstance(user_scope_delta, dict):
        raise IntegrityException("user_scope_delta must be an object")
    if system_overrides is not None and not isinstance(system_overrides, dict):
        raise IntegrityException("system_overrides must be an object")

    merged = deepcopy(defaults) if defaults is not None else {}
    if user_scope_delta is not None:
        merged = deep_merge(merged, deepcopy(user_scope_delta))
    if system_overrides is not None:
        merged = deep_merge(merged, deepcopy(system_overrides))
    return merged
