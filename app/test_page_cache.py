"""The page files are revalidated on every load, so an update is never hidden by a cached older copy."""
import asyncio
import unittest

import app as studio


def get(path):
    sent = []
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method='GET', scheme='http',
                 path=path, raw_path=path.encode(), query_string=b'', root_path='',
                 client=('127.0.0.1', 50000), server=('127.0.0.1', 7863),
                 headers=[(b'host', b'127.0.0.1')])

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message):
        sent.append(message)
    asyncio.run(studio.app(scope, receive, send))
    start = next(message for message in sent if message['type'] == 'http.response.start')
    return start['status'], {key.decode().lower(): value.decode() for key, value in start['headers']}


class PageCacheTests(unittest.TestCase):
    def test_page_scripts_and_styles_must_be_revalidated(self):
        for path in ('/', '/app.js', '/style.css'):
            status, headers = get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers.get('cache-control'), 'no-cache', path)
            self.assertIn('etag', headers, path)


if __name__ == '__main__':
    unittest.main()
