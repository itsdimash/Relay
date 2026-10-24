import os
import subprocess
import unittest

from relay.environment import augment_path, login_shell_path, prepare_environment


class AugmentPathTests(unittest.TestCase):
    def test_minimal_finder_path_gains_tool_folders(self):
        existing = {'/opt/homebrew/bin', '/Users/me/.local/bin'}
        result = augment_path('/usr/bin:/bin', home='/Users/me', exists=lambda p: p in existing)
        self.assertEqual(result.split(os.pathsep), ['/usr/bin', '/bin', '/opt/homebrew/bin', '/Users/me/.local/bin'])

    def test_login_shell_entries_are_added_once_and_keep_order(self):
        result = augment_path('/usr/bin', home='/h', shell_path='/Users/me/.nvm/bin:/usr/bin:/opt/homebrew/bin',
                              exists=lambda p: p != '/opt/homebrew/sbin')
        parts = result.split(os.pathsep)
        self.assertEqual(parts[0], '/usr/bin')
        self.assertEqual(parts.count('/usr/bin'), 1)
        self.assertLess(parts.index('/Users/me/.nvm/bin'), parts.index('/opt/homebrew/bin'))

    def test_missing_folders_are_skipped_but_existing_path_is_kept(self):
        result = augment_path('/custom/tools', home='/h', exists=lambda p: False)
        self.assertEqual(result, '/custom/tools')

    def test_prepare_environment_updates_mapping(self):
        env = {'PATH': '/usr/bin'}
        new = prepare_environment(env, read_login_path=lambda: '/Users/me/.nvm/bin')
        self.assertEqual(env['PATH'], new)
        self.assertTrue(new.startswith('/usr/bin'))


class LoginShellTests(unittest.TestCase):
    def test_reads_last_line_of_output(self):
        def fake(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout='Welcome back\n/a:/b\n', stderr='')
        self.assertEqual(login_shell_path(shell='/bin/sh', run=fake), '/a:/b')

    def test_timeout_and_failure_return_empty(self):
        def slow(*args, **kwargs):
            raise subprocess.TimeoutExpired(args, 1)
        def failing(*args, **kwargs):
            return subprocess.CompletedProcess(args, 1, stdout='x', stderr='')
        self.assertEqual(login_shell_path(shell='/bin/sh', run=slow), '')
        self.assertEqual(login_shell_path(shell='/bin/sh', run=failing), '')

    def test_missing_shell_returns_empty(self):
        self.assertEqual(login_shell_path(shell='/definitely/not/a/shell'), '')


if __name__ == '__main__':
    unittest.main()
