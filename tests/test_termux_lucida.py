"""Offline protocol, CLI, input validation and filesystem regression tests."""
import base64
import errno
import os
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.request import Request
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
            self.assertEqual(path.status, 'saved')
            self.assertEqual(path.path.parent, Path(tmp))
            self.assertEqual(path.path.read_bytes(), audio)
            self.assertFalse(list(Path(tmp).glob('*.part')))
            response2 = FakeResponse(b'different', {'Content-Type': 'audio/flac'})
            with patch.object(client, 'request', return_value=response2):
                same = client.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), path.path.stem)
            self.assertEqual(same.status, 'skipped')
            self.assertEqual(same.path, path.path)
            self.assertEqual(path.path.read_bytes(), audio)

    def test_truncated_file_cleans_part(self):
        client = m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            response = FakeResponse(b'abc', {'Content-Type': 'audio/flac', 'Content-Length': '9'})
            with patch.object(client, 'request', return_value=response):
                with self.assertRaises(m.LucidaError):
                    client.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), 'broken')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_handoff_request_has_expected_contract(self):
        client = m.Client()
        calls = []
        def fake_request(method, url, data=None, **kw):
            calls.append((method, url, data))
            return json.dumps({'server': 'download-2', 'handoff': 'a_123'})
        with patch.object(client, 'request', side_effect=fake_request):
            job_url = client.start({'url': 'https://play.qobuz.com/track/77', 'csrf': 'token1', 'csrfFallback': None}, 999, 'original', 'NL')
        self.assertEqual(job_url, 'https://download-2.lucida.to/api/fetch/request/a_123')
        self.assertEqual(calls[0][0], 'POST')
        self.assertEqual(calls[0][2]['token']['expiry'], 999)
        self.assertEqual(calls[0][2]['account'], {'id': 'NL', 'type': 'country'})
        self.assertIn('url=%2Fapi%2Ffetch%2Fstream%2Fv2', calls[0][1])

    def test_handoff_invalid_body(self):
        client = m.Client()
        with patch.object(client, 'request', return_value='[]'):
            with self.assertRaises(m.LucidaError):
                client.start({'url': 'https://play.qobuz.com/track/77', 'csrf': 'token'}, 123)

    def test_poll_complete_and_failed(self):
        client = m.Client()
        with patch.object(client, 'request', side_effect=['{"status":"processing"}', '{"status":"completed"}']):
            with patch.object(m.time, 'sleep'):
                client.poll('https://download.lucida.to/api/fetch/request/id', deadline=2)
        with patch.object(client, 'request', return_value='{"status":"error", "message":"unavailable"}'):
            with self.assertRaisesRegex(m.LucidaError, 'unavailable'):
                client.poll('https://download.lucida.to/api/fetch/request/id', deadline=2)

    def test_cookie_unredirected_and_https_only(self):
        client = m.Client(cookie="cf_clearance=secret")
        class Capture:
            def open(self, req, timeout):
                self.request = req
                return FakeResponse(b"ok", {"Content-Type": "text/plain"})
        fake = Capture()
        client.opener = fake
        self.assertEqual(client.request("GET", "https://lucida.to/"), "ok")
        self.assertNotIn("Cookie", fake.request.headers)
        self.assertEqual(fake.request.unredirected_hdrs["Cookie"], "cf_clearance=secret")
        self.assertEqual(client.request("GET", "https://a.lucida.to/"), "ok")
        self.assertNotIn("Cookie", fake.request.unredirected_hdrs)
        with self.assertRaises(m.LucidaError):
            m.HTTPSOnlyRedirect().redirect_request(Request("https://lucida.to/"), None, 302, "redirect", {}, "http://evil.test")

    def test_pick_explicit_required(self):
        with self.assertRaises(m.LucidaError):
            m.resolve_input(m.Client(), 'Some Artist - Song', 'amazon', 'tracks', None)

    def test_cli_no_network(self):
        self.assertEqual(m.main(['services']), 0)
        self.assertEqual(m.main(['download', 'track name']), 1)


