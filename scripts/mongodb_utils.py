#!/usr/bin/env python

import os
import shutil
import shlex
import subprocess
import datetime
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure


class MongoDBUtil:
    def __init__(self, uri: str):
        self.uri = uri
        self.client = MongoClient(self.uri, connect=False)
        self.default_db = self.client.get_default_database()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()
    
    @property
    def is_alived(self):
        try:
            # The ismaster command is cheap and does not require auth.
            self.client.admin.command('ismaster')
            return True
        except (ConnectionFailure, OperationFailure):
            return False

    @property
    def authenticated(self):
        try:
            self.client.list_database_names()
            return True
        except OperationFailure:
            return False

    def backup(self):
        database = self.client.get_default_database().name
        mongodump = shutil.which('mongodump')
        now = datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        cmd = f'{mongodump} --uri {self.uri} --gzip --archive=./{database}_{now}.gz'
        print('cmd', cmd)
        try: 
            cp = subprocess.run(
                shlex.split(cmd),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8'
            ) 
            print(cp.stderr) # 子进程的输出流被stderr捕获，即使设置了stdout，原因未知，其他命令正常
        except subprocess.CalledProcessError as e: 
            print(f'Calling command: {e.cmd} failed. Error output: {e.stderr}')

    def restore(self, archive: str, nsFrom: str = None, nsTo: str = None):
        """
        :param archive: 用于恢复数据库的存档文件名
        :param nsFrom: 源数据库名称。默认为`archive`中指定的数据库名
        :param nsTo: 目标数据库名称
        """
        assert os.path.exists(archive), f'脚本当前目录下没有文件：{archive}'
        mongorestore = shutil.which('mongorestore')
        if nsFrom is not None and nsTo is not None:
            cmd = f'{mongorestore} --uri {self.uri} --gzip --drop --archive={archive} --nsFrom={nsFrom}.* --nsTo={nsTo}.*'
        else:
            cmd = f'{mongorestore} --uri {self.uri} --gzip --drop --archive={archive}'
        print('cmd', cmd)
        try: 
            cp = subprocess.run(
                shlex.split(cmd),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8'
            ) 
            print(cp.stderr) # 子进程的输出流被stderr捕获，即使设置了stdout，原因未知，其他命令正常
        except subprocess.CalledProcessError as e: 
            print(f'Calling command: {e.cmd} failed. Error output: {e.stderr}')


def backup(args: dict):
    """
    :param args: 命令行参数及其值
    """
    with MongoDBUtil(args['uri']) as mongodbUtil:
        if mongodbUtil.is_alived and mongodbUtil.authenticated:
            print(mongodbUtil.backup())
        else:
            print('连不上MongoDB或者认证失败')


def restore(args: dict):
    """
    :param args: 命令行参数及其值
    """
    data = dict(args)
    uri = data.pop('uri')
    with MongoDBUtil(uri) as mongodbUtil:
        if mongodbUtil.is_alived and mongodbUtil.authenticated:
            print(mongodbUtil.restore(**data))
        else:
            print('连不上MongoDB或者认证失败')


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    parser_backup = subparsers.add_parser('backup', help='备份数据库')
    parser_backup.add_argument('uri', help='需要备份的数据库作为默认数据库的uri')
    parser_backup.set_defaults(func=backup)

    parser_restore = subparsers.add_parser('restore', help='恢复数据库')
    parser_restore.add_argument('uri')
    parser_restore.add_argument('archive', help='备份文件名称')
    parser_restore.add_argument('--from', dest='nsFrom', help='源数据库名称')
    parser_restore.add_argument('--to', dest='nsTo', help='目标数据库名称')
    parser_restore.set_defaults(func=restore)

    args = parser.parse_args()
    try:
        data = vars(args)
        data.pop('func')(data)
    except KeyError:
        parser.print_help()
