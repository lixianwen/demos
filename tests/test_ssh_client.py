import unittest

from demos.socket.ssh_client import SSHClientWithReturnCode


class MyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SSHClientWithReturnCode(hostname='192.168.1.2', username='root', password='a')

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_huge_output_command(self):
        stdout, stderr, return_code = self.client.run('ls -lshAR -h /')
        self.assertEqual(return_code, 0)

    def test_small_output_command(self):
        stdout, stderr, return_code = self.client.run('cat /etc/redhat-release')
        self.assertEqual(stdout.strip(), 'CentOS Linux release 7.8.2003 (Core)')
        self.assertEqual(return_code, 0)
        self.assertTrue(stdout)
        self.assertFalse(stderr)

    def test_run_failed_command(self):
        stdout, stderr, return_code = self.client.run('[[ -f /root/1.txt ]]')
        self.assertNotEqual(return_code, 0)

    def test_timeout_command_work(self):
        command = 'curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose'
        self.client.duration = 15
        stdout, stderr, return_code = self.client.run(command)
        self.assertEqual(return_code, 124)

    def test_duration(self):
        with self.assertRaises(ValueError):
            SSHClientWithReturnCode(hostname='192.168.1.2', username='root', password='a', duration=-1)


if __name__ == '__main__':
    unittest.main()
