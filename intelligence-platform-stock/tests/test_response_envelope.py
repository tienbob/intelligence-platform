"""Exercise the real ASGI boundary, including streaming and duplicate headers."""
import json
import pytest
from app.core.response_envelope import ResponseEnvelopeMiddleware


async def respond(body, *, status=200, headers=None, path='/example', method='GET'):
    emitted = []
    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': status, 'headers': headers or [
            (b'content-type', b'application/json'), (b'content-length', str(len(body)).encode()),
            (b'set-cookie', b'a=1'), (b'set-cookie', b'b=2')]})
        midpoint = len(body) // 2
        await send({'type': 'http.response.body', 'body': body[:midpoint], 'more_body': True})
        await send({'type': 'http.response.body', 'body': body[midpoint:], 'more_body': False})
    async def send(message):
        emitted.append(message)
    await ResponseEnvelopeMiddleware(app)({'type': 'http', 'path': path, 'method': method}, None, send)
    return emitted


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'{broken', b'', b'\xff'])
async def test_invalid_json_keeps_original_body_and_headers(body):
    messages = await respond(body)
    assert messages[1]['body'] == body
    assert (b'content-length', str(len(body)).encode()) in messages[0]['headers']


@pytest.mark.asyncio
async def test_chunked_json_wrapped_once_and_duplicate_cookies_preserved():
    messages = await respond(b'{"name":"test"}')
    assert json.loads(messages[1]['body'])['data'] == {'name': 'test'}
    assert [v for k, v in messages[0]['headers'] if k == b'set-cookie'] == [b'a=1', b'b=2']
    assert int(dict(messages[0]['headers'])[b'content-length']) == len(messages[1]['body'])


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'"denied"', b'["denied"]', b'{"detail":[{"msg":"required"}]}'])
async def test_error_json_shapes_do_not_crash(body):
    messages = await respond(body, status=422)
    assert json.loads(messages[1]['body'])['error']['code'] == '422'


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [
    {'path': '/health/ready'}, {'method': 'HEAD'}, {'status': 204},
    {'headers': [(b'content-type', b'text/event-stream')]},
    {'headers': [(b'content-type', b'application/json'), (b'content-encoding', b'gzip')]},
])
async def test_excluded_and_streaming_responses_pass_through(options):
    messages = await respond(b'example', **options)
    assert len(messages) == 3
    assert b''.join(m.get('body', b'') for m in messages) == b'example'
