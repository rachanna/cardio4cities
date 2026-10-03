"""Configuration loading and start-up validation (LLD-4 §5).

`config/<APP_ENV>.yaml` selects adapters and parameters; secrets come only from
environment variables named by `*_env` keys. `load_settings` gathers every
problem it finds and raises one `ConfigError` naming them all, so the
application refuses to start with a clear message (R-82, AT-36).

Checks that need a live provider or the database are pure functions here
(`check_embedding_dimension`, `check_reference_slots`, `check_indicator_codes`);
start-up calls them once those adapters and tables exist (BD-02).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from app.ports.llm import Effort

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DAY1_PLACEHOLDER = "<confirm day 1>"
MIN_ACCESS_CODE_LENGTH = 12
EXPECTED_SLOT_IDS = frozenset(f"S{n:02d}" for n in range(1, 17))

# local-quality: local stores with the deployed model bindings (BD-05)
AppEnv = Literal["local", "local-quality", "deployed"]
APP_ENVS: tuple[str, ...] = ("local", "local-quality", "deployed")


class ConfigError(Exception):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"Configuration refused ({len(problems)} problem(s)):\n{lines}")


# --- Config file shape (LLD-4 §5.1) ---------------------------------------


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AppSection(_Section):
    public_base_url: str
    user_agent: str


class AccessSection(_Section):
    access_code_env: str
    admin_code_env: str
    session_secret_env: str


class _Binding(_Section):
    """A model with the sampling or depth setting it accepts (BD-05).

    Claude Haiku 4.5 takes `temperature` and errors on `effort`; Claude Sonnet and
    Opus 5.5 reject `temperature`; OpenAI reasoning models take `effort`
    (`reasoning.effort`). So the setting belongs to the binding, not the role.
    """

    provider: str
    model: str
    effort: Effort | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if self.effort is not None and self.temperature is not None:
            raise ValueError("set effort or temperature, not both")
        return self


class ModelRef(_Binding):
    family: str | None = None


class RoleConfig(_Binding):
    family: str
    escalate_to: ModelRef | None = None
    fallback: ModelRef | None = None

    def model_refs(self) -> Iterator[ModelRef | RoleConfig]:
        yield self
        if self.escalate_to is not None:
            yield self.escalate_to
        if self.fallback is not None:
            yield self.fallback


class Roles(_Section):
    planner: RoleConfig
    extractor: RoleConfig
    checker: RoleConfig
    classifier: RoleConfig
    answerer: RoleConfig
    reporter: RoleConfig

    def items(self) -> Iterator[tuple[str, RoleConfig]]:
        for name in type(self).model_fields:
            yield name, getattr(self, name)


class ProviderConfig(_Section):
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None  # BD-05: e.g. OLLAMA_BASE_URL from .env


class LLMSection(_Section):
    roles: Roles
    providers: dict[str, ProviderConfig]
    concurrency: int
    allow_same_family_checker: bool = False  # BD-02


class EmbeddingsSection(_Section):
    provider: str
    model: str
    dimension: int
    key: str
    concurrency: int  # embedding calls in flight at once, across slots (LLD-2 §12)


class SearchSection(_Section):
    provider: str
    mode: Literal["links_only"]  # search is links only; never page content
    api_key_env: str | None = None
    base_url: str | None = None  # BD-02, for searxng
    rate_per_s: float


class RelationalSection(_Section):
    dsn_env: str


class VectorSection(_Section):
    provider: str
    url_env: str
    api_key_env: str | None = None


class GraphSection(_Section):
    provider: str
    uri_env: str
    user_env: str
    password_env: str


class SnapshotsSection(_Section):
    provider: str
    max_bytes: int


class RendererSection(_Section):
    provider: str


class TracingSection(_Section):
    providers: list[str]
    langsmith_api_key_env: str | None = None


class BudgetSection(_Section):
    wall_clock_s: int
    searches: int
    fetches: int
    tokens: int
    cost_micro_usd: int
    wind_down_at: float


class LimitsSection(_Section):
    runs_per_day: int
    ask_per_min: int
    resolve_per_min: int


class FetchSection(_Section):
    concurrency: int
    min_interval_s: float
    max_bytes: int
    connect_timeout_s: float
    read_timeout_s: float
    allowed_ports: list[int]  # LLD-2 §9.1 step 2 [tunable] (BD-07)
    robots_timeout_s: float  # LLD-2 §9.1 step 4: 15 s, raised from 5 after spike S-5 (BD-07)
    crawl_delay_cap_s: float  # LLD-2 §9.3: a longer crawl-delay is rate_limited (BD-20)


class VerifySection(_Section):
    max_claims_per_slot: int
    label_margin_chars: int  # context around each label passage the checker sees (BD-10)


class SelectSection(_Section):
    max_new_urls_per_slot_round: int
    # sources another slot already fetched this run, read again for this slot (BD-14)
    max_reused_per_slot_round: int
    other_place_min_population: int  # places that rank a candidate later (BD-15)


class ReplanSection(_Section):
    max_rounds: int
    max_rounds_wider_geo: int
    # slots re-planned first when searches run short; the rest follow in catalogue order
    priority: list[Annotated[str, Field(pattern=r"^S(0[1-9]|1[0-6])$")]] = []  # BD-15


class PlanSection(_Section):
    queries_per_slot: int = Field(ge=1, le=3)  # every round, re-plans included (BD-15)


class ExtractSection(_Section):
    window_tokens: int
    overlap_tokens: int


class QuoteSection(_Section):
    min_words: int  # LLD-2 §4.1 [tunable] (BD-06)
    max_words: int
    min_words_unique: int  # shorter quotes only when unique in the source (BD-08)


class ChunkSection(_Section):
    prose_tokens: int  # LLD-1 §5.3 [tunable] (BD-07)
    overlap_tokens: int
    table_max_tokens: int


class ConsistencySection(_Section):
    agree_pp: float
    agree_rel: float


class EntitySection(_Section):
    merge_threshold: float
    candidate_threshold: float


class BadgeSection(_Section):
    stale_years: int
    stale_years_people: int
    small_sample: int


class ConfidenceSection(_Section):
    recent_years: int


class AnalyticsSection(_Section):
    enabled: bool


class GeographySection(_Section):
    nearby_km: float  # figures from places this close may answer for the city (BD-10)


class EvalSection(_Section):
    checker_agreement_min: float  # LLD-3 §9 pass bar for the golden set [tunable]


class StructuredProvider(_Section):
    base_url: str  # official API root (Wave 0, BD-13)


class StructuredSection(_Section):
    providers: dict[str, StructuredProvider]


class StreamSection(_Section):
    poll_interval_s: float  # LLD-4 §4: live following polls run_event [tunable]
    heartbeat_s: float  # LLD-4 §4: comment line that keeps proxies from closing


class Config(_Section):
    app: AppSection
    access: AccessSection
    llm: LLMSection
    embeddings: EmbeddingsSection
    search: SearchSection
    relational: RelationalSection
    vector: VectorSection
    graph: GraphSection
    snapshots: SnapshotsSection
    renderer: RendererSection
    tracing: TracingSection
    budget: BudgetSection
    limits: LimitsSection
    fetch: FetchSection
    verify: VerifySection
    select: SelectSection
    replan: ReplanSection
    plan: PlanSection
    extract: ExtractSection
    quote: QuoteSection
    chunk: ChunkSection
    consistency: ConsistencySection
    entity: EntitySection
    badge: BadgeSection
    confidence: ConfidenceSection
    analytics: AnalyticsSection
    stream: StreamSection
    structured: StructuredSection
    geography: GeographySection
    eval: EvalSection


# --- Loaded settings -------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    env: AppEnv
    config: Config
    _secrets: Mapping[str, SecretStr] = field(repr=False)

    def secret(self, env_name: str) -> str:
        """Value of a secret the config refers to; only referenced names are held."""
        return self._secrets[env_name].get_secret_value()

    @property
    def same_family_checker(self) -> bool:
        """True when a same-family checker was explicitly allowed; shown on verdicts and /health."""
        roles = self.config.llm.roles
        return roles.checker.family == roles.extractor.family


def load_settings(env: Mapping[str, str] | None = None, config_dir: Path = CONFIG_DIR) -> Settings:
    """Load `config/<APP_ENV>.yaml`, resolve secrets from `env`, validate. Raises ConfigError."""
    env = os.environ if env is None else env
    app_env = env.get("APP_ENV", "local") or "local"
    if app_env not in APP_ENVS:
        raise ConfigError([f"APP_ENV must be one of {', '.join(APP_ENVS)}, not {app_env!r}"])

    path = config_dir / f"{app_env}.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"config file not found: {path}"]) from None
    except yaml.YAMLError as exc:
        raise ConfigError([f"{path.name} is not valid YAML: {exc}"]) from None

    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            [f"{path.name}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        ) from None

    required = required_secrets(config)
    problems = [
        *check_checker_independence(config),
        *check_providers_declared(config),
        *check_adapter_settings(config),
        *[
            f"environment variable {name} is not set (needed by {needed_by})"
            for name, needed_by in required.items()
            if not env.get(name, "").strip()
        ],
        *check_access_codes(config, env),
    ]
    if app_env == "deployed":
        problems += check_deployed_placeholders(config, raw)
    if problems:
        raise ConfigError(problems)

    secrets = {name: SecretStr(env[name]) for name in required}
    return Settings(env=cast(AppEnv, app_env), config=config, _secrets=secrets)


# --- Checks (pure) ---------------------------------------------------------


def check_checker_independence(config: Config) -> list[str]:
    llm = config.llm
    checker, extractor = llm.roles.checker, llm.roles.extractor
    if checker.family == extractor.family and not llm.allow_same_family_checker:
        return [
            f"checker independence: llm.roles.checker.family ({checker.family!r}) is the same as "
            f"llm.roles.extractor.family; the checker must come from a different model family "
            f"(R-82). Choose another checker, or set llm.allow_same_family_checker: true to "
            f"accept a same-family checker that is labelled on every verdict"
        ]
    return []


def check_providers_declared(config: Config) -> list[str]:
    providers = config.llm.providers
    return [
        f"llm.roles.{name}: provider {ref.provider!r} is not declared under llm.providers"
        for name, role in config.llm.roles.items()
        for ref in role.model_refs()
        if ref.provider not in providers
    ]


def check_adapter_settings(config: Config) -> list[str]:
    problems = []
    search = config.search
    if search.provider in ("brave", "tavily") and not search.api_key_env:
        problems.append(f"search.api_key_env is required for provider {search.provider!r}")
    if search.provider == "searxng" and not search.base_url:
        problems.append("search.base_url is required for provider 'searxng'")
    if "langsmith" in config.tracing.providers and not config.tracing.langsmith_api_key_env:
        problems.append("tracing.langsmith_api_key_env is required when langsmith is enabled")
    return problems


def required_secrets(config: Config) -> dict[str, str]:
    """Environment variables the enabled adapters need, mapped to what needs them."""
    needed: dict[str, str] = {}

    def need(name: str | None, needed_by: str) -> None:
        if name:
            needed.setdefault(name, needed_by)

    access = config.access
    need(access.access_code_env, "access.access_code_env")
    need(access.admin_code_env, "access.admin_code_env")
    need(access.session_secret_env, "access.session_secret_env")

    providers = config.llm.providers
    used = {ref.provider for _, role in config.llm.roles.items() for ref in role.model_refs()}
    used.add(config.embeddings.provider)
    for name in sorted(used & providers.keys()):
        need(providers[name].api_key_env, f"llm.providers.{name}")
        need(providers[name].base_url_env, f"llm.providers.{name}")

    need(config.search.api_key_env, "search.api_key_env")
    need(config.relational.dsn_env, "relational.dsn_env")
    need(config.vector.url_env, "vector.url_env")
    need(config.vector.api_key_env, "vector.api_key_env")
    need(config.graph.uri_env, "graph.uri_env")
    need(config.graph.user_env, "graph.user_env")
    need(config.graph.password_env, "graph.password_env")
    if "langsmith" in config.tracing.providers:
        need(config.tracing.langsmith_api_key_env, "tracing.langsmith_api_key_env")
    return needed


def check_access_codes(config: Config, env: Mapping[str, str]) -> list[str]:
    access_name, admin_name = config.access.access_code_env, config.access.admin_code_env
    access, admin = env.get(access_name, "").strip(), env.get(admin_name, "").strip()
    problems = []
    if access and len(access) < MIN_ACCESS_CODE_LENGTH:
        problems.append(f"{access_name} must be at least {MIN_ACCESS_CODE_LENGTH} characters")
    if access and admin and access == admin:
        problems.append(f"{admin_name} must differ from {access_name}")
    return problems


def check_deployed_placeholders(config: Config, raw: Any) -> list[str]:
    problems = [
        f"{path}: placeholder {DAY1_PLACEHOLDER!r} is not allowed in deployed"
        for path, value in _walk(raw)
        if value == DAY1_PLACEHOLDER
    ]
    problems += [
        f"budget.{name}: 0 means 'not yet set' and is not allowed in deployed"
        for name, value in config.budget.model_dump().items()
        if value == 0
    ]
    if config.embeddings.dimension == 0:
        problems.append(
            "embeddings.dimension: 0 means 'not yet set' and is not allowed in deployed"
        )
    return problems


def check_embedding_dimension(
    configured: int, reported: int, collection: str, existing_collection_size: int | None
) -> list[str]:
    """Refuse a model whose dimension differs from config, or a store that would mix models."""
    problems = []
    if reported != configured:
        problems.append(f"embeddings.dimension is {configured} but the provider reports {reported}")
    if existing_collection_size is not None and existing_collection_size != configured:
        problems.append(
            f"Qdrant collection {collection!r} has vector size {existing_collection_size}, "
            f"not {configured}; it would mix embedding models"
        )
    return problems


def check_reference_slots(slot_ids: Iterable[str]) -> list[str]:
    found = set(slot_ids)
    if found == EXPECTED_SLOT_IDS:
        return []
    if not found:
        return ["ref_slot is empty: run `poe reference` against DATABASE_URL"]
    missing = sorted(EXPECTED_SLOT_IDS - found)
    extra = sorted(found - EXPECTED_SLOT_IDS)
    return [f"ref_slot must hold exactly S01-S16 (missing: {missing}, unexpected: {extra})"]


_PLACEHOLDER_CODE = re.compile(r"^\s*<.*>\s*$")


def check_indicator_codes(codes: Mapping[str, str]) -> list[str]:
    """`codes` maps a label such as 'who_gho.HTN_PREV' to its indicator code."""
    return [
        f"ref_source {label}: indicator code {code!r} is a placeholder"
        for label, code in codes.items()
        if not code.strip() or _PLACEHOLDER_CODE.match(code)
    ]


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")
    else:
        yield path, node
