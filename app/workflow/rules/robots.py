"""robots.txt status handling (RFC 9309 §2.3.1, LLD-2 §9.2) and the group and path
matcher used for our own directives (Content-Usage).

RFC 9309, checked when implementing (BD-07):
- §2.3.1.3 unavailable (4xx): crawlers MAY access any resources.
- §2.3.1.4 unreachable (5xx or network failure): crawlers MUST assume complete disallow.
- §2.3.1.2 redirects: follow at least five consecutive redirects.
- §2.5 limits: parse at least the first 500 KiB.
- §2.2.1 group selection: match the product token case-insensitively; a matching
  group replaces `*`; several groups for the same agent are combined.
- §2.2.2 longest match wins; when Allow and Disallow are equally long, Allow wins.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

ROBOTS_MAX_BYTES = 500 * 1024
ROBOTS_MAX_REDIRECTS = 5

Availability = Literal["parsed", "unavailable", "unreachable_server_error", "unreachable_network"]


def robots_availability(status: int | None) -> Availability:
    """`status` None means the request failed at the network level or timed out."""
    if status is None:
        return "unreachable_network"
    if 200 <= status < 300:
        return "parsed"
    if 400 <= status < 500:
        return "unavailable"
    return "unreachable_server_error"


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[str, str]] = field(default_factory=list)  # (field name, value)


def parse_groups(text: str) -> list[Group]:
    """RFC 9309 groups: consecutive user-agent lines start a group; rules follow."""
    groups: list[Group] = []
    current: Group | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        name = name.lower()
        if name == "user-agent":
            if current is None or not last_was_agent:
                current = Group()
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
        else:
            if current is not None:
                current.rules.append((name, value))
            last_was_agent = False
    return groups


def product_token(user_agent: str) -> str:
    return re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0].lower()


def select_rules(groups: list[Group], user_agent: str) -> list[tuple[str, str]]:
    """Rules of every group naming our product token, else of every `*` group."""
    token = product_token(user_agent)
    mine = [g for g in groups if token in g.agents]
    chosen = mine or [g for g in groups if "*" in g.agents]
    return [rule for g in chosen for rule in g.rules]


def _pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = re.escape(path.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def path_matches(pattern: str, path: str) -> bool:
    return bool(_pattern(pattern).match(path))


def match_length(pattern: str) -> int:
    """Specificity used for longest match: the pattern length without wildcards."""
    return len(pattern.replace("*", "").rstrip("$"))
