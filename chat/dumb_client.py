import asyncio
import time
from functools import partial
import json

import aiohttp


def log(prompt: str, text: str):
    date_prompt = f"({time.strftime('%H:%M:%S')})"
    print(date_prompt, f'{prompt} {text}')

ACTION = {
    'connect': partial(log, 'Connected as'),
    'disconnect': partial(log, 'Disconnected'),
    'join': partial(log, 'Joined'),
    'sent': log
}

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8080') as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    action = data['action']
                    if action == 'sent':
                        log(data['name'] + ': ', data['text'])
                    else:
                        ACTION[action](data['name'])
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
