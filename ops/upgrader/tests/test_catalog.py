import shutil
import subprocess
from pathlib import Path

from upgrader.catalog import Choices, eligible, fetch

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
    assert eligible(REPO_ROOT) == [
        "bookstack",
        "immich",
        "lemmy",
        "mattermost",
        "nextcloud",
        "photoprism",
        "vaultwarden",
    ]


def test_fetch_reads_master_from_a_fresh_clone(tmp_path):
    git = shutil.which("git", path="/usr/local/bin:/usr/bin")
    work = tmp_path / "work"
    write(work, "immich", upstream("    type: github-release\n    repo: immich-app/immich"))
    write(work, "custom", upstream("    type: github-release\n    repo: OWNER/REPO"))
    run = lambda *a, cwd=work: subprocess.run([git, *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "master")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "catalog")
    run("clone", "-q", "--bare", str(work), str(tmp_path / "origin.git"), cwd=tmp_path)
    assert fetch(f"file://{tmp_path / 'origin.git'}", git=git, workdir=tmp_path) == ["immich"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["origin.git", "work"]


def test_choices_are_reread_after_their_ttl():
    reads, clock = [], [0.0]

    def read():
        reads.append(clock[0])
        return ["immich"] if len(reads) == 1 else ["immich", "vaultwarden"]

    choices = Choices(read, clock=lambda: clock[0])
    assert choices() == ["immich"]
    clock[0] += Choices.TTL - 1
    assert choices() == ["immich"]
    assert len(reads) == 1
    clock[0] += 1
    assert choices() == ["immich", "vaultwarden"]


def test_choices_keep_the_last_list_when_a_read_fails():
    clock, down = [0.0], [False]

    def read():
        if down[0]:
            raise RuntimeError("github is unreachable")
        return ["immich", "nextcloud"]

    choices = Choices(read, clock=lambda: clock[0])
    assert choices() == ["immich", "nextcloud"]
    down[0] = True
    clock[0] += Choices.TTL
    assert choices() == ["immich", "nextcloud"]
