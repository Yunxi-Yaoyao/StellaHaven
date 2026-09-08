import asyncio
from starlette.requests import Request
from starlette.responses import Response
from main import assets_cache_control


def test_background_range_and_validation_responses_keep_browser_cache():
    for status in (200, 206, 304):
        request = Request({'type': 'http', 'method': 'GET', 'path': '/assets/homebg/test.mp4', 'headers': []})
        async def respond(_):
            return Response(status_code=status, headers={'Content-Range': 'bytes 0-9/100'} if status == 206 else {})
        response = asyncio.run(assets_cache_control(request, respond))
        assert response.headers.get('cache-control') == 'public, max-age=604800, immutable', status
        if status == 206:
            assert response.headers['content-range'] == 'bytes 0-9/100'


def test_private_and_failed_responses_do_not_get_public_cache():
    for path, status in (('/auth/me', 200), ('/assets/missing.mp4', 404), ('/homebg/media', 200)):
        request = Request({'type': 'http', 'method': 'GET', 'path': path, 'headers': []})
        async def respond(_): return Response(status_code=status)
        response = asyncio.run(assets_cache_control(request, respond))
        assert 'cache-control' not in response.headers
