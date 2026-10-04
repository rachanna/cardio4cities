"""The web app, end to end in a real browser (D3-4, BD-41; owner: a Playwright smoke).
Sign in, find the city and see the identity chosen before research (AT-24's UI half),
open the stored brief, follow a fact to its evidence, explore findings and an entity's
graph view, and ask a question. Screenshots at phone and laptop widths go to
`tests/e2e/screenshots/` (git-ignored) for review. Fictional Halden Bay, Norvania."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, ViewportSize, expect, sync_playwright

from tests.e2e.conftest import ACCESS_CODE, ADMIN_CODE, Site

pytestmark = [pytest.mark.db, pytest.mark.stores]
SHOTS = Path(__file__).resolve().parent / "screenshots"
SIZES: dict[str, ViewportSize] = {
    "phone": {"width": 390, "height": 844},
    "laptop": {"width": 1366, "height": 900},
}


@pytest.fixture
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def shot(page: Page, size: str, name: str) -> None:
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{size}-{name}.png"), full_page=True)


def sign_in(page: Page, site: Site, code: str) -> None:
    page.goto(site.url + "/")
    page.get_by_label("Access code").fill(code)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Research a city")).to_be_visible()


@pytest.mark.parametrize("size", list(SIZES))
def test_a_city_lead_walks_through_the_app(site: Site, browser: Browser, size: str) -> None:
    page = browser.new_page(viewport=SIZES[size])
    page.goto(site.url + "/")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    shot(page, size, "01-sign-in")
    sign_in(page, site, ACCESS_CODE)

    # Start: the identity is shown before any research starts (AT-24)
    page.get_by_label("City name").fill("Halden Bay")
    page.get_by_role("button", name="Find").click()
    expect(page.get_by_text("You chose")).to_be_visible()
    expect(page.get_by_role("button", name="Research Halden Bay")).to_be_visible()
    shot(page, size, "02-start")

    # Open existing: the stored brief, no new research (AT-25)
    page.get_by_role("link", name="Halden Bay").click()
    expect(page.get_by_role("heading", name="Summary")).to_be_visible()
    expect(page.get_by_text("Download report (PDF)")).to_be_visible()
    expect(page.get_by_text("Not city-level").first).to_be_visible()
    shot(page, size, "03-brief")

    # The evidence panel from a fact (AT-12)
    page.get_by_role("button", name="Evidence").first.click()
    drawer = page.get_by_role("dialog", name="Evidence")
    expect(drawer.get_by_text("Independent check")).to_be_visible()
    expect(drawer.get_by_text("Retrieved")).to_be_visible()
    shot(page, size, "04-evidence")
    drawer.get_by_role("button", name="Close").click()

    # Explore: findings, then an entity read from the knowledge graph
    page.get_by_role("link", name="Explore").click()
    expect(page.get_by_role("heading", name="Findings")).to_be_visible()
    page.get_by_role("button", name="Halden Bay Health Office").click()
    expect(page.get_by_role("img", name="Halden Bay Health Office and its")).to_be_visible()
    shot(page, size, "05-entity")

    # Ask: a cited answer, then an honest gap
    page.get_by_role("link", name="Ask").click()
    page.get_by_label("Question").fill("Who runs public health in Halden Bay?")
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.get_by_text("has run public health in Halden Bay since April 2024")).to_be_visible()
    page.get_by_label("Question").fill("Does Halden Bay have a salt reduction policy?")
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.get_by_text("No confirmed tobacco or salt policies for Halden Bay")).to_be_visible()
    shot(page, size, "06-ask")
    page.close()


def test_the_presenter_sees_the_workflow_and_answer_traces(site: Site, browser: Browser) -> None:
    page = browser.new_page(viewport=SIZES["laptop"])
    sign_in(page, site, ADMIN_CODE)
    page.get_by_role("link", name="Presenter").click()
    expect(page.get_by_role("heading", name="Presenter tools")).to_be_visible()
    expect(page.get_by_label("Workflow diagram").first.locator("svg")).to_be_visible(timeout=20_000)
    shot(page, "laptop", "07-workflow")
    page.goto(f"{site.url}/city/ask/?id={site.city_id}")
    page.get_by_label("Question").fill("Who runs public health in Halden Bay?")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_role("button", name="Why this answer").click()
    expect(page.get_by_role("cell", name="Knowledge graph")).to_be_visible()
    shot(page, "laptop", "08-trace")
    page.close()
    assert os.environ.get("C4C_REQUIRE_WEB") != "1" or (SHOTS / "laptop-08-trace.png").exists()
