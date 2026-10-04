"""Spike S-3's offline parts (BD-36; code review RV-107): the site list from a git-ignored
file, one small request per official API, and a summary that names no site."""

from pathlib import Path

from scripts.spikes import reachability


def test_sites_come_from_the_file_without_comments_or_blank_lines(tmp_path: Path) -> None:
    listed = tmp_path / "sites.txt"
    listed.write_text(
        "# health sites\nhttps://health.halden-bay.test/\n\n"
        "https://data.halden-bay.test/x  # the open data portal\n",
        encoding="utf-8",
    )
    assert reachability.read_sites(listed) == [
        "https://health.halden-bay.test/",
        "https://data.halden-bay.test/x",
    ]
    assert reachability.read_sites(tmp_path / "missing.txt") == []


def test_the_default_site_list_is_git_ignored() -> None:
    assert reachability.DEFAULT_SITES.parent.name == "spike_results"


def test_each_official_api_is_asked_for_one_row() -> None:
    probes = reachability.api_probes(
        {"who_gho": "https://gho.example/api/", "world_bank": "https://wb.example/v2"}
    )
    assert probes["who_gho"] == "https://gho.example/api/NCD_HYP_PREVALENCE_A?$top=1"
    assert probes["world_bank"].startswith("https://wb.example/v2/country/WLD/indicator/")
    assert "perpage=1" in probes["dhs"]


def test_the_summary_counts_sites_by_outcome_and_names_none() -> None:
    rows = [
        ("https://health.halden-bay.test/a", "fetched (parsed)", ""),
        ("https://health.halden-bay.test/b", "fetched (parsed)", ""),
        ("https://archive.halden-bay.test/", "blocked_robots", "robots.txt disallows"),
    ]
    summary = reachability.report({"who_gho": "reachable"}, rows)
    assert "- fetched (parsed): 2" in summary
    assert "- blocked_robots: 1" in summary
    assert "- who_gho: reachable" in summary
    assert "halden-bay" not in summary
