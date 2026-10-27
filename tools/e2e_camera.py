"""End-to-end test of the living sheet with a fake webcam.

Usage: /usr/bin/python3 tools/e2e_camera.py <static_dir> <payload> <cam.y4m> [seconds]
Serves static/ on localhost, opens touch.html#d=<payload> in Chromium whose camera is the
synthetic video, presses "start", and prints everything the page would have spoken.
"""
import functools
import http.server
import json
import sys
import threading

from playwright.sync_api import sync_playwright

static_dir, payload, video = sys.argv[1], sys.argv[2], sys.argv[3]
seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 12

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=static_dir)
handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/touch.html#d={payload}"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                f"--use-file-for-fake-video-capture={video}"])
    ctx = b.new_context(viewport={"width": 420, "height": 900}, permissions=["camera"])
    ctx.add_init_script("window.__TS_TEST = true;")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(url)
    pg.wait_for_timeout(800)
    pg.click("#start")
    samples = []
    for _ in range(int(seconds * 4)):
        pg.wait_for_timeout(250)
        samples.append(pg.evaluate("[window.__tracker && window.__tracker.seen, window.__lastPlate]"))
    pg.screenshot(path=video.replace(".y4m", "_page.png"))
    spoken = pg.evaluate("window.__spoken")
    print(json.dumps({"spoken": spoken, "errors": errors[:5],
                      "markers_seen_max": max((s[0] or 0) for s in samples),
                      "plate_samples": [s[1] for s in samples if s[1]][:6]}, ensure_ascii=False, indent=1))
    b.close()
srv.shutdown()
