"""The Vercel config must forward every API path the page calls, with the origin secret."""

import json
import re

from recommender.api import WEB_DIR

CONFIG = json.loads((WEB_DIR / "vercel.json").read_text())


def proxied_paths() -> set[str]:
    (route,) = CONFIG["routes"]
    return set(re.fullmatch(r"/\((.+)\)", route["src"]).group(1).split("|"))


def test_every_path_the_page_calls_is_forwarded():
    js = (WEB_DIR / "static" / "app.js").read_text()
    called = set(re.findall(r'callApi\("/([a-z]+)"', js))
    assert called == {"meta", "recommend"}  # update both files if the page starts calling another path
    assert called <= proxied_paths()


def test_forwarded_calls_carry_the_secret_from_the_env():
    (route,) = CONFIG["routes"]
    (transform,) = route["transforms"]
    assert route["dest"].startswith("https://") and route["dest"].endswith("/$1")
    assert transform["target"]["key"] == "x-origin-secret"
    assert transform["args"] == "$ORIGIN_SECRET" and transform["env"] == ["ORIGIN_SECRET"]


def test_vercel_config_is_not_served_or_packaged():
    # The API only mounts web/static, and package-data lists web/*.html and web/static/*.
    assert not (WEB_DIR / "static" / "vercel.json").exists()
