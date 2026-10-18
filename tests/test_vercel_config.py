"""The Vercel config (repo root) must serve the page and forward every API path it calls."""

import json
import re

from recommender.api import WEB_DIR
from recommender.config import PROJECT_ROOT

CONFIG = json.loads((PROJECT_ROOT / "vercel.json").read_text())


def proxied_paths() -> set[str]:
    (route,) = CONFIG["routes"]
    return set(re.fullmatch(r"/\((.+)\)", route["src"]).group(1).split("|"))


def test_serves_the_web_folder_as_a_static_site():
    # framework null = "Other": without it Vercel sees pyproject.toml and tries to deploy FastAPI.
    assert CONFIG["framework"] is None and CONFIG["installCommand"] == ""
    assert PROJECT_ROOT / CONFIG["outputDirectory"] == WEB_DIR
    assert (WEB_DIR / "index.html").exists() and (WEB_DIR / "static" / "app.js").exists()


def test_every_path_the_page_calls_is_forwarded():
    js = (WEB_DIR / "static" / "app.js").read_text()
    called = set(re.findall(r'callApi\("/([a-z]+)"', js))
    assert called == {"meta", "recommend"}  # update both files if the page starts calling another path
    assert called <= proxied_paths()


def test_forwarded_calls_go_to_railway_with_the_secret_from_the_env():
    (route,) = CONFIG["routes"]
    (transform,) = route["transforms"]
    assert re.fullmatch(r"https://[a-z0-9-]+\.up\.railway\.app/\$1", route["dest"])
    assert transform["target"]["key"] == "x-origin-secret"
    assert transform["args"] == "$ORIGIN_SECRET" and transform["env"] == ["ORIGIN_SECRET"]


def test_no_vercel_config_inside_the_published_folder():
    # Everything in WEB_DIR is public on Vercel.
    assert not list(WEB_DIR.rglob("vercel.json"))
