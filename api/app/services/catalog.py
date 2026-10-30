"""The git-managed product catalog: document format, validation, reconciliation.

`products/catalog/<slug>/` is the desired state for a *published* product: its
`<slug>.yaml` document, icon, screenshots and `releases.yaml`. The `product`,
`product_template_version` and `product_release` rows are the applied state.
This module holds both halves of that relationship:

- the catalog document models and their validation rules, which run without a
  database so `catalog lint` can gate a pull request in CI, and
- `CatalogReconciler`, which closes the gap between the two.

For templates the reconciler has two verbs, insert and repoint, plus filling
in a template's `version` while it is still null. It never updates a template's
spec fields and never soft-deletes one, so `product_template_version` stays an
append-only ledger that deployments can keep referencing. Product fields,
screenshots and releases are made to equal the catalog on every run, so a
re-run against an unchanged catalog is a no-op.

It deliberately does *not* live in `app/services/reconcile.py`. Despite the
name it shares nothing with `DeploymentReconciler`: no `Provisioner`, no Helm,
no `reconcile_constants`; it runs once at startup rather than per job, and it
aborts the whole run on failure instead of marking one row errored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from jsonschema import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlmodel import Session, select

from app.models import (
    ListingFeature,
    ListingLink,
    ProductORM,
    ProductReleaseORM,
    ProductTemplateVersionORM,
    ProductVisibility,
    ScreenshotCredit,
    StoredScreenshot,
    screenshot_thumbnail_path,
)
from app.services.errors import CaelusException, ValidationException
from app.services.images import (
    SCREENSHOTS_MAX_COUNT,
    SCREENSHOTS_MAX_TOTAL_BYTES,
    check_screenshot,
    generate_icon_filename,
    process_icon,
    render_screenshot,
    save_icon,
    save_static,
    screenshot_rel_path,
)
from app.services.template_values import check_var_markers

logger = logging.getLogger(__name__)

# The document contract this build understands. A file declaring anything else
# is rejected rather than applied with the parts we happen to recognize.
CATALOG_SCHEMA_VERSION = 1

# Emitted at the catalog root so editors can offer completion; documents live
# one folder down, hence the `../` in the modeline.
SCHEMA_FILENAME = "catalog.schema.json"
SCHEMA_MODELINE = f"# yaml-language-server: $schema=../{SCHEMA_FILENAME}"
RELEASES_FILENAME = "releases.yaml"
RELEASE_NOTES_MAX_CHARS = 8000

# Arbitrary but fixed: the key concurrent `catalog apply` runs contend on.
CATALOG_ADVISORY_LOCK_KEY = 0x6361656C_7573_0001

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CatalogError(CaelusException):
    """A catalog document, directory, or reconciliation is invalid.

    Deliberately *not* a `ValidationException`: the catalog never crosses the
    REST surface, and `api/app/api/util.py` maps exceptions by exact type, so a
    near-miss subclass would silently become a 500 rather than a 400.
    """


# ---------------------------------------------------------------------------
# Document models
# ---------------------------------------------------------------------------


class CatalogModel(BaseModel):
    """Base for every catalog block.

    `extra="forbid"` is load-bearing rather than tidiness. A mistyped key would
    otherwise be dropped in silence, and — the case that matters — a
    `visibility` key would look accepted while the reconciler ignored it. The
    catalog owns what a product *is*; the database owns whether it is currently
    offered.
    """

    model_config = ConfigDict(extra="forbid")


def _validate_asset_path(v: str, what: str) -> str:
    path = Path(v)
    if not v or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{what} '{v}' must be a relative path inside the product's folder")
    return v


class CatalogScreenshot(CatalogModel):
    # Path to an image file, relative to the product's catalog folder.
    file: str
    caption: str = Field(min_length=1)
    form: Literal["desktop", "mobile"]
    credit: ScreenshotCredit | None = None

    @field_validator("file")
    @classmethod
    def _validate_file(cls, v: str) -> str:
        return _validate_asset_path(v, "screenshot file")


class ProductBlock(CatalogModel):
    """The catalog-managed fields of a `product` row."""

    slug: str
    name: str
    tagline: str | None = None
    # The long description, as Markdown.
    description: str | None = None
    category: str | None = None
    replaces: str | None = None
    # Path to an image file, relative to the product's catalog folder.
    icon: str | None = None
    license: str | None = None
    features: list[ListingFeature] = Field(default_factory=list)
    links: list[ListingLink] = Field(default_factory=list)
    screenshots: list[CatalogScreenshot] = Field(default_factory=list, max_length=SCREENSHOTS_MAX_COUNT)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                f"slug '{v}' must be lowercase alphanumeric words separated by hyphens"
            )
        return v

    @field_validator("icon")
    @classmethod
    def _validate_icon(cls, v: str | None) -> str | None:
        return v if v is None else _validate_asset_path(v, "icon")


class GithubReleaseSource(CatalogModel):
    type: Literal["github-release"]
    repo: str


class DockerTagSource(CatalogModel):
    type: Literal["docker-tag"]
    image: str


class HelmChartSource(CatalogModel):
    """A chart repository, for products whose version rides on the chart.

    Several products deploy a wrapper chart that pins the application image
    itself, so there is no image tag in `system_values` to bump: the artifact
    that actually moves is `template.chart_version`.
    """

    type: Literal["helm-chart"]
    repo: str
    chart: str


UpstreamSource = Annotated[
    Union[GithubReleaseSource, DockerTagSource, HelmChartSource],
    Field(discriminator="type"),
]


class UpstreamBlock(CatalogModel):
    """Release-detection metadata.

    Consumed only by release-detection tooling: it is never applied to the
    cluster and never persisted on a template row.
    """

    source: UpstreamSource
    # Selects eligible upstream tags. The `version` group orders candidates;
    # the winning tag itself is written verbatim, so no format string is needed.
    match: str
    # Dotted path into this document identifying where the winning tag goes.
    version_path: str

    @field_validator("match")
    @classmethod
    def _validate_match(cls, v: str) -> str:
        try:
            compiled = re.compile(v)
        except re.error as exc:
            raise ValueError(f"match '{v}' is not a valid regular expression: {exc}") from exc
        if "version" not in compiled.groupindex:
            raise ValueError(
                f"match '{v}' must define a named capture group 'version' to order candidates"
            )
        return v


class TemplateBlock(CatalogModel):
    """Exactly the fields that constitute a template version.

    `system_values` and `values_schema` are written to the row verbatim, with no
    templating or substitution, so the file content is what gets applied and
    review is WYSIWYG. The pinned application image tag lives inside
    `system_values`.
    """

    chart_ref: str
    chart_version: str
    chart_digest: str | None = None
    system_values: dict[str, Any] = Field(default_factory=dict)
    values_schema: dict[str, Any] | None = None

    @field_validator("system_values")
    @classmethod
    def _validate_auth_access(cls, v: dict[str, Any]) -> dict[str, Any]:
        # A template that turns Sign in with Freepod on says who may sign in,
        # so no product admits every Freepod account by omission
        # (app-auth-chart-contract).
        auth = v.get("auth")
        if isinstance(auth, dict) and auth.get("enabled") is True and "access" not in auth:
            raise ValueError("system_values.auth enables Sign in with Freepod, so it must also set auth.access")
        return v

    @field_validator("values_schema")
    @classmethod
    def _validate_values_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        try:
            validator_for(v).check_schema(v)
        # SchemaError is not a subclass of jsonschema's ValidationError, so it
        # must be caught explicitly or a malformed schema escapes as a crash.
        except SchemaError as exc:
            raise ValueError(f"values_schema is not a valid JSON Schema: {exc.message}") from exc
        try:
            # Same rules the API applies to a hand-made template, so a bad
            # marker fails `catalog lint` in CI rather than on rollout.
            check_var_markers(v)
        except ValidationException as exc:
            raise ValueError(f"values_schema: {exc}") from exc
        return v


class CatalogDocument(CatalogModel):
    """One `products/catalog/<slug>/<slug>.yaml` document."""

    schema_version: int
    product: ProductBlock
    upstream: UpstreamBlock
    template: TemplateBlock

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, v: int) -> int:
        if v != CATALOG_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {v}; this build understands "
                f"{CATALOG_SCHEMA_VERSION}"
            )
        return v


class CatalogRelease(CatalogModel):
    """One entry of a product's `releases.yaml`."""

    version: str = Field(min_length=1)
    notes: str = Field(min_length=1, max_length=RELEASE_NOTES_MAX_CHARS)


