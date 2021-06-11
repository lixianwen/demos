import sys
import asyncio
from urllib.parse import urljoin

import aiohttp
import motor.motor_asyncio

PROJECT = {
    'a': 'a',
    'b': 'b',
    'c': 'b',
    'd': 'd'
}

JenkinsAuth = ('admin', '123456')

JenkinsBaseURL = 'http://192.168.1.2:51908/job/'

session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(*JenkinsAuth))

async def get_migrate_info(project: str, zid: int):
    db = client.get_default_database()
    migrate_info = []

    minion_cursor = db.minion.find(
        {'cap': 0, 'status': 'enabled', 'group': {'$ne': 'other'}},
        projection={'_id': 0, 'name': 1}
    )
    async for name in minion_cursor:
        gamesvr_cursor = db.gamesvr.find(
            {'project': project, 'zid': int(zid), 'minion_name': name['name'], 'status': 'enabled'},
            projection={'_id': 0, 'project': 1, 'zid': 1, 'sid': 1}
        )
        async for game in gamesvr_cursor:
            migrate_info.append(game)

    return migrate_info


async def build_job(**kwargs: dict):
    """Access remote API to build the migrate job.

    key in param `kwargs` as follow:

    :key project: 项目名称
    :key zid: 项目ID
    :key sid:: 游戏服ID
    """
    async with session.post(urljoin(JenkinsBaseURL, f"{kwargs['project']}_auto_migrate_gamesvr_ops/buildWithParameters"), data=kwargs) as resp:
        print(f"服ID: {kwargs['sid']} 的提交状态: {resp.status}")


def get_mongodb_url(project: str) -> str:
    try:
        project = PROJECT[project]
    except KeyError:
        raise KeyError(f'没有此项目：{project}')

    return f'mongodb://{project}_readwrite:123456@192.168.1.2:27017/{project}-local-test?authSource=admin'


async def main(project: str, zid: int):
    try:
        migrate_info = await get_migrate_info(project, zid)
        if migrate_info:
            tasks = [build_job(**info) for info in migrate_info]
            await asyncio.gather(*tasks)
        else:
            print('没有待迁移的游戏服')
    finally:
        await session.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: python3.6 {__file__} project_id zone_id')
        sys.exit(1)

    client = motor.motor_asyncio.AsyncIOMotorClient(get_mongodb_url(sys.argv[1]))

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main(*sys.argv[1:]))
    finally:
        loop.close()
