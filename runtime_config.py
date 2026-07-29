from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from picable import PiClientOptions

EXAMPLE_PROVIDER_ENV = "PI_RPC_EXAMPLE_PROVIDER"
EXAMPLE_MODEL_ENV = "PI_RPC_EXAMPLE_MODEL"
EXAMPLE_EXTRA_ARGS_ENV = "PI_RPC_EXAMPLE_EXTRA_ARGS"
EXAMPLE_SESSION_DIR_ENV = "PI_RPC_EXAMPLE_SESSION_DIR"

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class ExampleRuntimeConfig:
    provider: str | None = None
    model: str | None = None
    extra_args: tuple[str, ...] = ()
    session_dir: str | None = None


def _optional_env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_example_extra_args(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None or not raw_value.strip():
        return ()
    return tuple(shlex.split(raw_value))


def get_example_runtime_config(env: Mapping[str, str] | None = None) -> ExampleRuntimeConfig:
    source = os.environ if env is None else env
    return ExampleRuntimeConfig(
        provider=_optional_env_value(source, EXAMPLE_PROVIDER_ENV),
        model=_optional_env_value(source, EXAMPLE_MODEL_ENV),
        extra_args=parse_example_extra_args(source.get(EXAMPLE_EXTRA_ARGS_ENV)),
        session_dir=_optional_env_value(source, EXAMPLE_SESSION_DIR_ENV),
    )


def _find_pi_executable() -> str:
    """Find pi executable in PATH, handling Windows .cmd extension."""
    return shutil.which("pi") or shutil.which("pi.cmd") or "pi"


def build_example_client_options(
    *,
    provider: str | None = None,
    model: str | None = None,
    no_session: bool = False,
    session_dir: str | None = None,
    cwd: str | None = None,
    extra_args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    startup_timeout: float = 10.0,
    command_timeout: float = 30.0,
    idle_timeout: float | None = None,
    executable: str = "C:/Users/MYue/.workbuddy/binaries/node/versions/22.22.2/pi.cmd",
    process_factory: Callable[..., Any] | None = None,
    auto_close_subscriptions: bool = True,
) -> PiClientOptions:
    runtime = get_example_runtime_config(env)
    options = PiClientOptions(
        executable=executable,
        provider=runtime.provider if runtime.provider is not None else provider,
        model=runtime.model if runtime.model is not None else model,
        no_session=no_session,
        session_dir=runtime.session_dir if runtime.session_dir is not None else session_dir,
        cwd=cwd,
        env=env,
        startup_timeout=startup_timeout,
        command_timeout=command_timeout,
        idle_timeout=idle_timeout,
        extra_args=tuple(extra_args) + runtime.extra_args,
        process_factory=process_factory,
        auto_close_subscriptions=auto_close_subscriptions,
    )
    # Force executable to system-resolved path (overrides module cache staleness)
    return replace(options, executable=_find_pi_executable())
