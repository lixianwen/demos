import selectors

import paramiko


class SSHClientWithReturnCode:
    """一个用于 ssh 到远程服务器执行命令并获取返回值和 return code 的类

    参考：https://github.com/paramiko/paramiko/issues/563
         https://stackoverflow.com/questions/23504126/do-you-have-to-check-exit-status-ready-if-you-are-going-to-check-recv-ready
    """
    def __init__(self, *, hostname: str, port: int = 22, username: str, password: str, duration: float = None, timeout: float = None, **kwargs):
        """
        :param hostname: hostname – the server to connect to
        :param port: port – the server port to connect to
        :param username: username – the username to authenticate as
        :param password: password – Used for password authentication
        :param duration: duration option (in seconds) for shell command `timeout`
        :param timeout: an optional timeout (in seconds) for the TCP connect
        :param kwargs: additional params pass to `paramiko.client.SSHClient.connect`
        """
        self.sel = selectors.DefaultSelector()

        self.client = paramiko.client.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        try:
            self.client.connect(hostname, port, username, password, timeout=timeout, **kwargs)
        except Exception as err:
            raise ConnectionError(str(err))

        self.duration = duration
        if self.duration is not None:
            if float(duration) <= 0:
                raise ValueError(f'{duration} must be a floating point number and grater then zero')
            else:
                self.duration = float(duration)

        self.stdout_chunks = []
        self.stderr_chunks = []
        self.got_chunk = False

    def _read_buffer(self, channel, mask):
        """A callback will be called when the `channel` is ready
        :param channel: A file object for selection, monitoring it for I/O events
        :param mask: A bitwise mask of events to monitor
        """
        if channel.recv_ready():
            self.stdout_chunks.append(channel.recv(len(channel.in_buffer)))
            self.got_chunk = True
        if channel.recv_stderr_ready():
            self.stderr_chunks.append(channel.recv_stderr(len(channel.in_stderr_buffer)))
            self.got_chunk = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sel.close()
        self.client.close()

        if exc_val:
            raise exc_val

    def run(self, cmd: str):
        """
        :param cmd: command executing on remote server
        :returns: the stdout, stderr, and return code of the executing command, as a 3-tuple
        """
        if self.duration:
            cmd = f'timeout {self.duration} {cmd}'

        # one channel per command
        stdin, stdout, stderr = self.client.exec_command(cmd)
        # we do not need stdin.
        stdin.close()
        # get the shared channel for stdin/stdout/stderr
        channel = stdout.channel
        # indicate that we are not going to write to that channel any more.
        channel.shutdown_write()
        self.sel.register(channel, selectors.EVENT_READ, self._read_buffer)

        self.stdout_chunks.append(channel.recv(len(channel.in_buffer)))
        # self.stderr_chunks.append(channel.recv_stderr(len(channel.in_stderr_buffer)))

        # read stdout/stderr in order to prevent read block hangs
        while not channel.closed or channel.recv_ready() or channel.recv_stderr_ready():
            self.got_chunk = False

            fd_list = self.sel.select()
            for key, events in fd_list:
                callback = key.data
                callback(key.fileobj, events)

            # if no data arrived in the last loop, check if we already received the exit code
            # if input buffers are empty
            if (
                not self.got_chunk
                and channel.exit_status_ready()
                and not channel.recv_ready()
                and not channel.recv_stderr_ready()
            ):
                # indicate that we are not going to read this channel any more
                channel.shutdown_read()
                channel.close()
                # exit as remote side is finished and our buffer are empty
                break

        stdout.close()
        stderr.close()

        success = ''.join([s.decode('utf-8', 'ignore') for s in self.stdout_chunks])
        failed = ''.join([s.decode('utf-8', 'ignore') for s in self.stderr_chunks])
        # return code is always ready at this point
        returncode = channel.recv_exit_status()

        return success, failed, returncode

