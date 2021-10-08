import os
import sys
import time
import signal
import multiprocessing
from functools import wraps
from typing import Callable, NoReturn


class TimeoutException(Exception):
    pass


def timeout(number: int, use_signal: bool = True):
    def wrapper(func: Callable):
        @wraps(func)
        def inner(*args, **kwargs):
            if use_signal:
                def handler(signum, frame) -> NoReturn:
                    raise TimeoutException(f'TimeoutException thrown out after {number} seconds')

                old_handler = signal.signal(signal.SIGALRM, handler)
                signal.alarm(number)
    
                try:
                    return func(*args, **kwargs)
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            else:
                timeout_wrapper = TimeOut(func, number)
                return timeout_wrapper(*args, **kwargs)

        return inner

    return wrapper


def worker(q, func, *args, **kwargs):
    try:
        q.put((True, func(*args, **kwargs)))
    except:
        q.put((False, sys.exc_info()[1]))
    finally:
        q.close()


class TimeOut:
    def __init__(self, func, number):
        self.func = func
        self.number = number
        self.timeout = number + time.time()
        self._queue = multiprocessing.Queue(1)

    def __call__(self, *args, **kwargs):
        self.process = multiprocessing.Process(
            target=worker,
            args=(self._queue, self.func) + args,
            kwargs=kwargs,
            daemon=False
        )
        self.process.start()

        while self.timeout > time.time():
            if self._queue.full():
                flag, result_or_exception_instance = self._queue.get()
                self.process.join()
                if flag:
                    return result_or_exception_instance
                raise result_or_exception_instance
        else:    # timeout
            self.process.terminate()
            self.process.join()
            raise TimeoutException(f'TimeoutException thrown out after {self.number} seconds')

