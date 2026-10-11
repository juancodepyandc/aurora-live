import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).resolve().parents[1] / 'status_check.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
URL = 'https://example-aurora.trycloudflare.com'


class Availability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / 'README.md').write_text('before\n<!--STATUS-->old<!--/STATUS-->\nafter', encoding='utf-8')
        (self.repo / 'tunnel.txt').write_text(URL, encoding='utf-8')

    def test_power_loss_and_recovery_retains_candidate(self):
        self.assertEqual(m.update(self.repo, checker=lambda _: True), 'online')
        self.assertEqual(m.update(self.repo, checker=lambda _: False), 'offline')
        self.assertEqual((self.repo / 'tunnel.txt').read_text(), '')
        self.assertNotIn(URL, (self.repo / 'README.md').read_text(encoding='utf-8'))
        self.assertEqual(m.update(self.repo, checker=lambda u: u == URL), 'online')
        self.assertEqual((self.repo / 'tunnel.txt').read_text().strip(), URL)

    def test_external_checkpoint_records_its_own_probe(self):
        m.update(self.repo, checker=lambda _: True)
        record = json.loads((self.repo / 'status.json').read_text())
        # A local heartbeat within the coalescing window is preserved.
        recent = (m.datetime.datetime.now(m.datetime.timezone.utc)
                  - m.datetime.timedelta(seconds=30)).isoformat(timespec='seconds')
        record['checked_at'] = recent
        (self.repo / 'status.json').write_text(json.dumps(record))
        m.update(self.repo, checker=lambda _: True)
        self.assertEqual(json.loads((self.repo / 'status.json').read_text())['checked_at'], recent)
        m.update(self.repo, checker=lambda _: True, checkpoint=True)
        self.assertNotEqual(json.loads((self.repo / 'status.json').read_text())['checked_at'], recent)

    def test_open_requires_verified_public_health(self):
        self.assertEqual(m.update(self.repo, 'open', URL, lambda _: False), 'offline')

    def test_shutdown_never_probes(self):
        def forbidden(_):
            self.fail('Shutdown must not wait for HTTP')
        self.assertEqual(m.update(self.repo, 'closed', URL, forbidden), 'offline')

    def test_new_tunnel_supersedes_old_candidate(self):
        m.update(self.repo, checker=lambda _: False)
        new = 'https://renewed-aurora.trycloudflare.com'
        m.update(self.repo, url=new, checker=lambda _: True)
        self.assertEqual(json.loads((self.repo / 'status.json').read_text())['candidate_url'], new)

    def test_invalid_urls_and_missing_marker_do_not_mutate(self):
        for url in ['http://localhost', 'https://example.com', URL + '/bad', URL + '\n']:
            with self.assertRaises(ValueError):
                m.update(self.repo, url=url)
        (self.repo / 'README.md').write_text('missing')
        with self.assertRaises(ValueError):
            m.update(self.repo, url=URL, checker=lambda _: True)
        self.assertEqual((self.repo / 'tunnel.txt').read_text(), URL)

    def test_http_errors_wrong_identity_and_bad_json_are_offline(self):
        for body in [b'{}', b'{"ok":true,"service":"other"}', b'{"ok":false,"service":"aurora-bridge"}', b'not json', b'[]']:
            response = MagicMock()
            response.status = 200
            response.read.return_value = body
            with patch.object(m.urllib.request, 'urlopen') as request:
                request.return_value.__enter__.return_value = response
                self.assertFalse(m.probe(URL))
        with patch.object(m.urllib.request, 'urlopen', side_effect=TimeoutError):
            self.assertFalse(m.probe(URL))

    def test_actual_health_identity_is_required(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"ok":true,"service":"aurora-bridge"}'
        with patch.object(m.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value = response
            self.assertTrue(m.probe(URL))
            self.assertEqual(request.call_args.args[0], URL + '/api/health')


if __name__ == '__main__':
    unittest.main()
