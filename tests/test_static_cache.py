"""After a deploy the browser must run the new app.js, not a copy it decided was still fresh.

2026-09-24: a tab opened after the #113 deploy was running #111's app.js. /static sent Last-Modified and an
ETag but no Cache-Control, so Chrome picked a lifetime itself. no-cache keeps the cache and makes every
load ask first: a 304 when nothing changed, the new file when something did.
"""


def test_the_app_script_and_styles_revalidate_on_every_load(client):
    for path in ("/static/app.js", "/static/app.css", "/static/index.html"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path


def test_an_unchanged_script_costs_a_304(client):
    etag = client.get("/static/app.js").headers["etag"]
    assert client.get("/static/app.js", headers={"If-None-Match": etag}).status_code == 304


def test_the_page_itself_revalidates(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache"
