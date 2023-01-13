import os
from typing import Union
from pathlib import PurePath, PurePosixPath


def remove_first_part(path: Union[str, PurePath]) -> str:
    try:
        new_path = path.relative_to(*(path.parts[:2])).as_posix()
    except AttributeError:
        new_path = remove_first_part(PurePosixPath(path))

    return new_path


def remove_first_part_v2(path: str) -> str:
    return os.path.join(*(path.split(os.sep)[2:]))


def test_remove_first_part():
    p1 = '/opt/lua-1.0/fixed/lua.c'
    assert remove_first_part(p1) == 'lua-1.0/fixed/lua.c'

    p2 = PurePosixPath(p1)
    assert remove_first_part(p2) == 'lua-1.0/fixed/lua.c'


def test_remove_first_part_v2():
    p1 = '/opt/lua-1.0/fixed/lua.c'
    assert remove_first_part_v2(p1) == 'lua-1.0/fixed/lua.c'

