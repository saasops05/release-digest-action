"""Offline tests: python3 -m unittest -v test_digest.py (no secrets, no network)."""
import http.server
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import digest  # noqa: E402


def run(*args, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SLACK_", "DIGEST_", "GITHUB_"))}
    e.update(env or {})
    return subprocess.run([sys.executable, str(HERE / "digest.py"), *args],
                          capture_output=True, text=True, env=e)


class DigestTests(unittest.TestCase):
    def test_sample_fixture_renders_with_footer(self):
        r = run("--fixture", "sample")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(":sparkles: *Features*", r.stdout)
        self.assertIn("Sample data from a fixture", r.stdout)
        self.assertIn("saasops05.github.io/saasops-digest-demo/scorecard.html", r.stdout)
        self.assertIn("not posted", r.stderr)

    def test_no_footer(self):
        r = run("--fixture", "fixture-release.json", "--no-footer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("SaaS Ops Tune-Up", r.stdout)

    def test_empty_window(self):
        r = run("--fixture", "fixture-empty.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No merged PRs", r.stdout)

    def test_escapes_slack_markup(self):
        out = digest.render({"title": "x", "pull_requests": [
            {"number": 1, "title": "a <b> & c", "labels": [], "url": ""}]})
        self.assertIn("a &lt;b&gt; &amp; c", out)

    def test_missing_repo_fails_without_inventing(self):
        r = run()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")

    def test_dry_run_beats_webhook(self):
        r = run("--fixture", "sample", "--dry-run", env={"SLACK_WEBHOOK_URL": "http://127.0.0.1:9/x"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry-run", r.stderr)

    def test_posts_to_local_mock_webhook_and_sets_outputs(self):
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        out_file = HERE / ".test-github-output"
        out_file.write_text("")
        try:
            r = run("--fixture", "sample", env={
                "SLACK_WEBHOOK_URL": "http://127.0.0.1:%d/hook" % srv.server_port,
                "GITHUB_OUTPUT": str(out_file)})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(got), 1)
            self.assertIn("Weekly PR digest", got[0]["text"])
            outputs = out_file.read_text()
            self.assertIn("posted=true", outputs)
            self.assertIn("pr-count=7", outputs)
        finally:
            out_file.unlink()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
