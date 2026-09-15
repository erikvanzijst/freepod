"""Configuration from the deployment's vars (product-upgrade-service)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REPO = "erikvanzijst/freepod"

REQUIRED = (
    "INFERENCE_BASE_URL",
    "INFERENCE_MODEL",
    "INFERENCE_API_KEY",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY",
)
SECRETS = ("GITHUB_APP_PRIVATE_KEY", "INFERENCE_API_KEY", "DASHBOARD_PASSWORD")
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def _get(env, name: str) -> str | None:
    value = env.get(name)
    return value if value else None


@dataclass(frozen=True)
class Settings:
    inference_base_url: str | None = None
    inference_model: str | None = None
    inference_api_key: str | None = None
    github_app_id: str | None = None
    github_app_private_key: str | None = None
    dashboard_password: str | None = None
    thinking_level: str = "medium"
    schedule_time: str = "03:00"
    schedule_timezone: str = "Europe/Brussels"
    dry_run: bool = True
    product_timeout_minutes: str = "90"
    notify_email: str | None = None
    notify_from: str = "upgrader@freepod.eu"
    smtp_host: str = "smtp.mailer.svc.cluster.local"
    dashboard_url: str | None = None
    repo_url: str = f"https://github.com/{REPO}.git"

    @classmethod
    def from_env(cls, env=None) -> Settings:
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            inference_base_url=_get(env, "INFERENCE_BASE_URL"),
            inference_model=_get(env, "INFERENCE_MODEL"),
            inference_api_key=_get(env, "INFERENCE_API_KEY"),
            github_app_id=_get(env, "GITHUB_APP_ID"),
            github_app_private_key=_get(env, "GITHUB_APP_PRIVATE_KEY"),
            dashboard_password=_get(env, "DASHBOARD_PASSWORD"),
            thinking_level=_get(env, "THINKING_LEVEL") or defaults.thinking_level,
            schedule_time=_get(env, "SCHEDULE_TIME") or defaults.schedule_time,
            schedule_timezone=_get(env, "SCHEDULE_TIMEZONE") or defaults.schedule_timezone,
            dry_run=env.get("UPGRADE_DRY_RUN") != "0",
            product_timeout_minutes=(
                _get(env, "PRODUCT_TIMEOUT_MINUTES") or defaults.product_timeout_minutes
            ),
            notify_email=_get(env, "NOTIFY_EMAIL"),
            notify_from=_get(env, "NOTIFY_FROM") or defaults.notify_from,
            smtp_host=_get(env, "SMTP_HOST") or defaults.smtp_host,
            dashboard_url=_get(env, "DASHBOARD_URL"),
            repo_url=_get(env, "REPO_URL") or defaults.repo_url,
        )

    @property
    def timeout_seconds(self) -> int:
        return int(self.product_timeout_minutes) * 60

    def problems(self) -> list[str]:
        """What stops a run from starting: missing required vars and invalid values, by name."""
        values = {
            "INFERENCE_BASE_URL": self.inference_base_url,
            "INFERENCE_MODEL": self.inference_model,
            "INFERENCE_API_KEY": self.inference_api_key,
            "GITHUB_APP_ID": self.github_app_id,
            "GITHUB_APP_PRIVATE_KEY": self.github_app_private_key,
        }
        found = [f"{name} is not set" for name in REQUIRED if not values[name]]
        if self.thinking_level not in THINKING_LEVELS:
            found.append(f"THINKING_LEVEL must be one of {', '.join(THINKING_LEVELS)}")
        if not re.fullmatch(r"[1-9][0-9]*", self.product_timeout_minutes):
            found.append("PRODUCT_TIMEOUT_MINUTES must be a positive whole number")
        found.extend(self.schedule_problems())
        return found

    def schedule_problems(self) -> list[str]:
        found = []
        if self.schedule_time != "off" and not re.fullmatch(
            r"([01][0-9]|2[0-3]):[0-5][0-9]", self.schedule_time
        ):
            found.append("SCHEDULE_TIME must be HH:MM or off")
        try:
            ZoneInfo(self.schedule_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            found.append(f"SCHEDULE_TIMEZONE {self.schedule_timezone!r} is not an IANA zone")
        return found

    def secret_values(self) -> dict[str, str]:
        return {
            name: value
            for name, value in (
                ("INFERENCE_API_KEY", self.inference_api_key),
                ("DASHBOARD_PASSWORD", self.dashboard_password),
            )
            if value
        }
