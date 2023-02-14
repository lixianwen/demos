import concurrent.futures
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import warnings

import paramiko
import pytest

from demos.socket.ssh import SSHClientWithReturnCode, create_pkey

HOST = "openssh-server"
PASSWORDLESS_SUDO_HOST = "openssh-server-passwordless-sudo"
USER = "user"
PWD = "passwd"
PORT = 2222
PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
..."""

PRIVATE_KEY_WITH_PASSWORD = """-----BEGIN RSA PRIVATE KEY-----
..."""


def test_huge_output_command():
    # arrange
    client = SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT)

    # act
    errno, stdout, stderr = client.run("ls -lshAR -h /etc/ssl/certs")

    # assert
    assert errno == 0


def test_small_output_command():
    # arrange
    client = SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT)

    # act
    errno, stdout, stderr = client.run("whoami")

    # assert
    assert stdout.strip() == "user"
    assert errno == 0
    assert not stderr


def test_run_failed_command():
    # arrange
    client = SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT)

    # act
    errno, stdout, stderr = client.run("ls not_exist_file")

    # assert
    assert errno == 2


def test_timeout_command_work():
    # arrange
    client = SSHClientWithReturnCode(
        hostname=HOST, username=USER, password=PWD, port=PORT, timeout=1
    )

    # act
    command = 'curl --limit-rate 1 -L "https://baidu.com" -o /tmp/baidu.com'
    client.duration = 4
    errno, stdout, stderr = client.run(command)

    # assert
    assert errno == 124


def test_duration():
    with pytest.raises(ValueError):
        SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT, duration=-1)


def test_run_multi_command_within_context():
    with SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT) as client:
        errno1, stdout1, stderr1 = client.run("uname -s")
        errno2, stdout2, stderr2 = client.run("whoami")

        assert errno1 == errno2 == 0
        assert stdout1 == "Linux\n"
        assert stdout2 == "user\n"
        assert not stderr1
        assert not stderr2


def test_missing_lang_parameter():
    with SSHClientWithReturnCode(hostname=HOST, username=USER, password=PWD, port=PORT) as client:
        errno, stdout, stderr = client.run("uname -s", environment={})

        assert errno == 0
        assert stdout == "Linux\n"
        assert not stderr


def test_create_rsa_pkey():
    pkey = create_pkey(PRIVATE_KEY)
    assert isinstance(pkey, paramiko.RSAKey)


def test_create_rsa_pkey_with_password():
    pkey = create_pkey(PRIVATE_KEY_WITH_PASSWORD, passphrase="123456")
    assert isinstance(pkey, paramiko.RSAKey)


def test_create_rsa_pkey_failed():
    with pytest.raises(ValueError):
        _ = create_pkey(PRIVATE_KEY, tag="aes")


def test_login_with_pkey():
    with SSHClientWithReturnCode(
        hostname=HOST, port=PORT, username=USER, pkey=create_pkey(PRIVATE_KEY)
    ) as client:
        code, _, _ = client.run("w")

        assert code == 0


def test_warning_command():
    with warnings.catch_warnings(record=True) as w:
        cmd = "du /config | sort -rn |head -n1"
        with SSHClientWithReturnCode(
            hostname=HOST, port=PORT, username=USER, pkey=create_pkey(PRIVATE_KEY)
        ) as client:
            code, _, _ = client.run(cmd)

            assert code == 0
            assert len(w) == 1
            assert issubclass(w[-1].category, SyntaxWarning)


def test_validate_local_failed():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        remote = "/app"

        with pytest.raises(ValueError, match="Don't support file like object"):
            with tempfile.TemporaryDirectory() as tmpdirname:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=tmpdirname, delete=False
                ) as f:
                    client.put(f, remote)

        local = None
        with pytest.raises(TypeError):
            client.put(local, remote)

        local = ""
        with pytest.raises(ValueError, match="isn't a file"):
            client.put(local, remote)

        local = "/root"
        with pytest.raises(ValueError, match=f"{local!r} isn't a file"):
            client.put(local, remote)

        local = "notexist"
        with pytest.raises(FileNotFoundError, match="No such file or directory"):
            client.put(local, remote)


def test_upload_case_one():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=tmpdirname, delete=False
            ) as f:
                f.write("Hello world\n")
                f.close()

                with pytest.raises(ValueError, match="No allow empty remote"):
                    client.put(f.name, "")

                with pytest.raises(ValueError, match="No allow empty remote"):
                    client.put(f.name, None)

                with pytest.raises(ValueError, match="No allow empty remote"):
                    client.put(f.name, False)

                with pytest.raises(TypeError):
                    client.put(f.name, True)

                with pytest.raises(
                    ValueError, match="Remote must be absolute path, got 'abc.txt'"
                ):
                    client.put(f.name, "abc.txt")

                sftp = client.sftp

                current_abs_path = os.path.abspath("")
                basename = os.path.basename(f.name)
                current_file_abs_path = os.path.join(current_abs_path, basename)
                shutil.copyfile(f.name, current_file_abs_path)
                remote = "/app"
                remote_abs_path = os.path.join(remote, basename)
                try:
                    client.put(basename, remote)
                    sftp.stat(remote_abs_path)
                finally:
                    os.remove(current_file_abs_path)

                client.put(f.name, remote)
                sftp.stat(remote_abs_path)

                client.put(f.name, "/app/test.txt")
                sftp.stat("/app/test.txt")

                remote = "/notexist"
                with pytest.raises(
                    FileNotFoundError, match=f"No such file or directory: {remote!r}"
                ):
                    client.put(f.name, remote)

                with pytest.raises(FileNotFoundError):
                    client.put(f.name, "/app/notexist/test.txt")


def test_upload_case_two():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        not_granted_dir = "/root/xtrabackup_backupfiles"
        code, _, failure = client.run(f"sudo mkdir -p {not_granted_dir}")
        if code:
            raise RuntimeError(failure)
        # Just in case
        code, _, failure = client.run(f"sudo chown root:root {not_granted_dir}")
        if code:
            raise RuntimeError(failure)

        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=tmpdirname, delete=False
            ) as f:
                f.write("Hello world\n")
                f.close()

                basename = os.path.basename(f.name)
                remote = "/root"
                remote_abs_path = os.path.join(remote, basename)

                client.put(f.name, remote, sudo=True)
                code, _, _ = client.run(f"sudo [ -f {remote_abs_path} ]")
                assert code == 0

                client.put(f.name, remote_abs_path, sudo=True)
                code, _, _ = client.run(f"sudo [ -f {remote_abs_path} ]")
                assert code == 0

                with pytest.raises(PermissionError):
                    client.put(f.name, not_granted_dir)

                not_granted_remote_abs_path = os.path.join(not_granted_dir, basename)
                client.put(f.name, not_granted_dir, sudo=True)
                code, _, _ = client.run(f"sudo [ -f {not_granted_remote_abs_path} ]")
                assert code == 0

                with pytest.raises(PermissionError):
                    client.put(f.name, not_granted_remote_abs_path)

                client.put(f.name, not_granted_remote_abs_path, sudo=True)
                code, _, _ = client.run(f"sudo [ -f {not_granted_remote_abs_path} ]")
                assert code == 0

                with pytest.raises(AssertionError):
                    client.put(
                        f.name,
                        os.path.join(not_granted_dir, "notexist", basename),
                        sudo=True,
                    )

                with pytest.raises(AssertionError):
                    client.put(
                        f.name,
                        os.path.join(not_granted_remote_abs_path, basename),
                        sudo=True,
                    )


def test_upload_case_three():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=tmpdirname, delete=False
            ) as f:
                f.write("Hello world\n")
                f.close()

                sftp = client.sftp

                remote = os.path.join("/app", os.path.basename(f.name))
                client.put(f.name, remote, preserve_mode=False)
                local_mode = stat.S_IMODE(os.stat(f.name).st_mode)
                remote_mode = stat.S_IMODE(sftp.stat(remote).st_mode)
                assert local_mode != remote_mode

                client.put(f.name, remote, preserve_mode=True)
                remote_mode = stat.S_IMODE(sftp.stat(remote).st_mode)
                assert local_mode == remote_mode

                remote = os.path.join("/root", os.path.basename(f.name))
                client.put(f.name, remote, preserve_mode=True, sudo=True)
                code, success, failure = client.run(f"sudo stat {remote}")
                if code:
                    raise RuntimeError(failure)
                re_mode = re.compile(r"Access: \((\d+).*\)  Uid")
                match_mode = re_mode.search(success)
                remote_mode = int(match_mode.group(1).strip(), 8)
                assert local_mode == remote_mode


def test_validate_remote_failed():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with pytest.raises(ValueError, match="No allow empty remote"):
            client.get("", "abc.txt")

        with pytest.raises(ValueError, match="No allow empty remote"):
            client.get(None, "abc.txt")

        with pytest.raises(ValueError, match="No allow empty remote"):
            client.get(False, "abc.txt")

        with pytest.raises(
            TypeError, match="expected str, bytes or os.PathLike object, not bool"
        ):
            client.get(True, "abc.txt")

        with pytest.raises(ValueError, match="Remote must be absolute path"):
            client.get("sshd.pid", "abc.txt")

        with pytest.raises(ValueError, match="Remote must be a file"):
            client.get("/config", "abc.txt")

        with pytest.raises(FileNotFoundError):
            client.get("/config/notexists", "abc.txt")

        with pytest.raises(PermissionError):
            client.get("/root/abc.txt", "abc.txt")

        with pytest.raises(AssertionError, match="Remote not exist or not a file"):
            client.get("/root/abc.txt", "abc.txt", sudo=True)


def test_validate_local_failed_v2():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with pytest.raises(ValueError, match="No allow empty local"):
            client.get("/etc/motd", "")

        with pytest.raises(ValueError, match="No allow empty local"):
            client.get("/etc/motd", None)

        with pytest.raises(ValueError, match="No allow empty local"):
            client.get("/etc/motd", False)

        with pytest.raises(
            TypeError, match="expected str, bytes or os.PathLike object, not bool"
        ):
            client.get("/etc/motd", True)

        with pytest.raises(ValueError, match="Expect file path, got directory"):
            client.get("/etc/motd", "tests")

        with pytest.raises(ValueError, match="Expect file path, got directory"):
            client.get("/etc/motd", "/var/app")

        with pytest.raises(FileNotFoundError):
            client.get("/etc/motd", "/var/app/notexists/tests")


def test_download_case_one():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=tmpdirname, delete=False
            ) as f:
                f.write("Hello world\n")
                f.close()

            basename = os.path.basename(f.name)
            remote = os.path.join("/app", basename)
            client.put(f.name, remote)

            local = os.path.join("/var/app", basename)
            client.get(remote, local, preserve_mode=False)

            sftp = client.sftp

            remote_mode = stat.S_IMODE(sftp.stat(remote).st_mode)
            local_mode = stat.S_IMODE(os.stat(local).st_mode)
            assert remote_mode != local_mode

            client.get(remote, local, preserve_mode=True)
            local_mode = stat.S_IMODE(os.stat(local).st_mode)
            assert remote_mode == local_mode


def test_download_case_two():
    with SSHClientWithReturnCode(
        hostname=PASSWORDLESS_SUDO_HOST,
        port=PORT,
        username=USER,
        pkey=create_pkey(PRIVATE_KEY),
    ) as client:
        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=tmpdirname, delete=False
            ) as f:
                f.write("Hello world\n")
                f.close()

            basename = os.path.basename(f.name)
            remote = os.path.join("/root", basename)
            client.put(f.name, remote, sudo=True)

            local = os.path.join("/var/app", basename)
            tmp_remote = os.path.join("/tmp", basename)
            client.get(remote, local, preserve_mode=True, sudo=True)
            code, _, _ = client.run(f"[[ -f {tmp_remote} ]]")
            assert code != 0

            code_stat, success_stat, failure_stat = client.run(f"sudo stat {remote}")
            if code_stat:
                raise RuntimeError(failure_stat)
            re_mode = re.compile(r"Access: \((\d+).*\)  Uid")
            match_mode = re_mode.search(success_stat)
            remote_mode = int(match_mode.group(1).strip(), 8)
            local_mode = stat.S_IMODE(os.stat(local).st_mode)
            assert remote_mode == local_mode


def detect_sftp_obj(client: SSHClientV2) -> int:
    start = time.perf_counter()
    print("Start: ", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    thread_name = threading.current_thread().name
    sftp_address = id(client.sftp)
    print(f"Thread: {thread_name}, id(sftp)={sftp_address}")
    print("End: ", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    print(f"Cost: {time.perf_counter() - start}")

    return sftp_address


def test_singleton_sftp():
    with SSHClientV2(hostname=HOST, username=USER, password=PWD, port=PORT) as client:
        sftp_address_set = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {
                executor.submit(detect_sftp_obj, client): i for i in range(10)
            }
            for future in concurrent.futures.as_completed(future_to_url):
                sftp_address_set.add(future.result())

        assert len(sftp_address_set) == 1

