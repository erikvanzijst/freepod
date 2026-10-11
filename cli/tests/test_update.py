"""The daily update notice: which repository it asks, and how rarely."""

from __future__ import annotations

import httpx
import pytest
from click.testing import CliRunner

from freepod import __version__, cli as cli_module, update
from freepod.update import detect_install

DAY = 24 * 60 * 60

FORMULA = """class Freepod < Formula
  url "https://files.pythonhosted.org/packages/69/e4/aa/freepod-{version}.tar.gz"
  resource "anyio" do
    url "https://files.pythonhosted.org/packages/a9/d2/anyio-4.15.1.tar.gz"
  end
end
"""


def bumped(version: str) -> str:
    major, *rest = version.split(".")
    return ".".join([str(int(major) + 1), *rest])


class Repositories:
    """PyPI and the tap, each serving its own latest version."""

    def __init__(self, pypi: str, brew: str):
        self.pypi, self.brew = pypi, brew
        self.urls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if str(request.url) == update.PYPI_URL:
            return httpx.Response(200, json={"info": {"version": self.pypi}})
        if str(request.url) == update.BREW_FORMULA_URL:
            return httpx.Response(200, text=FORMULA.format(version=self.brew))
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def pip_install(monkeypatch, tmp_path):
    monkeypatch.setattr(update.sys, "prefix", str(tmp_path / "venv"))


@pytest.fixture
def brew_install(monkeypatch):
    monkeypatch.setattr(
        update.sys, "prefix", "/opt/homebrew/Cellar/freepod/0.1.0/libexec"
    )


def test_installers_are_told_apart(tmp_path):
    assert detect_install(tmp_path / "Cellar" / "freepod" / "1.0" / "libexec").command == (
        "brew upgrade freepod"
    )
    mise = tmp_path / "mise" / "installs" / "pipx-freepod" / "1.0"
    mise.mkdir(parents=True)
    (mise / "uv-receipt.toml").write_text("")
    assert detect_install(mise).command == "mise upgrade pipx:freepod"
    uv = tmp_path / "uv" / "tools" / "freepod"
    uv.mkdir(parents=True)
    (uv / "uv-receipt.toml").write_text("")
    assert detect_install(uv).command == "uv tool upgrade freepod"
    pipx = tmp_path / "pipx" / "venvs" / "freepod"
    pipx.mkdir(parents=True)
    (pipx / "pipx_metadata.json").write_text("{}")
    assert detect_install(pipx).command == "pipx upgrade freepod"
    assert detect_install(tmp_path / "venv").command == "pip install --upgrade freepod"


def test_a_newer_pypi_release_is_reported_with_the_upgrade_command(pip_install):
    repos = Repositories(pypi=bumped(__version__), brew=__version__)
    notice = update.check(now=DAY, client=repos.client())
    assert notice == (
        f"freepod {bumped(__version__)} available (you have {__version__}): "
        "pip install --upgrade freepod"
    )
    assert repos.urls == [update.PYPI_URL]


def test_brew_asks_the_tap_not_pypi(brew_install):
    """The tap lags PyPI; a brew user is told only what `brew upgrade` gets."""
    repos = Repositories(pypi=bumped(__version__), brew=__version__)
    assert update.check(now=DAY, client=repos.client()) is None
    assert repos.urls == [update.BREW_FORMULA_URL]

    repos.brew = bumped(__version__)
    notice = update.check(now=2 * DAY, client=repos.client())
    assert notice and notice.endswith(": brew upgrade freepod")


def test_the_network_is_asked_at_most_once_a_day(pip_install):
    repos = Repositories(pypi=bumped(__version__), brew=__version__)
    assert update.check(now=DAY, client=repos.client())
    assert update.check(now=DAY + DAY - 1, client=repos.client()) is None
    assert len(repos.urls) == 1
    assert update.check(now=2 * DAY, client=repos.client())
    assert len(repos.urls) == 2


def test_a_failed_check_waits_a_day_too(pip_install):
    """Offline, the timeout is paid once a day rather than on every command."""
    calls = []

    def down(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)

    client = httpx.Client(transport=httpx.MockTransport(down))
    assert update.check(now=DAY, client=client) is None
    assert update.check(now=DAY + 60, client=client) is None
    assert len(calls) == 1


def test_current_or_older_is_silent(pip_install):
    assert update.check(now=DAY, client=Repositories(__version__, __version__).client()) is None
    assert update.check(now=2 * DAY, client=Repositories("0.0.1", "0.0.1").client()) is None


def test_versions_compare_numerically():
    assert update.parse_version("0.10.0") > update.parse_version("0.9.9")
    assert update.parse_version("1.0.0rc1") is None


def run(monkeypatch, *args, notice="freepod 9.9.9 available (you have 0.1.0): uv tool upgrade freepod"):
    calls = []
    monkeypatch.setattr(update, "check", lambda: calls.append(1) or notice)
    monkeypatch.setattr(cli_module, "_at_terminal", lambda: True)
    printed = []
    monkeypatch.setattr(cli_module, "log", printed.append)
    result = CliRunner().invoke(cli_module.cli, list(args))
    result.printed = printed
    return result, calls


def test_the_cli_prints_the_notice_after_a_successful_command(monkeypatch):
    result, calls = run(monkeypatch, "skill", "show")
    assert result.exit_code == 0, result.output
    assert calls == [1]
    assert result.printed[-1].startswith("freepod 9.9.9 available")


def test_quiet_and_opt_out_skip_the_check(monkeypatch):
    _, calls = run(monkeypatch, "--quiet", "skill", "show")
    assert calls == []
    monkeypatch.setenv(update.OPT_OUT_VAR, "1")
    _, calls = run(monkeypatch, "skill", "show")
    assert calls == []
