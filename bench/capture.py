"""README capture: the static site (web/snapshot.json) turning SOURCE from Honest to Saboteur.

Writes docs/source-honest-to-saboteur.gif (green ACCEPT -> red REJECT) and a fresh docs/panel.png
(the og:image). Drives the installed Microsoft Edge through Playwright, so no browser download:
    pip install -r bench/requirements.txt
    python bench/capture.py
"""
import io
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
GIF, PNG = ROOT / "docs" / "source-honest-to-saboteur.gif", ROOT / "docs" / "panel.png"
VIEW, GIF_W = (1280, 720), 800
URL = "http://trustpass.test/index.html?circuit=grover&backend=FakeBrisbane"


def serve(page):
    """Answer every request from the repo: /api/ is a 404, so the page uses the snapshot, as on Pages."""
    def handle(route):
        f = ROOT / urlparse(route.request.url).path.lstrip("/")
        route.fulfill(path=f) if f.is_file() else route.fulfill(status=404)
    page.route("**/*", handle)


def frames(page, seconds, out):
    """Screenshot as fast as we can for `seconds`; keep the real timestamps for frame durations."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        out.append((time.perf_counter(), Image.open(io.BytesIO(page.screenshot()))))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport=dict(zip(("width", "height"), VIEW)))
        serve(page)
        page.goto(URL + "&mode=honest")
        page.wait_for_timeout(3000)  # first acquisition + reveal settle
        shots = []
        frames(page, 1.5, shots)
        page.locator("#det-source button").nth(4).click()  # the Saboteur detent
        frames(page, 5.0, shots)
        browser.close()

        big = p.chromium.launch(channel="msedge")
        page = big.new_page(viewport={"width": 1920, "height": 1080})
        serve(page)
        page.goto(URL + "&mode=saboteur")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(PNG))
        big.close()

    size = (GIF_W, GIF_W * VIEW[1] // VIEW[0])
    imgs = [im.convert("RGB").resize(size, Image.LANCZOS).quantize(colors=128, dither=Image.Dither.NONE)
            for _, im in shots]
    t = [s for s, _ in shots] + [shots[-1][0] + 1.5]  # hold the REJECT frame before looping
    ms = [max(20, round(1000 * (b - a))) for a, b in zip(t, t[1:])]
    imgs[0].save(GIF, save_all=True, append_images=imgs[1:], duration=ms, loop=0, optimize=True)
    print(f"{GIF.name}: {len(imgs)} frames, {sum(ms) / 1000:.1f} s, {GIF.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
