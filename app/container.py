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

from app.ports.embeddings import EmbeddingsPort
from app.ports.fetch import FetchPort
from app.ports.graph import GraphPort
from app.ports.llm import LLMPort
from app.ports.renderer import RendererPort
from app.ports.repos import RelationalPort
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.structured import StructuredDataPort
from app.ports.tracing import TracingPort
from app.ports.vector import VectorPort
from app.settings import Settings

# port -> provider -> "module:factory"
AdapterRegistry = Mapping[str, Mapping[str, str]]
ADAPTERS: AdapterRegistry = {
    "relational": {"postgres": "app.adapters.postgres.relational:make"},
}


@dataclass
class Container:
    settings: Settings
    relational: RelationalPort | None = None
    llm: dict[str, LLMPort] = field(default_factory=dict)  # by provider
    embeddings: EmbeddingsPort | None = None
    search: SearchPort | None = None
    fetch: FetchPort | None = None
    structured: dict[str, StructuredDataPort] = field(default_factory=dict)
    vector: VectorPort | None = None
    graph: GraphPort | None = None
    snapshots: SnapshotPort | None = None
    renderer: RendererPort | None = None
    tracing: list[TracingPort] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # "port:provider" with no adapter yet


def build_container(settings: Settings, registry: AdapterRegistry | None = None) -> Container:
    registry = ADAPTERS if registry is None else registry
    config = settings.config
    container = Container(settings=settings)

    def build(port: str, provider: str) -> Any:
        target = registry.get(port, {}).get(provider)
        if target is None:
            container.missing.append(f"{port}:{provider}")
            return None
        module_name, _, attr = target.partition(":")
        factory: Callable[[Settings], Any] = getattr(importlib.import_module(module_name), attr)
        return factory(settings)

    container.relational = build("relational", "postgres")  # fixed choice (CON-04)

    llm_providers = sorted(
        {ref.provider for _, role in config.llm.roles.items() for ref in role.model_refs()}
    )
    for provider in llm_providers:
        if (adapter := build("llm", provider)) is not None:
            container.llm[provider] = adapter

    container.embeddings = build("embeddings", config.embeddings.provider)
    container.search = build("search", config.search.provider)
    container.fetch = build("fetch", "httpx_pinned")
    container.vector = build("vector", config.vector.provider)
    container.graph = build("graph", config.graph.provider)
    container.snapshots = build("snapshots", config.snapshots.provider)
    container.renderer = build("renderer", config.renderer.provider)
    for provider in config.tracing.providers:
        if (adapter := build("tracing", provider)) is not None:
            container.tracing.append(adapter)
    return container
