import logging

from aiohttp import web, WSCloseCode

from views import index


async def init_app():
    app = web.Application()

    app['websockets'] = {}

    app.on_shutdown.append(shutdown)

    app.router.add_get('/', index)

    return app


async def shutdown(app):
    for ws in app['websockets'].values():
        await ws.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')
    app['websockets'].clear()


def main():
    logging.basicConfig(level=logging.DEBUG)

    app = init_app()
    web.run_app(app)   


if __name__ == '__main__':
    main()
