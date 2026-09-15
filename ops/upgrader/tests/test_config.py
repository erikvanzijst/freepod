import re

import pytest

from upgrader.config import REQUIRED, SECRETS, Settings

FULL = {
    "INFERENCE_BASE_URL": "https://ai.example/v1",
    "INFERENCE_MODEL": "qwen",
    "INFERENCE_API_KEY": "k",
    "GITHUB_APP_ID": "123",
    "GITHUB_APP_PRIVATE_KEY": "cGVt",
}

RESERVED = re.compile(r"^(PORT|BUCKET_NAME|DATABASE_URL|AWS_.*|S3_.*|PG.*|CAELUS_.*|RAILPACK_.*)$")


def test_defaults():
    s = Settings.from_env(FULL)
    assert s.problems() == []
    assert s.dry_run is True
    assert (s.schedule_time, s.schedule_timezone) == ("03:00", "Europe/Brussels")
    assert s.thinking_level == "medium"
    assert s.timeout_seconds == 90 * 60
    assert s.notify_email is None
    assert s.notify_from == "upgrader@freepod.eu"
    assert s.smtp_host == "smtp.mailer.svc.cluster.local"
    assert s.repo_url == "https://github.com/erikvanzijst/freepod.git"


@pytest.mark.parametrize(
    "value, dry", [(None, True), ("1", True), ("false", True), ("", True), ("00", True), ("0", False)]
)
def test_only_zero_means_real(value, dry):
    env = dict(FULL) if value is None else {**FULL, "UPGRADE_DRY_RUN": value}
    assert Settings.from_env(env).dry_run is dry


@pytest.mark.parametrize("name", REQUIRED)
def test_missing_required_var_is_named(name):
    env = {k: v for k, v in FULL.items() if k != name}
    assert Settings.from_env(env).problems() == [f"{name} is not set"]


def test_empty_counts_as_unset():
    problems = Settings.from_env({**FULL, "INFERENCE_BASE_URL": ""}).problems()
    assert problems == ["INFERENCE_BASE_URL is not set"]


def test_invalid_values_are_named():
    env = {
        **FULL,
        "THINKING_LEVEL": "extreme",
        "PRODUCT_TIMEOUT_MINUTES": "soon",
        "SCHEDULE_TIME": "3am",
        "SCHEDULE_TIMEZONE": "Mars/Olympus",
    }
    problems = " ".join(Settings.from_env(env).problems())
    for name in ("THINKING_LEVEL", "PRODUCT_TIMEOUT_MINUTES", "SCHEDULE_TIME", "SCHEDULE_TIMEZONE"):
        assert name in problems


def test_schedule_off_is_valid():
    assert Settings.from_env({**FULL, "SCHEDULE_TIME": "off"}).problems() == []


def test_no_reserved_name_is_required_or_secret():
    assert not [n for n in (*REQUIRED, *SECRETS) if RESERVED.match(n)]
