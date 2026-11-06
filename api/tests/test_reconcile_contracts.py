from app.services import reconcile_constants as c
from app.services.reconcile_naming import (
    MAX_NAME_LEN,
    MAX_NAMESPACE_LEN,
    NAME_BASE_MAX_LEN,
    generate_deployment_name,
    generate_deployment_namespace,
    is_valid_dns_label,
    slugify_token,
)


def test_deployment_statuses_are_complete_and_unique() -> None:
    expected = {
        "pending",
        "provisioning",
        "ready",
        "deleting",
        "deleted",
        "error",
    }
    assert set(c.DEPLOYMENT_STATUSES) == expected
    assert len(c.DEPLOYMENT_STATUSES) == len(set(c.DEPLOYMENT_STATUSES))


def test_job_statuses_and_reasons_are_complete_and_unique() -> None:
    assert set(c.JOB_STATUSES) == {"queued", "running", "done", "failed"}
    assert set(c.JOB_REASONS) == {"create", "update", "delete", "power"}
    assert len(c.JOB_STATUSES) == len(set(c.JOB_STATUSES))
    assert len(c.JOB_REASONS) == len(set(c.JOB_REASONS))


# --- generate_deployment_name tests ---


def test_generate_name_format_and_length() -> None:
    name = generate_deployment_name("Hello Static", suffix="abc123")
    assert name == "hello-static-abc123"
    assert len(name) <= MAX_NAME_LEN
    assert is_valid_dns_label(name)


def test_generate_name_truncates_long_product() -> None:
    long_product = "p" * 200
    name = generate_deployment_name(long_product, suffix="zzzzzz")
    base, suffix = name.rsplit("-", 1)
    assert suffix == "zzzzzz"
    assert len(base) <= NAME_BASE_MAX_LEN
    assert len(name) <= MAX_NAME_LEN
    assert is_valid_dns_label(name)


def test_generate_name_strips_trailing_hyphen_after_truncation() -> None:
    # Product name that slugifies to exactly 20 chars ending in hyphen after truncation
    product = "a" * 20 + "-bbb"
    name = generate_deployment_name(product, suffix="abc123")
    base, _ = name.rsplit("-", 1)
    assert not base.endswith("-")
    assert is_valid_dns_label(name)


def test_generate_name_special_characters() -> None:
    name = generate_deployment_name("My App (v2.0)!!!", suffix="abc123")
    assert name == "my-app-v2-0-abc123"
    assert is_valid_dns_label(name)


def test_generate_name_fallback_for_non_alnum() -> None:
    name = generate_deployment_name("!!!", suffix="000000")
    assert name == "dep-000000"
    assert is_valid_dns_label(name)


def test_generate_name_random_suffix_when_none() -> None:
    name = generate_deployment_name("hello")
    assert name.startswith("hello-")
    assert len(name) == len("hello-") + 6
    assert is_valid_dns_label(name)


# --- generate_deployment_namespace tests ---


def test_generate_namespace_format_and_length() -> None:
    ns = generate_deployment_namespace(
        "Hello Static", "alice.smith@example.com", suffix="abc123def"
    )
    assert ns == "hello-static-alice-smit-abc123def"
    assert len(ns) <= MAX_NAMESPACE_LEN
    assert is_valid_dns_label(ns)


def test_generate_namespace_omits_the_email_domain() -> None:
    """The namespace is typed as an SSH username; it does not carry an address."""
    ns = generate_deployment_namespace(
        "Hello Static", "alice@corp.example.com", suffix="abc123def"
    )
    assert "corp" not in ns
    assert "example" not in ns
    assert "com" not in ns.rsplit("-", 1)[0]


def test_generate_namespace_truncates_long_product_and_local_part() -> None:
    ns = generate_deployment_namespace(
        "A " + ("Very " * 20) + "Long Product",
        "user." + ("x" * 200) + "@example.com",
        suffix="zzzzzzzzz",
    )
    # Segments carry hyphens of their own, so the bound is asserted on the whole
    # rather than by splitting it back apart.
    assert ns == "a-very-very-very-ver-user-xxxxx-zzzzzzzzz"
    assert len(ns) == MAX_NAMESPACE_LEN
    assert is_valid_dns_label(ns)


def test_generate_namespace_special_email_characters() -> None:
    ns = generate_deployment_namespace(
        "My App (v2.0)!!!",
        "Alice.Smith+dev@example.com",
        suffix="abc123def",
    )
    assert ns == "my-app-v2-0-alice-smit-abc123def"
    assert is_valid_dns_label(ns)


def test_generate_namespace_fallback_for_non_alnum() -> None:
    """Neither segment may come out empty, or the label doubles a hyphen."""
    ns = generate_deployment_namespace(
        "@@@", "@@@@example.com", suffix="000000000"
    )
    assert ns == "dep-dep-000000000"
    assert is_valid_dns_label(ns)


def test_generate_namespace_random_suffix_when_none() -> None:
    ns = generate_deployment_namespace(
        "Hello Static", "test@example.com"
    )
    parts = ns.rsplit("-", 1)
    assert len(parts[1]) == 9
    assert is_valid_dns_label(ns)


# --- slugify_token tests ---


def test_slugify_token() -> None:
    assert slugify_token("A__B.C") == "a-b-c"
    assert slugify_token("hello") == "hello"
    assert slugify_token("") == ""
