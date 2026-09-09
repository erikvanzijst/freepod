"""The command surface: streams, exit codes, colour, and `--quiet` (task 11)."""

from __future__ import annotations

import io
import json

import pytest

from freepod import (
    EXIT_BUILD_FAILED,
    EXIT_ERROR,
    EXIT_NOT_AUTHENTICATED,
    EXIT_OK,
    EXIT_ROLLOUT_FAILED,
    EXIT_USAGE,
    AuthenticationError,
    BuildFailed,
    FreepodError,
    RolloutFailed,
    UsageError,
)
from freepod.cli import main

from test_deploy import Platform, deployment, project_at


@pytest.fixture
def run_deploy(monkeypatch, tmp_path):
    """Drive `main(['deploy'])` against a scripted platform in `tmp_path`."""

    def go(platform, *argv, cwd=None, before=()):
        import httpx

        import freepod.cli as cli_module
        from freepod.api import ApiClient
        from freepod.config import ENVIRONMENTS

        from conftest import Recorder, StubSession
        from test_deploy import Store

        recorder = Recorder(platform)
        transport = httpx.MockTransport(recorder)

        # `deploy` reaches the object store through a client it opens itself,
        # which would be a real network call from a unit test. Intercept the
        # bare `httpx.Client()` construction and leave every explicit one alone.
        store = Store()
        real_client = httpx.Client

        def intercepted(*args, **kwargs):
            if args or kwargs:
                return real_client(*args, **kwargs)
            return real_client(transport=httpx.MockTransport(store))

        monkeypatch.setattr(httpx, "Client", intercepted)

        class Ctx(cli_module.Context):
            def session(self, force_flow=None):
                return StubSession()

            def client(self, session):
                return ApiClient(
                    ENVIRONMENTS[self.env.name],
                    session,
                    client=httpx.Client(transport=transport),
                    backoff_base=0,
                )

        monkeypatch.setattr(cli_module, "Context", Ctx)
        monkeypatch.chdir(cwd or tmp_path)
        # No terminal: nothing may prompt, and colour must be off.
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        return main([*before, "deploy", *argv])

    return go


def ready_platform(**kwargs):
    kwargs.setdefault("create", deployment(status="provisioning", generation=1))
    kwargs.setdefault("reads", [deployment(status="ready", generation=1)])
    return Platform(**kwargs)


# --------------------------------------------------------------------------
# Stream discipline (task 11.2)
# --------------------------------------------------------------------------


def test_a_piped_deploy_carries_only_the_address_on_stdout(run_deploy, tmp_path, capsys):
    """`URL=$(freepod deploy)` must yield a URL, not a buildkit transcript."""
    project_at(tmp_path)

    assert run_deploy(ready_platform()) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == "https://myapp.erik.freepod.eu\n"


def test_the_build_log_goes_to_stderr(run_deploy, tmp_path, capsys):
    """It is the platform narrating progress, not the command's result."""
    project_at(tmp_path)

    run_deploy(ready_platform())

    captured = capsys.readouterr()
    assert "step 1" in captured.err
    assert "step 1" not in captured.out


def test_every_diagnostic_line_is_on_stderr(run_deploy, tmp_path, capsys):
    project_at(tmp_path)

    run_deploy(ready_platform())

    captured = capsys.readouterr()
    for phrase in ("Packed", "Creating a deployment", "Built ", "Deployed. Live at"):
        assert phrase in captured.err, phrase
        assert phrase not in captured.out, phrase


def test_an_error_leaves_stdout_empty(run_deploy, tmp_path, capsys):
    """A failed deploy must not put a half-result into a pipeline."""
    project_at(tmp_path)

    assert run_deploy(Platform(plans=[])) != EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "publishes no plans" in captured.err


# --------------------------------------------------------------------------
# `--quiet` (task 11.1)
# --------------------------------------------------------------------------


