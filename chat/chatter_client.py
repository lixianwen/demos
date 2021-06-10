import asyncio

import aiohttp


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8080') as ws:
            while True:
                msg = input('Please enter something: ')
                if not msg:
                    break
                await ws.send_str(msg)

            print('Client side connection closed')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
