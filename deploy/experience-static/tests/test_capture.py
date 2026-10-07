"""Bounded unauthenticated loopback extraction; never follow redirects/crawl."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

import test_public_assets as f


class CaptureTest(f.FixtureCase):

    def test_capture_only_reviewed_paths_without_cookies_and_reject_nonpublic_responses(self):
        self.assertTrue(callable(getattr(self.tool, 'capture', None)), 'explicit loopback capture missing')
        hits = []
        class Handler(BaseHTTPRequestHandler):
            status = 200
            extra = {}
            content_type = 'text/javascript; charset=utf-8'
            body = f.BODY
            def log_message(self, format, *args):
                pass
            def do_GET(self):
                hits.append((self.path, dict(self.headers)))
                self.send_response(self.status)
                self.send_header('Content-Type', self.content_type)
                self.send_header('Content-Length', str(len(self.body)))
                for k, v in self.extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(self.body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        paths = self.root / 'paths.json'
        paths.write_bytes(f.encoded([f.PREFIX + f.NAME]))
        def capture(name):
            return self.tool.capture(server.server_port, paths, f.sha(paths.read_bytes()),
                                     f.MODULE, f.ORIGIN, f.PREFIX, self.root / name)
        result = capture('captured')
        self.assertEqual(result['files'], self.spec['files'])
        self.assertEqual((self.root / 'captured' / 'source' / f.NAME).read_bytes(), f.BODY)
        self.assertEqual(len(hits), 1)
        self.assertNotIn('Cookie', hits[0][1])
        self.assertNotIn('Authorization', hits[0][1])
        for i, (status, extra, content_type, body) in enumerate([
            (302, {'Location': '/private'}, 'text/javascript', f.BODY),
            (200, {'Set-Cookie': 'private=fixture'}, 'text/javascript', f.BODY),
            (200, {'Cache-Control': 'private, no-store'}, 'text/javascript', f.BODY),
            (200, {'Content-Disposition': 'attachment'}, 'text/javascript', f.BODY),
            (200, {}, 'text/html', b'<html>login</html>'),
            (200, {}, 'text/javascript', b'<html>login</html>'),
        ]):
            Handler.status, Handler.extra, Handler.content_type, Handler.body = status, extra, content_type, body
            before = len(hits)
            with self.subTest(i=i), self.assertRaises(ValueError):
                capture('bad' + str(i))
            self.assertFalse((self.root / ('bad' + str(i))).exists())
            self.assertEqual(len(hits), before + 1, 'no redirect or discovery follow-up')
        before = len(hits)
        for i, values in enumerate([['http://elsewhere/assets/' + f.NAME], [f.PREFIX + f.NAME + '?token=x'],
                                   ['/private/assets/' + f.NAME], [f.PREFIX + f.NAME] * 2]):
            paths.write_bytes(f.encoded(values))
            with self.subTest(paths=values), self.assertRaises(ValueError):
                capture('pathsbad' + str(i))
        self.assertEqual(len(hits), before, 'reject bad scope before any HTTP')


if __name__ == '__main__':
    unittest.main()