@dataclass(frozen=True)
class LoadedScreenshot:
    """A declared screenshot with its validated source bytes."""

    declared: CatalogScreenshot
    source: bytes


@dataclass(frozen=True)
class CatalogFile:
    """A validated document together with where it came from.

    The path is carried alongside so that every error can name the file an
    operator has to edit.
    """

    path: Path
    document: CatalogDocument
    icon_bytes: bytes | None = None
    screenshots: tuple[LoadedScreenshot, ...] = ()
    # Newest first, as in the file; empty when the folder has no releases file.
    releases: tuple[CatalogRelease, ...] = ()

    @property
    def slug(self) -> str:
        return self.document.product.slug


def catalog_document_json_schema() -> dict[str, Any]:
    """JSON Schema for a catalog document, for editor completion."""
    return CatalogDocument.model_json_schema()


def write_json_schema(catalog_dir: Path) -> Path:
    """Write the document schema next to the catalog files.

    The models above are the single source of truth for the document contract;
    this file is derived from them. It exists only so the `$schema` modeline in
    each catalog file gives editors completion and inline validation — nothing
    reads it at runtime, where validation goes through the models directly.
    """
    path = catalog_dir / SCHEMA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog_document_json_schema(), indent=2) + "\n")
    return path


def check_json_schema(catalog_dir: Path) -> None:
    """Fail when the committed schema is no longer what the models produce.

    A generated artifact in version control is only one source of truth as long
    as something proves it is still derived. Without this check, editing a model
    and forgetting to regenerate would leave editors validating catalog files
    against a contract the reconciler no longer enforces.
    """
    path = catalog_dir / SCHEMA_FILENAME
    if not path.exists():
        # The schema is an editor convenience, not part of the contract: a
        # catalog directory without one is valid.
        return
    try:
        committed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{path}: cannot be read as JSON: {exc}") from exc
    if committed != catalog_document_json_schema():
        raise CatalogError(
            f"{path} is out of date with the catalog document models. "
            f"Regenerate it with `caelus catalog lint --write-schema`."
        )


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def spec_hash(
    *,
    chart_ref: str | None,
    chart_version: str | None,
    chart_digest: str | None,
    system_values: dict[str, Any] | None,
    values_schema: dict[str, Any] | None,
) -> str:
    """Hash the five fields that constitute a template's spec.

    Computed from row (or document) contents at read time rather than stored, so
    it cannot go stale when the field set changes, and — the property graduation
    depends on — it ignores how a row came to exist. A hand-made template must
    be recognizable, or `catalog curate` would produce a file whose first apply
    inserted a duplicate of the template it was generated from.

    `sort_keys` makes key ordering in the source YAML irrelevant.
    """
    payload = {
        "chart_ref": chart_ref,
        "chart_version": chart_version,
        "chart_digest": chart_digest,
        "system_values": system_values or {},
        "values_schema": values_schema,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def template_spec_hash(template: ProductTemplateVersionORM) -> str:
    return spec_hash(
        chart_ref=template.chart_ref,
        chart_version=template.chart_version,
        chart_digest=template.chart_digest,
        system_values=template.system_values_json,
        values_schema=template.values_schema_json,
    )


def document_spec_hash(document: CatalogDocument) -> str:
    return spec_hash(
        chart_ref=document.template.chart_ref,
        chart_version=document.template.chart_version,
        chart_digest=document.template.chart_digest,
        system_values=document.template.system_values,
        values_schema=document.template.values_schema,
    )


def load_document(path: Path, *, catalog_dir: Path) -> CatalogFile:
    """Parse and validate one product folder's document and its assets.

    Every failure names the file to edit. Asset paths resolve against the
    document's folder, ``path.parent``.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise CatalogError(f"{path}: cannot be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path}: is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: must contain a YAML mapping")

    try:
        document = CatalogDocument.model_validate(raw)
    except ValidationError as exc:
        raise CatalogError(f"{path}: {_format_validation_error(exc)}") from exc

    if document.product.slug != path.stem or path.parent.name != path.stem:
        raise CatalogError(
            f"{path}: declares product.slug '{document.product.slug}' but lives at "
            f"'{path.parent.name}/{path.name}'; the slug must equal both the folder name "
            f"and the filename stem"
        )

    return CatalogFile(
        path=path,
        document=document,
        icon_bytes=_load_icon(document, path=path),
        screenshots=_load_screenshots(document, path=path),
        releases=_load_releases(path.parent / RELEASES_FILENAME),
    )


def _resolve_asset(rel: str, *, path: Path, what: str) -> Path:
    """Resolve an asset path against the document's folder, refusing escapes.

    Each product folder must stay a self-contained unit for apply, lint, the
    image build and the upgrader's patch allowlist, so a path leaving it (via a
    symlink, say) is refused.
    """
    folder = path.parent.resolve()
    resolved = (folder / rel).resolve()
    if not resolved.is_relative_to(folder):
        raise CatalogError(f"{path}: {what} '{rel}' resolves outside the product folder {folder}")
    if not resolved.is_file():
        raise CatalogError(f"{path}: {what} '{rel}' does not exist")
    return resolved


def _load_icon(document: CatalogDocument, *, path: Path) -> bytes | None:
    """Read and process the document's icon, or return None when it declares no icon."""
    if document.product.icon is None:
        return None
    icon_path = _resolve_asset(document.product.icon, path=path, what="icon")
    try:
        return process_icon(icon_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CatalogError(
            f"{path}: icon '{document.product.icon}' cannot be processed as an image: {exc}"
        ) from exc


def _load_screenshots(document: CatalogDocument, *, path: Path) -> tuple[LoadedScreenshot, ...]:
    """Read and check each declared screenshot; rendering waits for the reconciler."""
    loaded = []
    total = 0
    for shot in document.product.screenshots:
        source_path = _resolve_asset(shot.file, path=path, what="screenshot")
        try:
            source = source_path.read_bytes()
            check_screenshot(source)
        except (OSError, ValueError) as exc:
            raise CatalogError(f"{path}: screenshot '{shot.file}' {exc}") from exc
        total += len(source)
        loaded.append(LoadedScreenshot(declared=shot, source=source))
    if total > SCREENSHOTS_MAX_TOTAL_BYTES:
        raise CatalogError(
            f"{path}: screenshots total {total} bytes; the limit per product is "
            f"{SCREENSHOTS_MAX_TOTAL_BYTES} bytes (5 MB)"
        )
    return tuple(loaded)


def _load_releases(path: Path) -> tuple[CatalogRelease, ...]:
    """Parse a product's releases file; a folder without one has no releases."""
    if not path.exists():
        return ()
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise CatalogError(f"{path}: cannot be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path}: is not valid YAML: {exc}") from exc
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CatalogError(f"{path}: must contain a YAML list of releases, newest first")

    releases = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, dict) and not isinstance(item.get("version", ""), str):
            # YAML reads `3.10` as a float; refuse rather than guess its spelling.
            raise CatalogError(f"{path}: entry {index}: version must be quoted as a string")
        try:
            release = CatalogRelease.model_validate(item)
        except ValidationError as exc:
            raise CatalogError(f"{path}: entry {index}: {_format_validation_error(exc)}") from exc
        if release.version in seen:
            raise CatalogError(f"{path}: version '{release.version}' is listed more than once")
        seen.add(release.version)
        releases.append(release)
    return tuple(releases)


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "document"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def load_catalog(catalog_dir: Path) -> list[CatalogFile]:
    """Load and validate every document in a catalog directory.

    A directory that does not exist or cannot be read is an error rather than an
    empty desired state: failing to read the desired state is not the same as
    the desired state being empty, and treating it as such would uncurate every
    product at once. An *empty* directory is valid — it is the state every
    environment is in before its first product is curated.
    """
    if not catalog_dir.exists():
        raise CatalogError(f"catalog directory {catalog_dir} does not exist")
    if not catalog_dir.is_dir():
        raise CatalogError(f"catalog path {catalog_dir} is not a directory")
    try:
        children = sorted(catalog_dir.iterdir())
    except OSError as exc:
        raise CatalogError(f"catalog directory {catalog_dir} cannot be read: {exc}") from exc

    paths = []
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix in (".yaml", ".yml"):
            # A document from the flat layout; fail loudly rather than skip it.
            raise CatalogError(
                f"{child}: catalog documents live in per-product folders; move it to "
                f"{catalog_dir / child.stem / (child.stem + '.yaml')}"
            )
        if not child.is_dir():
            continue
        document = child / f"{child.name}.yaml"
        if not document.is_file():
            raise CatalogError(f"{child}: product folder has no {child.name}.yaml document")
        paths.append(document)

    entries = [load_document(path, catalog_dir=catalog_dir) for path in paths]

    # Folder and filename both carry the slug, so duplicates cannot arise from
    # files alone; the check stays as a guard for any future layout change.
    by_slug: dict[str, Path] = {}
    for entry in entries:
        if (previous := by_slug.get(entry.slug)) is not None:
            raise CatalogError(
                f"duplicate product.slug '{entry.slug}' declared by {previous} and {entry.path}"
            )
        by_slug[entry.slug] = entry.path

    return entries


