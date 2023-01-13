import logging
import selectors
import warnings
from typing import Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

DEFAULT_LANG = 'en_US.UTF-8'


class SSHClientWithReturnCode:
    """A ssh client wrapper for execute command at remote server, get the return code and output stream without hangs.

    reference: https://github.com/paramiko/paramiko/issues/563
               https://stackoverflow.com/questions/23504126/do-you-have-to-check-exit-status-ready-if-you-are-going-to-check-recv-ready
    """

    def __init__(
        self,
        *,
        hostname: str,
        port: int = 22,
        username: str,
        password: Optional[str] = None,
        duration: Optional[float] = None,
        timeout: Optional[float] = None,
        **connect_kwargs,
    ):
        """
        :param hostname: hostname – the server to connect to
        :param port: port – the server port to connect to
        :param username: username – the username to authenticate as
        :param password: password – Used for password authentication
        :param float duration: duration option (in seconds) for shell command `timeout`
        :param float timeout: an optional timeout (in seconds) for the TCP connect
        :param connect_kwargs: additional params pass to `paramiko.client.SSHClient.connect`

        >>> with SSHClientWithReturnCode(hostname='a', username='b', password='c') as client:
        >>>     c, s, f = client.run('[[ -f /home/airflow/dags/restore.py ]]')
        >>>     assert c == 0
        """
        self.duration = duration
        if self.duration is not None:
            # unhandled convert error, just raise it
            self.duration = float(duration)
            if self.duration <= 0:
                raise ValueError(f'{duration} must be a float number and it grater then zero')

        if timeout is not None:
            timeout = float(timeout)

        self.client = paramiko.client.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        # probably raise exception `socket.timeout`
        self.client.connect(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            **connect_kwargs,
        )

        self.sel = selectors.DefaultSelector()

        self.stdout_chunks = b''
        self.stderr_chunks = b''

    def _read_buffer(self, channel, mask):
        """A callback will be called when the `channel` is ready.

        :param channel: A file object for selection, monitoring it for I/O events
        :param mask: A bitwise mask of events to monitor
        """
        if channel.recv_ready():
            self.stdout_chunks += channel.recv(len(channel.in_buffer))
        if channel.recv_stderr_ready():
            self.stderr_chunks += channel.recv_stderr(len(channel.in_stderr_buffer))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def run(self, cmd: str, **kwargs) -> Tuple[int, str, str]:
        """Execute a command.

        :param cmd: command executing on remote server
        :param kwargs: additional params pass to `paramiko.client.SSHClient.exec_command`
        :returns: the return code, stdout and stderr of the executing command, as a 3-tuple
        """
        logger.info(f'Running command: {cmd!r}')

        if self.duration:
            cmd = f'timeout {self.duration} {cmd}'

        if 'environment' not in kwargs:
            kwargs['environment'] = {'LANG': DEFAULT_LANG}
        elif 'LANG' not in kwargs['environment']:
            # kwargs['environment'] may not be a mapping
            kwargs['environment']['LANG'] = DEFAULT_LANG

        if '|' in cmd:
            warnings.warn(f'Pipe in command: {cmd}, exit code determined by the last command', SyntaxWarning)

        # one channel per command
        stdin, stdout, stderr = self.client.exec_command(cmd, **kwargs)
        # we do not need stdin.
        stdin.close()
        # get the shared channel for stdin/stdout/stderr
        channel = stdout.channel
        # indicate that we are not going to write to that channel any more.
        channel.shutdown_write()
        self.sel.register(channel, selectors.EVENT_READ, self._read_buffer)

        # capture any initial output in case channel is closed already
        stdout_buffer_length = len(stdout.channel.in_buffer)

        if stdout_buffer_length > 0:
            self.stdout_chunks += stdout.channel.recv(stdout_buffer_length)

        try:
            # read stdout/stderr in order to prevent read block hangs
            while not channel.closed or channel.recv_ready() or channel.recv_stderr_ready():
                fd_list = self.sel.select()
                for key, events in fd_list:
                    callback = key.data
                    callback(key.fileobj, events)

                # if no data arrived in the last loop, check if we already received the exit code
                # if input buffers are empty
                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    # indicate that we are not going to read this channel any more
                    channel.shutdown_read()
                    # exit as remote side is finished and our buffer are empty
                    break

            success = self.stdout_chunks.decode('utf-8', 'ignore')
            failed = self.stderr_chunks.decode('utf-8', 'ignore')
            # return code is always ready at this point
            errno = channel.recv_exit_status()

            return errno, success, failed
        finally:
            self.sel.unregister(channel)
            channel.close()
            stdout.close()
            stderr.close()
            self.stdout_chunks = b''
            self.stderr_chunks = b''

    def close(self):
        self.sel.close()
        self.client.close()
