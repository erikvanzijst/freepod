from pathlib import Path

from upgrader.catalog import eligible

REPO_ROOT = Path(__file__).resolve().parents[3]


def write(clone, slug, body):
    path = clone / "products" / "catalog" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def upstream(source):
    return f"upstream:\n  source:\n{source}\n  match: ^(?P<version>.+)$\n  version_path: x\ntemplate: {{}}\n"


def test_placeholder_and_missing_upstream_are_excluded(tmp_path):
    write(tmp_path, "vaultwarden", upstream("    type: docker-tag\n    image: docker.io/vaultwarden/server"))
    write(tmp_path, "custom", upstream("    type: github-release\n    repo: OWNER/REPO"))
    write(tmp_path, "nextcloud", upstream("    type: docker-tag\n    image: docker.io/library/nextcloud"))
    write(tmp_path, "immich", upstream("    type: github-release\n    repo: immich-app/immich"))
    write(tmp_path, "static", "template: {}\n")
    (tmp_path / "products" / "catalog" / "catalog.schema.json").write_text("{}")
    assert eligible(tmp_path) == ["immich", "nextcloud", "vaultwarden"]


def test_the_repositorys_own_catalog():
    assert eligible(REPO_ROOT) == ["immich", "nextcloud", "vaultwarden"]