# ---------------------------------------------------------------------------
# Generating documents from database state (`catalog curate`)
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Derive a catalog slug from a product name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise CatalogError(f"cannot derive a catalog slug from product name '{name}'")
    return slug


def placeholder_upstream() -> UpstreamBlock:
    """The `upstream` block `catalog curate` emits.

    Release-detection metadata is not derivable from the database, so curate
    emits a valid placeholder for the operator to complete rather than omitting
    the block — a curated product with no upstream declaration would silently
    never be checked for updates.
    """
    return UpstreamBlock(
        source=GithubReleaseSource(type="github-release", repo="OWNER/REPO"),
        match=r"^v(?P<version>.+)$",
        version_path="template.system_values.image.tag",
    )


def document_from_product(
    product: ProductORM,
    template: ProductTemplateVersionORM,
    *,
    slug: str,
    icon: str | None,
) -> CatalogDocument:
    """Build a catalog document from current database state.

    Round-trip fidelity is load-bearing: applying the result to the database it
    came from must match the existing template by spec equality and insert
    nothing, so the first pull request for a product is a verified no-op.
    """
    return CatalogDocument(
        schema_version=CATALOG_SCHEMA_VERSION,
        product=ProductBlock(
            slug=slug,
            name=product.name,
            tagline=product.tagline,
            description=product.description,
            category=product.category,
            replaces=product.replaces,
            icon=icon,
            license=product.license,
            features=product.features or [],
            links=product.links or [],
        ),
        upstream=placeholder_upstream(),
        template=TemplateBlock(
            chart_ref=template.chart_ref,
            chart_version=template.chart_version,
            chart_digest=template.chart_digest,
            system_values=template.system_values_json or {},
            values_schema=template.values_schema_json,
        ),
    )