def test_quiet_silences_diagnostics_but_not_the_address(run_deploy, tmp_path, capsys):
    project_at(tmp_path)

    assert run_deploy(ready_platform(), before=["--quiet"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == "https://myapp.erik.freepod.eu\n"
    assert captured.err == ""


def test_quiet_still_reports_a_failure(run_deploy, tmp_path, capsys):
    """Silencing progress must not silence the reason a deploy stopped."""
    project_at(tmp_path)

    assert run_deploy(Platform(plans=[]), before=["--quiet"]) != EXIT_OK

    captured = capsys.readouterr()
    assert "publishes no plans" in captured.err
    assert captured.out == ""


def test_quiet_and_verbose_together_are_a_usage_error(capsys):
    assert main(["--quiet", "--verbose", "whoami"]) == EXIT_USAGE
    assert "contradict" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Exit codes (task 11.3)
# --------------------------------------------------------------------------


def test_the_exit_code_table_is_what_the_errors_declare():
    """Each row is carried by the exception, not by a `main` branch that could
    drift from it."""
    assert (EXIT_OK, EXIT_ERROR, EXIT_USAGE) == (0, 1, 2)
    assert (EXIT_NOT_AUTHENTICATED, EXIT_BUILD_FAILED, EXIT_ROLLOUT_FAILED) == (3, 4, 5)
    assert FreepodError("x").exit_code == EXIT_ERROR
    assert UsageError("x").exit_code == EXIT_USAGE
    assert AuthenticationError("x").exit_code == EXIT_NOT_AUTHENTICATED
    assert BuildFailed("x").exit_code == EXIT_BUILD_FAILED
    assert RolloutFailed("x").exit_code == EXIT_ROLLOUT_FAILED


@pytest.mark.parametrize(
    "error,expected",
    [
        (FreepodError("plain"), EXIT_ERROR),
        (UsageError("bad flag"), EXIT_USAGE),
        (AuthenticationError("no token"), EXIT_NOT_AUTHENTICATED),
        (BuildFailed("build died"), EXIT_BUILD_FAILED),
        (RolloutFailed("rollout died"), EXIT_ROLLOUT_FAILED),
    ],
)
def test_each_failure_reaches_its_exit_code_through_main(
    monkeypatch, error, expected, capsys
):
    import freepod.cli as cli_module

    def explode(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(cli_module, "forget_environment", explode)
    assert main(["logout"]) == expected
    assert str(error) in capsys.readouterr().err


def test_an_unexpected_exception_is_reported_as_exit_one(monkeypatch, capsys):
    import freepod.cli as cli_module

    def explode(*_args, **_kwargs):
        raise ZeroDivisionError("something nobody anticipated")

    monkeypatch.setattr(cli_module, "forget_environment", explode)

    assert main(["logout"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "unexpected error" in err
    assert "ZeroDivisionError" in err


def test_an_interrupt_is_not_reported_as_a_crash(monkeypatch, capsys):
    import freepod.cli as cli_module

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "forget_environment", interrupt)

    assert main(["logout"]) == 130
    assert "Interrupted" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Timeouts read as "stopped waiting", not "failed" (task 11.4)
# --------------------------------------------------------------------------


def test_the_timeout_help_names_all_three_operations(capsys):
    main(["--help"])
    out = capsys.readouterr().out
    assert "whichever operation is in progress" in out
    for default in ("300s", "1800s", "600s"):
        assert default in out


def test_a_build_timeout_says_the_build_continues():
    from freepod.build import follow_build

    from conftest import Recorder

    import httpx

    from freepod.api import ApiClient
    from freepod.config import ENVIRONMENTS
    from conftest import StubSession

    def handler(_request):
        return httpx.Response(206, content=b"", headers={"X-Build-Status": "running"})

    api = ApiClient(
        ENVIRONMENTS["prod"],
        StubSession(),
        client=httpx.Client(transport=httpx.MockTransport(Recorder(handler))),
        backoff_base=0,
    )

    with pytest.raises(FreepodError) as raised:
        follow_build(api, 7, "b-1", out=io.BytesIO(), timeout=0, poll_active=0, poll_idle=0)

    message = str(raised.value)
    assert "stopped waiting" in message
    assert "still running" in message
    assert "not canceled" in message


def test_a_rollout_timeout_says_the_rollout_continues(make_api):
    from freepod.deploy import follow_rollout

    api, _, _ = make_api(Platform(reads=[deployment(status="provisioning", generation=4)]))

    with pytest.raises(FreepodError) as raised:
        follow_rollout(api, 7, "d-1", 4, timeout=0, poll=0, echo=lambda _m: None)

    message = str(raised.value)
    assert "stopped waiting" in message
    assert "still rolling out" in message
    assert "not canceled" in message


def test_a_timeout_is_not_a_build_failure(make_api):
    """Exit 4 means the platform reported a failed build. A client that gave up
    waiting has learned nothing about the build's outcome."""
    from freepod.deploy import follow_rollout

    api, _, _ = make_api(Platform(reads=[deployment(status="provisioning", generation=4)]))

    with pytest.raises(FreepodError) as raised:
        follow_rollout(api, 7, "d-1", 4, timeout=0, poll=0, echo=lambda _m: None)

    assert raised.value.exit_code == EXIT_ERROR
    assert not isinstance(raised.value, (BuildFailed, RolloutFailed))


# --------------------------------------------------------------------------
# Colour (task 11.5)
# --------------------------------------------------------------------------


def test_colour_is_off_when_stdout_is_not_a_terminal(monkeypatch, capsys):
    import click

    seen = {}

    @click.command()
    @click.pass_context
    def probe(ctx):
        seen["color"] = ctx.color

    from freepod.cli import cli

    cli.add_command(probe, "probe")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    try:
        main(["probe"])
    finally:
        cli.commands.pop("probe")

    assert seen["color"] is False


def test_colour_is_off_when_no_color_is_set(monkeypatch, capsys):
    import click

    seen = {}

    @click.command()
    @click.pass_context
    def probe(ctx):
        seen["color"] = ctx.color

    from freepod.cli import cli

    cli.add_command(probe, "probe")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    try:
        main(["probe"])
    finally:
        cli.commands.pop("probe")

    assert seen["color"] is False


def test_styled_output_carries_no_escape_codes_when_piped(monkeypatch, capsys):
    """The end the user sees: whatever the context says, no escapes on a pipe."""
    import click

    from freepod.cli import cli

    @click.command()
    def probe():
        click.secho("hello", fg="red")

    cli.add_command(probe, "probe")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    try:
        main(["probe"])
    finally:
        cli.commands.pop("probe")

    assert capsys.readouterr().out == "hello\n"


def test_every_command_appears_in_the_readme_table():
    """The README is the package's PyPI landing page, so a command that is not
    in its table is a command nobody browsing the project can discover."""
    import pathlib

    from freepod.cli import cli

    table = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text()
    listed = {line.split("`")[1] for line in table.splitlines() if line.startswith("| `freepod ")}
    documented = {name.split()[-1] for name in listed}
    assert set(cli.commands) <= documented, (
        f"undocumented commands: {sorted(set(cli.commands) - documented)}"
    )
