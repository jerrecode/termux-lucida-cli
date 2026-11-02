"""Offline protocol, CLI, input validation and filesystem regression tests."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import termux_lucida as m


class FakeResponse(io.BytesIO):
    def __init__(self, data, headers):
        super().__init__(data)
        from email.message import Message
        msg = Message()
        for key, value in headers.items():
            msg[key] = value
        self.headers = msg


class ProtocolTests(unittest.TestCase):
    def test_sveltekit_data_extraction_json5(self):
        payload = "<script>foo,{\"type\":\"data\",\"data\":{info:{type:'track',title:'Hello',url:'https://play.qobuz.com/track/123'},tokenExpiry:123,token:'abc'},\"uses\":{\"url\":1}}];</script>"
        result = m.parse_page(payload)
        self.assertEqual(result['info']['title'], 'Hello')
        self.assertEqual(result['tokenExpiry'], 123)

    def test_missing_data_is_error(self):
        with self.assertRaises(m.LucidaError):
            m.parse_page('<title>Just a moment</title>')

    def test_search_nested(self):
        item = {'title': 'Track', 'url': 'https://play.qobuz.com/track/99', 'artists': [{'name': 'Ar'}], 'album': {'title': 'Al'}}
        result = m.search_items([{'foo': {'results': {'tracks': [item], 'albums': []}}}])
        self.assertEqual(result[0]['artist'], 'Ar')
        self.assertEqual(result[0]['album'], 'Al')

    def test_token_and_album(self):
        token = base64.b64encode(base64.b64encode(b'secret')).decode()
        tracks, expiry, _ = m.tracks_from_page({'info': {'type': 'track', 'url': 'https://tidal.com/x'}, 'token': token, 'tokenExpiry': 3})
        self.assertEqual(tracks[0]['csrf'], 'secret')
        self.assertEqual(expiry, 3)
        many, _, _ = m.tracks_from_page({'info': {'type': 'album', 'tracks': [{'url': 'https://tidal.com/x', 'csrf': 'token'}]}, 'tokenExpiry': 3})
        self.assertEqual(len(many), 1)

    def test_source_url_restrictions(self):
        self.assertTrue(m.service_url('https://play.qobuz.com/track/123'))
        for url in ('http://tidal.com/abc', 'https://evil.example/a', 'https://tidal.com.evil.example/x', 'https://a:b@tidal.com/x', 'file:///etc/passwd'):
            self.assertFalse(m.service_url(url), url)

    def test_worker_hostname_and_id_validation(self):
        self.assertEqual(m.safe_worker('us-east', 'abc-def'), 'https://us-east.lucida.to/api/fetch/request/abc-def')
        for server, handoff in [('example.org', '123'), ('foo/bar', '123'), ('server', '../passwd'), ('server', 'abc?x=1')]:
            with self.assertRaises(m.LucidaError):
                m.safe_worker(server, handoff)

    def test_path_sanitize(self):
        self.assertEqual(m.safe_name('../../Evil:Title.mp3'), '_.._Evil_Title.mp3')
        self.assertEqual(m.safe_name('  . '), 'Unknown')

    def test_download_stream_is_atomic_and_no_overwrite(self):
        client = m.Client()
        audio = b'fLaC' + b'0' * 1000
        with tempfile.TemporaryDirectory() as tmp:
            response = FakeResponse(audio, {'Content-Type': 'audio/flac', 'Content-Disposition': 'attachment; filename="../../ABC.flac"', 'Content-Length': str(len(audio))})
            with patch.object(client, 'request', return_value=response):
                path = client.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), 'fallback')
            self.assertEqual(path.parent, Path(tmp))
            self.assertEqual(path.read_bytes(), audio)
            self.assertFalse((Path(tmp) / (path.name + '.part')).exists())
            response2 = FakeResponse(b'different', {'Content-Type': 'audio/flac'})
            with patch.object(client, 'request', return_value=response2):
                same = client.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), path.stem)
            self.assertEqual(same, path)
            self.assertEqual(path.read_bytes(), audio)

    def test_truncated_file_cleans_part(self):
        client = m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            response = FakeResponse(b'abc', {'Content-Type': 'audio/flac', 'Content-Length': '9'})
            with patch.object(client, 'request', return_value=response):
                with self.assertRaises(m.LucidaError):
                    client.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), 'broken')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_pick_explicit_required(self):
        with self.assertRaises(m.LucidaError):
            m.resolve_input(m.Client(), 'Some Artist - Song', 'amazon', 'tracks', None)

    def test_cli_no_network(self):
        self.assertEqual(m.main(['services']), 0)
        self.assertEqual(m.main(['download', 'track name']), 1)


if __name__ == '__main__':
    unittest.main()
