from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import tomllib
from typing import cast


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    api_base_url: str
    token_env_var: str
    append_to_response: str
    max_connections: int
    requests_per_second: float
    request_timeout_seconds: float
    connect_timeout_seconds: float
    max_retries: int
    retry_base_delay_seconds: float
    retry_backoff_multiplier: float
    source_file: Path
    cache_file: Path
    removals_file: Path
    output_dir: Path

    @property
    def acquisition_file(self) -> Path:
        return self.output_dir / f"{self.cache_file.stem}.acquisition.json"

    @property
    def benchmark_dir(self) -> Path:
        # Keep performance experiments together under the configured output folder.
        return self.output_dir / "benchmarks"

    @property
    def notebook_report_dir(self) -> Path:
        return self.project_root / "data" / "recommendation-report"

    @property
    def notebook_benchmark_dir(self) -> Path:
        return self.notebook_report_dir / "benchmark"


def _section(config: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = config.get(name)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"Config section '{name}' must be a table.")
    return cast(Mapping[str, object], value)


def _text(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config value '{key}' must be non-empty text.")
    return value


def _integer(
    section: Mapping[str, object], key: str, *, minimum: int
) -> int:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(
            f"Config value '{key}' must be an integer of at least {minimum}."
        )
    return value


def _number(
    section: Mapping[str, object],
    key: str,
    *,
    minimum: float,
    exclusive_minimum: bool = False,
) -> float:
    value = section.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < minimum
        or (exclusive_minimum and value == minimum)
    ):
        comparison = (
            f"greater than {minimum}"
            if exclusive_minimum
            else f"at least {minimum}"
        )
        raise ValueError(
            f"Config value '{key}' must be a finite number {comparison}."
        )
    return float(value)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    if config_path is None:
        resolved_config_path = Path(__file__).resolve().parents[2] / "config.toml"
    else:
        resolved_config_path = Path(config_path).resolve()

    try:
        with resolved_config_path.open("rb") as config_file:
            raw_config: object = tomllib.load(config_file)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Configuration file not found: {resolved_config_path}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(
            f"Invalid TOML in {resolved_config_path}: {error}"
        ) from error

    if not isinstance(raw_config, dict) or not all(
        isinstance(key, str) for key in raw_config
    ):
        raise ValueError(f"Configuration must be a TOML table: {resolved_config_path}")

    config = cast(Mapping[str, object], raw_config)
    api = _section(config, "api")
    retry = _section(config, "retry")
    paths = _section(config, "paths")
    project_root = resolved_config_path.parent

    return AppConfig(
        project_root=project_root,
        api_base_url=_text(api, "base_url"),
        token_env_var=_text(api, "token_env_var"),
        append_to_response=_text(api, "append_to_response"),
        max_connections=_integer(api, "max_connections", minimum=1),
        requests_per_second=_number(
            api, "requests_per_second", minimum=0.0, exclusive_minimum=True
        ),
        request_timeout_seconds=_number(
            api, "request_timeout_seconds", minimum=0.0, exclusive_minimum=True
        ),
        connect_timeout_seconds=_number(
            api, "connect_timeout_seconds", minimum=0.0, exclusive_minimum=True
        ),
        max_retries=_integer(retry, "max_retries", minimum=0),
        retry_base_delay_seconds=_number(
            retry, "base_delay_seconds", minimum=0.0
        ),
        retry_backoff_multiplier=_number(
            retry, "backoff_multiplier", minimum=1.0
        ),
        source_file=(project_root / _text(paths, "source_file")).resolve(),
        cache_file=(project_root / _text(paths, "cache_file")).resolve(),
        removals_file=(project_root / _text(paths, "removals_file")).resolve(),
        output_dir=(project_root / _text({"output_dir": "out"} | paths, "output_dir")).resolve(),
    )


CONFIG = load_config()