def curate_product(session: Session, *, identifier: str, catalog_dir: Path) -> list[Path]:
    """Write a product's catalog folder (document and icon), and return the paths written.

    Screenshots are not written: static storage holds only their renditions,
    not the committed sources.

    ``identifier`` is the product's slug or its name, case-insensitively: a
    product being graduated has no slug yet, since only the reconciler assigns
    one.

    Writing the files does not curate the product. Curation follows from a
    catalog file existing in a *rolled-out* image, so `curated` and `slug` are
    deliberately left untouched here — that is what keeps file presence the
    single source of truth.
    """
    product = _find_product(session, identifier)
    if product.template_id is None:
        raise CatalogError(
            f"product '{product.name}' has no canonical template; set one before curating it"
        )
    template = session.get(ProductTemplateVersionORM, product.template_id)
    if template is None or template.deleted_at is not None:
         raise CatalogError(
             f"product '{product.name}' points at template {product.template_id}, which is missing"
         )

    slug = product.slug or slugify(product.name)
    icon_bytes = _read_product_icon(product)
    icon_rel = "icon.png" if icon_bytes is not None else None
    document = document_from_product(product, template, slug=slug, icon=icon_rel)

    folder = catalog_dir / slug
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if icon_bytes is not None:
        icon_path = folder / icon_rel
        icon_path.write_bytes(icon_bytes)
        written.append(icon_path)

    document_path = folder / f"{slug}.yaml"
    document_path.write_text(dump_document(document))
    written.append(document_path)
    written.append(write_json_schema(catalog_dir))
    return written


