"""Content-Usage preferences (LLD-2 §9.1 step 6, §9.3; R-86). Parsed by our own code
because general robots.txt parsers ignore these lines.

Sources (checked 2026-10-03, BD-07):
- draft-ietf-aipref-vocab-08: categories `train-ai`, `ai-use`, `search`; values y / n.
- draft-ietf-aipref-attach-05: robots.txt rule `Content-Usage: [path] usage-pref` inside
  user-agent groups, longest-prefix matching like Allow/Disallow; the same preferences
  as an HTTP response header (a structured-field dictionary).
- Cloudflare Content Signals: `Content-Signal: ai-input=no, ai-train=no, search=yes`.

Blocking (owner decision, BD-07): the categories that cover this system's use, feeding
pages to models at request time. `train-ai` and `search` opt-outs are recorded, not
blocking: the system neither trains models nor runs a search index.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.workflow.rules.robots import Group, match_length, path_matches, select_rules

BLOCKING = frozenset({"ai-use", "ai", "tdm", "ai-input"})  # 'ai', 'tdm': earlier draft names
NO_VALUES = frozenset({"n", "no"})
DIRECTIVES = ("content-usage", "content-signal")


@dataclass(frozen=True)
class UsageDecision:
    blocked: bool
    rule: str | None  # the line or header that decided it
    preferences: dict[str, str]  # everything stated, for the crawl decision record


def parse_preferences(value: str) -> dict[str, str]:
    """'train-ai=n, ai-use=y' -> {'train-ai': 'n', 'ai-use': 'y'} (lower-cased)."""
    prefs: dict[str, str] = {}
    for item in re.split(r"[,;]", value):
        if "=" in item:
            key, val = (part.strip().lower().strip('"') for part in item.split("=", 1))
            if key:
                prefs[key] = val
    return prefs


def _decide(prefs: dict[str, str], rule: str | None) -> UsageDecision:
    blocked = any(prefs.get(k) in NO_VALUES for k in BLOCKING)
    return UsageDecision(blocked=blocked, rule=rule if prefs else None, preferences=prefs)


def from_header(headers: dict[str, str]) -> UsageDecision:
    """Response headers `Content-Usage` and `Content-Signal` (lower-cased names)."""
    prefs: dict[str, str] = {}
    rules = []
    for name in DIRECTIVES:
        if name in headers:
            prefs.update(parse_preferences(headers[name]))
            rules.append(f"{name}: {headers[name]}")
    return _decide(prefs, "; ".join(rules) or None)


def from_robots(groups: list[Group], user_agent: str, url: str) -> UsageDecision:
    """Preferences from the robots.txt group that applies to us, for this path."""
    path = urlsplit(url).path or "/"
    best: tuple[int, str, dict[str, str]] | None = None
    for name, value in select_rules(groups, user_agent):
        if name not in DIRECTIVES:
            continue
        pattern, prefs_text = "/", value
        first, _, rest = value.partition(" ")
        if first.startswith("/") and rest.strip():
            pattern, prefs_text = first, rest
        if not path_matches(pattern, path):
            continue
        length = match_length(pattern)
        if best is None or length >= best[0]:
            prefs = parse_preferences(prefs_text)
            if best is not None and length == best[0]:
                prefs = {**best[2], **prefs}  # same path: combine, e.g. two directives
            best = (length, f"{name}: {value}", prefs)
    if best is None:
        return UsageDecision(False, None, {})
    return _decide(best[2], best[1])