class HardeningTests(unittest.TestCase):
    def test_sveltekit_trailing_data_format_changes(self):
        text = """<script>abc,{"type":"data","data":{info:{title:'X }, and " yes'},desc:'single-quote { ok }',extra: [1,2,],},"uses":{"url":1,"anything":123}}];</script>"""
        result = m.parse_page(text)
        self.assertEqual(result['info']['title'], 'X }, and " yes')
        self.assertEqual(result['desc'], 'single-quote { ok }')

    def test_untrusted_host_and_malformed_url(self):
        c = m.Client()
        for url in ('https://evil.example/x', 'http://lucida.to',
                    'https://lucida.to:123/x', 'https://lucida.to.evil.test/a'):
            with self.assertRaises(m.LucidaError):
                c.request('GET', url, attempts=1)
        for url in ('https://[', 'https://play.qobuz.com:invalid/a'):
            self.assertFalse(m.service_url(url))

    def test_no_cross_origin_redirect_for_api(self):
        redir = m.HTTPSOnlyRedirect()
        with self.assertRaisesRegex(m.LucidaError, 'cross-origin'):
            redir.redirect_request(Request('https://lucida.to/api/load', data=b'{}'), None, 302, 'moved', {}, 'https://evil.example/steal')
        with self.assertRaisesRegex(m.LucidaError, 'cross-origin'):
            redir.redirect_request(Request('https://lucida.to/search'), None, 302, 'moved', {}, 'https://evil.example/search')
        resp = redir.redirect_request(Request('https://one.lucida.to/api/fetch/request/id/download'), None, 302, 'moved', {}, 'https://cdn.example/file.flac')
        self.assertEqual(resp.full_url, 'https://cdn.example/file.flac')

    def test_existing_modes_are_explicit_and_never_overwrite(self):
        c = m.Client()
        job = 'https://x.lucida.to/api/fetch/request/abc'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/'Track.flac').write_bytes(b'old data')
            def resp():
                return FakeResponse(b'fLaC' + b'new', {'Content-Type':'audio/flac', 'Content-Disposition':'attachment; filename="Track.flac"'})
            with patch.object(c, 'request', side_effect=lambda *a, **kw: resp()):
                s = c.download(job, out, 'x')
                self.assertEqual(s.status, 'skipped')
                with self.assertRaises(m.LucidaError):
                    c.download(job, out, 'x', on_existing='fail')
                r = c.download(job, out, 'x', on_existing='rename')
            self.assertEqual(r.status, 'saved')
            self.assertEqual(r.path.name, 'Track (2).flac')
            self.assertEqual((out/'Track.flac').read_bytes(), b'old data')
            self.assertFalse(list(out.glob('*.part')))

    def test_shared_storage_hardlink_unsupported_fallback(self):
        c = m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(c, 'request', return_value=FakeResponse(b'fLaC'+b'a'*10, {'Content-Type':'audio/flac'})):
                with patch.object(m.os, 'link', side_effect=OSError(errno.EPERM, 'no hardlinks')):
                    result = c.download('https://x.lucida.to/api/fetch/request/a', Path(tmp), 'song')
            self.assertEqual(result.status, 'saved')
            self.assertEqual(result.path.read_bytes(), b'fLaC'+b'a'*10)
            self.assertEqual(list(Path(tmp).glob('*.part')), [])

    def test_audio_error_with_misreported_content_type(self):
        c = m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(c, 'request', return_value=FakeResponse(b'<html>denied</html>', {'Content-Type':'application/octet-stream'})):
                with self.assertRaisesRegex(m.LucidaError, 'disguised'):
                    c.download('https://x.lucida.to/api/fetch/request/a', Path(tmp), 'song')
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_hardlink_destination_race_no_clobber(self):
        c = m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            original = m.os.link
            call = [0]
            def simultaneous(src, dst):
                call[0] += 1
                if call[0] == 1:
                    Path(dst).write_bytes(b'unrelated')
                    raise FileExistsError(errno.EEXIST, 'exists', str(dst))
                return original(src, dst)
            with patch.object(c, 'request', return_value=FakeResponse(b'fLaC' + b'correct', {'Content-Type':'audio/flac'})):
                with patch.object(m.os, 'link', side_effect=simultaneous):
                    new = c.download('https://x.lucida.to/api/fetch/request/id', out, 'song', on_existing='rename')
            self.assertEqual((out/'song.flac').read_bytes(), b'unrelated')
            self.assertEqual(new.path.name, 'song (2).flac')
            self.assertFalse(list(out.glob('*.part')))

    def test_unicode_filename_bytes_and_invalid_track_type(self):
        self.assertLessEqual(len(m.safe_name('☀️' * 130).encode('utf-8')), 200)
        with self.assertRaisesRegex(m.LucidaError, 'unsupported item type'):
            m.tracks_from_page({'tokenExpiry':1, 'info':{'type':'artist', 'csrf':'x', 'url':'https://play.qobuz.com/track/1'}})
        with self.assertRaisesRegex(m.LucidaError, 'invalid track listing'):
            m.tracks_from_page({'tokenExpiry':1, 'info':{'type':'album', 'tracks':'not-a-list'}})

    def test_mime_extension_disagreement_is_corrected(self):
        c=m.Client()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(c, 'request', return_value=FakeResponse(b'fLaC'+b'payload', {'Content-Type':'audio/flac', 'Content-Disposition':'attachment; filename="Song.mp3"'})):
                result=c.download('https://x.lucida.to/api/fetch/request/abc', Path(tmp), 'Song')
            self.assertEqual(result.path.name, 'Song.flac')

    def test_no_retry_for_api_post(self):
        c = m.Client()
        count = []
        def failing(req, timeout):
            count.append(req)
            raise OSError('network down')
        c.opener.open = failing
        with patch.object(m.time, 'sleep'):
            with self.assertRaises(m.LucidaError):
                c.request('POST', 'https://lucida.to/api/load', {'a':1})
        self.assertEqual(len(count), 1)

    def test_full_synthetic_track_pipeline(self):
        fake_url = 'https://play.qobuz.com/track/42'
        page = {"info": {"type":"track", "url":fake_url, "title":"My Song", "artists":[{"name":"Someone"}],"csrf":"abc"}, "tokenExpiry":123}
        payload = ',{"type":"data","data":'+json.dumps(page)+',"uses":{"url":1}}];'
        c = m.Client()
        requests = []
        def serve(method, url, data=None, stream=False, attempts=3):
            requests.append((method,url,data,stream))
            if method=='GET' and '?url=' in url: return '<script>'+payload+'</script>'
            if method=='POST': return json.dumps({'server':'edge-1','handoff':'task123'})
            if url.endswith('/download'):
                return FakeResponse(b'fLaC'+b'payload', {'Content-Type':'audio/flac', 'Content-Length':'11'})
            if method=='GET' and '/api/fetch/request/' in url:
                return '{"status":"completed"}'
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as tmp:
            args=m.build_parser().parse_args(['download',fake_url,'--output',tmp])
            with patch.object(c, 'request', side_effect=serve):
                self.assertTrue(m.download_input(c, fake_url, args))
            self.assertEqual((Path(tmp)/'Someone'/'Singles'/'My Song.flac').read_bytes(), b'fLaCpayload')
        self.assertEqual([call[0] for call in requests], ['GET','POST','GET','GET'])


if __name__ == '__main__':
    unittest.main()
