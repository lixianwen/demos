import errno
import io
import logging
import os
import re
import selectors
import stat
import warnings
import getpass
import shutil
from typing import List, Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

DEFAULT_LANG = 'en_US.UTF-8'

CMD_TIMEOUT = 10.0

SUPPORTED_ENCRYPTION_ALGORITHM = {
    "DSA": paramiko.DSSKey,
    "DSS": paramiko.DSSKey,
    "RSA": paramiko.RSAKey,
    "ECDSA": paramiko.ECDSAKey,
    "ED25519": paramiko.Ed25519Key,
}


def create_pkey(
    plain_text: str, tag: str = "RSA", passphrase: Optional[str] = None
) -> paramiko.PKey:
    """Instantiate `paramiko.PKey` for key authentication

    :param plain_text: private key text
    :param tag: encrypt type
    :param passphrase: password for private key
    """
    tag = tag.upper()
    try:
        cls = SUPPORTED_ENCRYPTION_ALGORITHM[tag]
    except KeyError:
        raise ValueError(f"Unsupported encrypt algorithm {tag}")

    return cls(file_obj=io.StringIO(plain_text), password=passphrase)


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
        cmd_timeout: Optional[float] = None,
        **connect_kwargs,
    ) -> None:
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

        >>> private_key = 'ssh-rsa ...'
        >>> pkey = create_pkey(private_key)
        >>> with SSHClientWithReturnCode(hostname='a', username='b', pkey=pkey) as client:
        >>>     c, s, f = client.run('w')
        >>>     assert c == 0
        """
        self.duration = duration
        if self.duration is not None:
            # unhandled convert error, just raise it
            self.duration = float(self.duration)
            if self.duration <= 0:
                raise ValueError(f'{duration} must be a float number and it grater then zero')

        if timeout is not None:
            timeout = float(timeout)

        self.cmd_timeout = cmd_timeout
        if self.cmd_timeout is None:
           self.cmd_timeout = timeout if timeout else CMD_TIMEOUT

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

        # SFTP client object
        self._sftp: Optional[paramiko.SFTPClient] = None

    def _read_buffer(self, channel: paramiko.Channel, mask: int) -> None:
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
                fd_list: List[Tuple[selectors.SelectorKey, int]] = self.sel.select(self.cmd_timeout)
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
            code = channel.recv_exit_status()

            return code, success, failed
        finally:
            self.sel.unregister(channel)
            channel.close()
            stdout.close()
            stderr.close()
            self.stdout_chunks = b''
            self.stderr_chunks = b''

    def close(self) -> None:
        self.sel.close()
        self.client.close()

        if self._sftp is not None:
            self._sftp.close()

    @property
    def sftp(self) -> paramiko.SFTPClient:
        """Return a `~paramiko.sftp_client.SFTPClient` object.

        If called more than one time, memoizes the first result; thus, any
        given `.Connection` instance will only ever have a single SFTP client,
        and state (such as that managed by
        `~paramiko.sftp_client.SFTPClient.chdir`) will be preserved.

        Thanks for :library:`fabric`
        """
        if self._sftp is None:
            self._sftp = self.client.open_sftp()

        return self._sftp

    def put(
        self,
        local: str,
        remote: str,
        preserve_mode: bool = True,
        sudo: bool = False,
    ) -> None:
        """Upload file to remote server

        :param local: File to upload. It can be a relative path or absolute path.
        :param remote: Where the file upload to. Only accept an absolute path.
        :param preserve_mode: Preserve file mode or not on remote server.
        :param sudo: Whether to use sudo mechanism when upload wasn't granted or not
        """
        if hasattr(local, "write") and callable(getattr(local, "write")):
            raise ValueError("Don't support file like object")
        if not os.path.isabs(local):
            local = os.path.abspath(local)
        if not os.path.exists(local):
            raise FileNotFoundError(
                errno.ENOENT, f"No such file or directory: {local!r}"
            )
        if not os.path.isfile(local):
            raise ValueError(f"{local!r} isn't a file")

        sftp = self.sftp

        local_base = os.path.basename(local)
        if not remote:
            raise ValueError(f"No allow empty remote: {remote!r}")
        elif not os.path.isabs(remote):
            raise ValueError(f"Remote must be absolute path, got {remote!r}")

        try:
            remote_st_mode = sftp.stat(remote).st_mode
            assert remote_st_mode is not None
            if stat.S_ISDIR(remote_st_mode):
                remote = os.path.join(remote, local_base)
        except FileNotFoundError:
            remote_dirname = os.path.dirname(remote)
            if remote_dirname == "/":
                raise FileNotFoundError(
                    errno.ENOENT, f"No such file or directory: {remote!r}"
                )

            # May be its dirname exist, try again
            sftp.stat(remote_dirname)
        except PermissionError:
            if sudo:
                remote_is_dir, _, _ = self.run(f"sudo [ -d {remote} ]")
                if remote_is_dir == 0:
                    remote = os.path.join(remote, local_base)
                else:
                    remote_dirname = os.path.dirname(remote)
                    remote_is_dir, _, _ = self.run(f"sudo [ -d {remote_dirname} ]")
                    assert (
                        remote_is_dir == 0
                    ), f"{remote_dirname!r} not exist or not a directory"
            else:
                raise

        try:
            sftp.stat(remote)
            logger.warning(
                f"File {remote!r} exist on remote server, default to rewrite it."
            )
        except (FileNotFoundError, PermissionError):
            pass

        try:
            logger.info(f"Uploading {local!r} to {remote!r}")
            sftp.put(localpath=local, remotepath=remote)
        except PermissionError:
            remote_basename = os.path.basename(remote)
            tmp_remote = os.path.join("/tmp", remote_basename)
            logger.info(f"Uploading {local!r} to {tmp_remote!r}")
            sftp.put(localpath=local, remotepath=tmp_remote)

            logger.info(f"Moving {tmp_remote} to {remote}")
            code_mv, _, failure_mv = self.run(f"sudo mv {tmp_remote} {remote}")
            if code_mv:
                raise RuntimeError(f"Upload failed: {failure_mv!r}")  # pragma: nocover

        # Set mode to same as local end
        if preserve_mode:
            local_mode = os.stat(local).st_mode
            mode = stat.S_IMODE(local_mode)
            try:
                # Expect *NOT* raise :exc:`FileNotFoundError` here
                sftp.chmod(remote, mode)
            except PermissionError:
                code_chmod, _, failure_chmod = self.run(f"sudo chmod {mode:o} {remote}")
                if code_chmod:
                    raise RuntimeError(
                        f"Change mode failed: {failure_chmod!r}"
                    )  # pragma: nocover

    def get(
        self,
        remote: str,
        local: str,
        preserve_mode: bool = True,
        sudo: bool = False,
    ) -> None:
        """Download file from remote server

        :param remote: File to download. Only accept an absolute path.
        :param local: Path to save file. It can be a relative path or absolute path.
        :param preserve_mode: Preserve file mode or not.
        :param sudo: Whether to use sudo mechanism when download wasn't granted or not
        """
        sftp = self.sftp

        if not remote:
            raise ValueError(f"No allow empty remote: {remote!r}")
        elif not os.path.isabs(remote):
            raise ValueError(f"Remote must be absolute path, got {remote!r}")
        try:
            remote_st_mode = sftp.stat(remote).st_mode
            assert remote_st_mode is not None
            if stat.S_ISDIR(remote_st_mode):
                raise ValueError(f"Remote must be a file, got {remote!r}")
        except PermissionError:
            if sudo:
                code_valid_remote, _, _ = self.run(f"sudo [ -f {remote} ]")
                assert code_valid_remote == 0, "Remote not exist or not a file"
            else:
                raise

        if not local:
            raise ValueError(f"No allow empty local: {local!r}")
        if not os.path.isabs(local):
            local = os.path.abspath(local)
        try:
            if stat.S_ISDIR(os.stat(local).st_mode):
                raise ValueError(f"Expect file path, got directory: {local!r}")
        except FileNotFoundError:
            dirname, basename = os.path.split(local.rstrip(os.sep))
            stat.S_ISDIR(os.stat(dirname).st_mode)

        try:
            os.stat(local)
            logger.warning(
                f"File {local!r} exist on local server, default to rewrite it."
            )
        except FileNotFoundError:
            pass

        try:
            logger.info(f"Pulling down {remote!r} and save it to {local!r}")
            sftp.get(remotepath=remote, localpath=local)
        except PermissionError:
            code_cp, _, failure_cp = self.run(f"sudo cp {remote} /tmp")
            if code_cp:
                raise RuntimeError(failure_cp)  # pragma: nocover

            code_who, success_who, failure_who = self.run("whoami")
            if code_who:
                raise RuntimeError(failure_who)  # pragma: nocover
            username = success_who.strip()

            tmp_remote = os.path.join("/tmp", os.path.basename(remote))
            code_chown, _, failure_chown = self.run(
                f"sudo [ -f {tmp_remote} ] && sudo chown {username}:{username} {tmp_remote}"
            )
            if code_chown:
                raise RuntimeError(failure_chown)  # pragma: nocover

            logger.info(f"Pulling down {tmp_remote!r} and save it to {local!r}")
            sftp.get(remotepath=tmp_remote, localpath=local)
            sftp.remove(tmp_remote)

        # Set mode to same as remote
        if preserve_mode:
            try:
                remote_mode = sftp.stat(remote).st_mode
                assert remote_mode is not None
                mode = stat.S_IMODE(remote_mode)
            except PermissionError:
                code_stat, success_stat, failure_stat = self.run(f"sudo stat {remote}")
                if code_stat:
                    raise RuntimeError(failure_stat)  # pragma: nocover
                re_mode = re.compile(r"Access: \((\d+).*\)  Uid")
                match_mode = re_mode.search(success_stat)
                if match_mode is None:
                    raise ValueError("Can not match mode.")
                mode = int(match_mode.group(1).strip(), 8)

            # Expect *NOT* raise :exc:`FileNotFoundError` here
            os.chmod(local, mode)
            current_user = getpass.getuser()
            shutil.chown(local, current_user, current_user)