def _find_product(session: Session, identifier: str) -> ProductORM:
    products = session.exec(
        select(ProductORM).where(ProductORM.deleted_at == None)  # noqa: E711
    ).all()
    for product in products:
        if product.slug == identifier:
            return product
    matches = [p for p in products if p.name.lower() == identifier.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CatalogError(f"no product found with slug or name '{identifier}'")
    raise CatalogError(f"'{identifier}' matches {len(matches)} products; use a slug")


def _read_product_icon(product: ProductORM) -> bytes | None:
    """The product's stored icon bytes, or None when it has none."""
    if not product.rel_icon_path:
        return None

    from app.config import get_settings

    path = get_settings().static_path / product.rel_icon_path
    if not path.is_file():
        raise CatalogError(
            f"product '{product.name}' references icon {product.rel_icon_path}, "
            f"which is missing from static storage"
        )
    return path.read_bytes()


def dump_document(document: CatalogDocument) -> str:
    """Serialize a document in declaration order, with the editor modeline."""
    body = yaml.safe_dump(
        document.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return f"{SCHEMA_MODELINE}\n{body}"


# ---------------------------------------------------------------------------
# Template versions (product-releases)
# ---------------------------------------------------------------------------

_TEMPLATE_SCALARS = ("chart_ref", "chart_version", "chart_digest")


def derive_version(upstream: UpstreamBlock, spec: dict[str, Any]) -> str | None:
    """The `version` group of ``upstream.match`` applied at ``version_path``.

    ``spec`` holds a template's `chart_ref`, `chart_version`, `chart_digest` and
    `system_values`, from a document or a row alike. A path outside the
    template, one that does not resolve, or a value that does not match yields
    None. Matching uses `re.match`, as the upgrade skill does.
    """
    parts = upstream.version_path.split(".")
    if len(parts) < 2 or parts[0] != "template":
        return None
    if parts[1] in _TEMPLATE_SCALARS:
        if len(parts) != 2:
            return None
        value: Any = spec.get(parts[1])
    elif parts[1] == "system_values":
        value = spec.get("system_values") or {}
        for key in parts[2:]:
            if not isinstance(value, dict) or key not in value:
                return None
            value = value[key]
    else:
        return None
    # An unquoted tag such as 261007 arrives from YAML as an int.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    found = re.match(upstream.match, str(value))
    return found.group("version") if found else None


def _document_spec(document: CatalogDocument) -> dict[str, Any]:
    block = document.template
    return {
        "chart_ref": block.chart_ref,
        "chart_version": block.chart_version,
        "chart_digest": block.chart_digest,
        "system_values": block.system_values,
    }


def _row_spec(template: ProductTemplateVersionORM) -> dict[str, Any]:
    return {
        "chart_ref": template.chart_ref,
        "chart_version": template.chart_version,
        "chart_digest": template.chart_digest,
        "system_values": template.system_values_json or {},
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogAction:
    """One change the reconciler made (or, in a dry run, would make)."""

    kind: str
    slug: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind} {self.slug}: {self.detail}"


@dataclass
class CatalogApplyReport:
    actions: list[CatalogAction] = field(default_factory=list)
    dry_run: bool = False

    def record(self, kind: str, slug: str, detail: str) -> None:
        self.actions.append(CatalogAction(kind=kind, slug=slug, detail=detail))

    def of_kind(self, kind: str) -> list[CatalogAction]:
        return [action for action in self.actions if action.kind == kind]


class CatalogReconciler:
    """Apply a catalog directory to the database.

    Constructed per run and used once::

        CatalogReconciler(session=session, catalog_dir=path, commit_sha=sha).apply()

    Failure aborts the whole run and rolls back: a partially applied catalog is
    worse than an unapplied one, and the init container's non-zero exit is what
    keeps the previous pods serving.
    """

    def __init__(
        self,
        *,
        session: Session,
        catalog_dir: Path,
        commit_sha: str | None = None,
    ) -> None:
        self._session = session
        self._catalog_dir = Path(catalog_dir)
        self._commit_sha = commit_sha

    # -- entry point --------------------------------------------------------

    def apply(self, *, dry_run: bool = False) -> CatalogApplyReport:
        """Reconcile the catalog directory into the database.

        Everything happens in one transaction under an advisory lock, so
        concurrent init containers across replicas cannot both observe a missing
        template and insert duplicates.
        """
        # Validate every document before touching the database, so one bad file
        # cannot leave a half-applied catalog behind.
        entries = load_catalog(self._catalog_dir)
        report = CatalogApplyReport(dry_run=dry_run)

        try:
            self._lock()
            for entry in entries:
                self._apply_document(entry, report=report, dry_run=dry_run)
            self._release_undeclared({entry.slug for entry in entries}, report=report)

            if dry_run:
                # Roll back rather than commit: a dry run reports the plan by
                # computing it, which is the only way to report it accurately.
                self._session.rollback()
            else:
                self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        logger.info(
            "Catalog %s: %s documents, %s actions",
            "planned" if dry_run else "applied",
            len(entries),
            len(report.actions),
        )
        return report

    def _lock(self) -> None:
        """Serialize concurrent runs for the duration of the transaction."""
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_ADVISORY_LOCK_KEY}
        )

    # -- per document -------------------------------------------------------

    def _apply_document(
        self, entry: CatalogFile, *, report: CatalogApplyReport, dry_run: bool
    ) -> None:
        document = entry.document
        product = self._resolve_product(entry, report=report)

        block = document.product
        product.name = block.name
        product.tagline = block.tagline
        product.description = block.description
        product.category = block.category
        product.replaces = block.replaces
        product.license = block.license
        product.features = [feature.model_dump(mode="json") for feature in block.features]
        product.links = [link.model_dump(mode="json") for link in block.links]
        product.curated = True
        product.slug = document.product.slug
        # `visibility` is intentionally absent here: it is initialized on
        # creation only (see _resolve_product) and never written again, so an
        # administrator's change survives every subsequent rollout.
        self._session.add(product)
        self._session.flush()

        self._materialize_icon(entry, product=product, report=report, dry_run=dry_run)
        self._materialize_screenshots(entry, product=product, report=report, dry_run=dry_run)

        template = self._resolve_template(entry, product=product, report=report)
        if product.template_id != template.id:
            report.record(
                "canonical-repointed",
                entry.slug,
                f"template_id {product.template_id} -> {template.id}",
            )
            product.template_id = template.id
            self._session.add(product)
            self._session.flush()

        self._stamp_versions(entry, product=product, report=report)
        self._sync_releases(entry, product=product, report=report)

    def _resolve_product(self, entry: CatalogFile, *, report: CatalogApplyReport) -> ProductORM:
        """Find the product this file declares, adopting or creating as needed."""
        slug = entry.slug

        # Curated products are addressed by slug, which is independent of `name`
        # so that renaming a product in its catalog file updates the existing row
        # rather than orphaning it.
        product = self._session.exec(
            select(ProductORM).where(
                ProductORM.slug == slug,
                ProductORM.curated == True,  # noqa: E712
                ProductORM.deleted_at == None,  # noqa: E711
            )
        ).one_or_none()
        if product is not None:
            return product

        # Adoption is the one query that deliberately selects a *non*-curated
        # product: it is the graduation path for a hand-tuned product whose
        # catalog file was just merged. Matching on name is safe here precisely
        # because the row has no slug yet.
        name = entry.document.product.name
        adopted = self._session.exec(
            select(ProductORM).where(
                ProductORM.curated == False,  # noqa: E712
                ProductORM.deleted_at == None,  # noqa: E711
                ProductORM.slug == None,  # noqa: E711
            )
        ).all()
        for candidate in adopted:
            if candidate.name.lower() == name.lower():
                logger.info(
                    "Adopting product id=%s name=%s into the catalog as slug=%s",
                    candidate.id,
                    candidate.name,
                    slug,
                )
                report.record("product-adopted", slug, f"adopted product id={candidate.id}")
                return candidate

        # New products start hidden, so merging a catalog change can never by
        # itself put a product in front of end users.
        product = ProductORM(
            name=name,
            curated=True,
            slug=slug,
            visibility=ProductVisibility.ADMIN,
        )
        self._session.add(product)
        self._session.flush()
        logger.info("Created curated product id=%s slug=%s", product.id, slug)
        report.record("product-created", slug, f"created product id={product.id}")
        return product

    def _resolve_template(
        self, entry: CatalogFile, *, product: ProductORM, report: CatalogApplyReport
    ) -> ProductTemplateVersionORM:
        """Match the document's spec against existing rows, inserting if new."""
        wanted = document_spec_hash(entry.document)
        existing = self._session.exec(
            select(ProductTemplateVersionORM).where(
                ProductTemplateVersionORM.product_id == product.id,
                ProductTemplateVersionORM.deleted_at == None,  # noqa: E711
            )
        ).all()
        for template in existing:
            # Matching ignores `catalog_commit`: a hand-authored row is a valid
            # match, which is what makes graduation insert nothing.
            if template_spec_hash(template) == wanted:
                return template

        block = entry.document.template
        template = ProductTemplateVersionORM(
            product_id=product.id,
            chart_ref=block.chart_ref,
            chart_version=block.chart_version,
            chart_digest=block.chart_digest,
            system_values_json=block.system_values,
            values_schema_json=block.values_schema,
            catalog_commit=self._commit_sha,
            version=derive_version(entry.document.upstream, _document_spec(entry.document)),
        )
        self._session.add(template)
        self._session.flush()
        logger.info(
            "Inserted template id=%s for slug=%s catalog_commit=%s",
            template.id,
            entry.slug,
            self._commit_sha,
        )
        report.record(
            "template-inserted",
            entry.slug,
            f"inserted template id={template.id} chart_version={block.chart_version}",
        )
        return template

    def _materialize_icon(
        self,
        entry: CatalogFile,
        *,
        product: ProductORM,
        report: CatalogApplyReport,
        dry_run: bool,
    ) -> None:
        """Ensure the product's processed icon exists in static storage.

        Static storage is a per-environment volume while the catalog is shared
        across environments, so presence is verified on disk rather than
        inferred from the stored path — otherwise a restore onto a fresh volume
        would leave every product with a correct path and no file.
        """
        if entry.icon_bytes is None:
            # A document that declares no icon leaves the product's existing
            # icon alone: the catalog declares icons, not their absence, and
            # `catalog curate` always emits one for a product that has it.
            return

        from app.config import get_settings

        rel_path = generate_icon_filename(entry.icon_bytes)
        static_path = get_settings().static_path
        path_matches = product.rel_icon_path == rel_path
        file_present = (static_path / rel_path).is_file()

        if path_matches and file_present:
            return

        if not dry_run:
            save_icon(entry.icon_bytes, rel_path)
        if not path_matches:
            product.rel_icon_path = rel_path
            self._session.add(product)
            self._session.flush()
        report.record(
            "icon-materialized",
            entry.slug,
            f"wrote {rel_path}" if not path_matches else f"repopulated {rel_path}",
        )

    def _materialize_screenshots(
        self,
        entry: CatalogFile,
        *,
        product: ProductORM,
        report: CatalogApplyReport,
        dry_run: bool,
    ) -> None:
        """Ensure both renditions of every screenshot exist, and list them in order.

        Rendering is the expensive step, so it runs only when a rendition file
        is missing; like icons, presence is verified on disk rather than
        inferred from the stored entries.
        """
        from app.config import get_settings

        static_path = get_settings().static_path
        stored = []
        for shot in entry.screenshots:
            rel_path = screenshot_rel_path(shot.source)
            thumb_path = screenshot_thumbnail_path(rel_path)
            missing = [
                path for path in (rel_path, thumb_path) if not (static_path / path).is_file()
            ]
            if missing:
                if not dry_run:
                    try:
                        full, thumb = render_screenshot(shot.source)
                    except ValueError as exc:
                        raise CatalogError(
                            f"{entry.path}: screenshot '{shot.declared.file}' {exc}"
                        ) from exc
                    save_static(full, rel_path)
                    save_static(thumb, thumb_path)
                report.record("screenshot-materialized", entry.slug, f"wrote {rel_path}")
            declared = shot.declared
            stored.append(
                StoredScreenshot(
                    path=rel_path, caption=declared.caption, form=declared.form, credit=declared.credit
                ).model_dump(mode="json")
            )
        if product.screenshots != stored:
            product.screenshots = stored
            self._session.add(product)
            self._session.flush()

    def _stamp_versions(
        self, entry: CatalogFile, *, product: ProductORM, report: CatalogApplyReport
    ) -> None:
        """Fill in the null `version` of the product's template rows.

        The one write the reconciler makes to an existing template row, and only
        ever from null: a set version is history and is never rewritten.
        """
        unstamped = self._session.exec(
            select(ProductTemplateVersionORM).where(
                ProductTemplateVersionORM.product_id == product.id,
                ProductTemplateVersionORM.deleted_at == None,  # noqa: E711
                ProductTemplateVersionORM.version == None,  # noqa: E711
            )
        ).all()
        for template in unstamped:
            version = derive_version(entry.document.upstream, _row_spec(template))
            if version is None:
                continue
            template.version = version
            self._session.add(template)
            report.record("version-stamped", entry.slug, f"template {template.id} -> {version}")
        self._session.flush()

    def _sync_releases(
        self, entry: CatalogFile, *, product: ProductORM, report: CatalogApplyReport
    ) -> None:
        """Make the product's release rows equal its `releases.yaml`."""
        existing = {
            release.version: release
            for release in self._session.exec(
                select(ProductReleaseORM).where(ProductReleaseORM.product_id == product.id)
            ).all()
        }
        wanted = {release.version for release in entry.releases}

        for version, release in existing.items():
            if version not in wanted:
                self._session.delete(release)
                report.record("release-deleted", entry.slug, version)
        # Deletions first, so a version moving position never collides.
        self._session.flush()

        now = datetime.now(UTC)
        for position, declared in enumerate(entry.releases):
            release = existing.get(declared.version)
            if release is None:
                self._session.add(
                    ProductReleaseORM(
                        product_id=product.id,
                        version=declared.version,
                        notes=declared.notes,
                        position=position,
                    )
                )
                report.record("release-inserted", entry.slug, declared.version)
            elif (release.notes, release.position) != (declared.notes, position):
                release.notes = declared.notes
                release.position = position
                release.updated_at = now
                self._session.add(release)
                report.record("release-updated", entry.slug, declared.version)
        self._session.flush()

    def _release_undeclared(self, declared: set[str], *, report: CatalogApplyReport) -> None:
        """Uncurate every curated product no catalog file declares.

        File presence is the sole carrier of curation, so removing a file
        releases its product. Release is deliberately shallow: templates, the
        canonical `template_id`, `visibility`, and deployments are all left
        exactly as they were, which is what makes restoring a dropped file a
        no-op re-adoption rather than a repair job.
        """
        curated = self._session.exec(
            select(ProductORM).where(
                ProductORM.curated == True,  # noqa: E712
                ProductORM.deleted_at == None,  # noqa: E711
            )
        ).all()
        for product in curated:
            if product.slug in declared:
                continue
            logger.info(
                "Releasing product id=%s slug=%s: no catalog file declares it",
                product.id,
                product.slug,
            )
            report.record(
                "product-released", product.slug or "", f"released product id={product.id}"
            )
            product.curated = False
            product.slug = None
            self._session.add(product)
        self._session.flush()
