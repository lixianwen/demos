import logging

import aiohttp
from aiohttp import web
from faker import Faker


log = logging.getLogger(__name__)

fake = Faker()

async def index(request):
    ws_current = web.WebSocketResponse()
    ws_ready = ws_current.can_prepare(request)
    if not ws_ready.ok:
        return web.json_response({'error': 'Sorry, can not establish a websocket connection.'})
    await ws_current.prepare(request)

    name = fake.name()
    log.info(f'{name} joined.')

    await ws_current.send_json({'action': 'connect', 'name': name})

    for ws in request.app['websockets'].values():
        await ws.send_json({'action': 'join', 'name': name})
    request.app['websockets'][name] = ws_current

    async for msg in ws_current:
        if msg.type == aiohttp.WSMsgType.TEXT:
            for ws in request.app['websockets'].values():
                if ws is not ws_current:
                    await ws.send_json({'action': 'sent', 'name': name, 'text': msg.data})
        elif msg.type == aiohttp.WSMsgType.ERROR:
            log.error('ws connection closed with exception %s', ws_current.exception())

    del request.app['websockets'][name]
    log.info(f'{name} disconnected.')
    for ws in request.app['websockets'].values():
        await ws.send_json({'action': 'disconnect', 'name': name})

    log.info('websocket connection closed')

    return ws_current
