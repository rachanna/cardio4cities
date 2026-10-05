"""Composition root: builds adapters from config and wires them into services.

Each port is filled from `ADAPTERS`, which maps a provider name to the import
path of its factory. The module is imported only when that provider is
configured, so an unconfigured vendor SDK is never loaded. A factory takes the
`Settings` and returns the adapter.

The registry grows as adapter tasks land. Until then a configured provider
without an adapter leaves its port empty and is listed in `Container.missing`.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.ports.checkpoint import CheckpointPort
from app.ports.embeddings import EmbeddingsPort
from app.ports.fetch import FetchPort
from app.ports.graph import GraphPort
from app.ports.health import HealthProbe
from app.ports.llm import LLMPort
from app.ports.parse import ParserPort
from app.ports.renderer import RendererPort
from app.ports.repos import RelationalPort
from app.ports.robots import RobotsParser
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.structured import StructuredDataPort
from app.ports.tracing import TracingPort
from app.ports.vector import VectorPort
from app.settings import Settings
from app.workflow.state import CHECKPOINT_TYPES

# port -> provider -> "module:factory"
AdapterRegistry = Mapping[str, Mapping[str, str]]
ADAPTERS: AdapterRegistry = {
    "relational": {"postgres": "app.adapters.postgres.relational:make"},
    # workflow checkpoints in schema lg (D2-5, BD-14); the factory takes the state types
    "checkpointer": {"postgres": "app.adapters.postgres.checkpointer:make"},
    # health probes by store provider (LLD-4 §7); full adapters arrive in D2-2 and D2-4
    "probe:vector": {"qdrant": "app.adapters.vector.qdrant_probe:make"},
    "probe:graph": {"graphiti_neo4j": "app.adapters.graph.neo4j_probe:make"},
    # provider health probes (D3-5, BD-42), cached by the health service
    "probe:llm": {
        "anthropic": "app.adapters.llm.anthropic:make_probe",
        "openai": "app.adapters.llm.openai:make_probe",
    },
    "probe:embeddings": {
        "openai": "app.adapters.embeddings.openai:make_probe",
        "sentence_transformers": "app.adapters.embeddings.sentence_transformers:make_probe",
    },
    "probe:search": {
        "searxng": "app.adapters.search.searxng:make_probe",
        "brave": "app.adapters.search.brave:make_probe",
    },
    # collection (D2-2)
    "fetch": {"httpx_pinned": "app.adapters.fetch.httpx_pinned:make"},
    "robots": {"protego": "app.adapters.fetch.robots_protego:make"},
    "parser": {"trafilatura_pdfplumber": "app.adapters.parse.documents:make"},
    "search": {
        "searxng": "app.adapters.search.searxng:make",
        "brave": "app.adapters.search.brave:make",
    },
    "embeddings": {
        "openai": "app.adapters.embeddings.openai:make",
        "sentence_transformers": "app.adapters.embeddings.sentence_transformers:make",
    },
    "vector": {"qdrant": "app.adapters.vector.qdrant:make"},
    "snapshots": {"postgres": "app.adapters.snapshots.postgres:make"},
    # report PDF (D3-3, BD-40): pure Python, no system libraries
    "renderer": {"fpdf2": "app.adapters.renderer.fpdf2:make"},
    # graph (D2-4, BD-11): the factory also takes the embeddings adapter
    "graph": {"graphiti_neo4j": "app.adapters.graph.graphiti:make"},
    # official APIs for Wave 0 (D2-5, BD-13), keyed by the registry's provider name
    "structured": {
        "who_gho": "app.adapters.structured.who_gho:make",
        "world_bank": "app.adapters.structured.world_bank:make",
    },
    # model providers (D2-3)
    "llm": {
        "anthropic": "app.adapters.llm.anthropic:make",
        "openai": "app.adapters.llm.openai:make",
    },
}


@dataclass
class Container:
    settings: Settings
    relational: RelationalPort | None = None
    llm: dict[str, LLMPort] = field(default_factory=dict)  # by provider
    embeddings: EmbeddingsPort | None = None
    search: SearchPort | None = None
    fetch: FetchPort | None = None
    robots: RobotsParser | None = None
    parser: ParserPort | None = None
    structured: dict[str, StructuredDataPort] = field(default_factory=dict)
    vector: VectorPort | None = None
    graph: GraphPort | None = None
    snapshots: SnapshotPort | None = None
    checkpointer: CheckpointPort | None = None
    renderer: RendererPort | None = None
    tracing: list[TracingPort] = field(default_factory=list)
    probes: list[HealthProbe] = field(default_factory=list)  # stores
    provider_probes: list[HealthProbe] = field(default_factory=list)  # BD-42
    provider_components: list[str] = field(default_factory=list)  # expected in /health
    missing: list[str] = field(default_factory=list)  # "port:provider" with no adapter yet

    async def close(self) -> None:
        """Close every adapter that holds connections."""
        adapters = (
            *self.probes, *self.provider_probes, self.relational, self.vector,
            self.snapshots, self.graph,
            self.checkpointer,
        )  # fmt: skip
        for adapter in adapters:
            close = getattr(adapter, "close", None)
            if close is not None:
                await close()


def build_container(settings: Settings, registry: AdapterRegistry | None = None) -> Container:
    registry = ADAPTERS if registry is None else registry
    config = settings.config
    container = Container(settings=settings)

    def build(port: str, provider: str, *deps: Any) -> Any:
        target = registry.get(port, {}).get(provider)
        if target is None:
            container.missing.append(f"{port}:{provider}")
            return None
        module_name, _, attr = target.partition(":")
        factory: Callable[..., Any] = getattr(importlib.import_module(module_name), attr)
        return factory(settings, *deps)

    container.relational = build("relational", "postgres")  # fixed choice (CON-04)
    container.checkpointer = build("checkpointer", "postgres", CHECKPOINT_TYPES)
    for port, provider in (
        ("probe:vector", config.vector.provider),
        ("probe:graph", config.graph.provider),
    ):
        if (probe := build(port, provider)) is not None:
            container.probes.append(probe)

    llm_providers = sorted(
        {ref.provider for _, role in config.llm.roles.items() for ref in role.model_refs()}
    )
    for provider in llm_providers:
        if (adapter := build("llm", provider)) is not None:
            container.llm[provider] = adapter

    container.embeddings = build("embeddings", config.embeddings.provider)
    container.search = build("search", config.search.provider)
    container.fetch = build("fetch", "httpx_pinned")
    container.robots = build("robots", "protego")
    container.parser = build("parser", "trafilatura_pdfplumber")
    container.vector = build("vector", config.vector.provider)
    container.graph = build("graph", config.graph.provider, container.embeddings)
    container.snapshots = build("snapshots", config.snapshots.provider)
    container.renderer = build("renderer", config.renderer.provider)
    for provider in config.structured.providers:
        if (adapter := build("structured", provider)) is not None:
            container.structured[provider] = adapter
    for provider in config.tracing.providers:
        if (adapter := build("tracing", provider)) is not None:
            container.tracing.append(adapter)

    # Every provider a run depends on is checked by /health (R-77, BD-42)
    providers = [("probe:llm", p, f"llm_{p}") for p in llm_providers]
    providers += [
        ("probe:embeddings", config.embeddings.provider, "embeddings"),
        ("probe:search", config.search.provider, "search"),
    ]
    adapters = {"probe:embeddings": container.embeddings, "probe:search": container.search}
    for port, provider, component in providers:
        container.provider_components.append(component)
        deps = (adapters[port],) if port in adapters else ()
        if (probe := build(port, provider, *deps)) is not None:
            container.provider_probes.append(probe)
    return container
