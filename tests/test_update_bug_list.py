import unittest
import oar.cli.cmd_update_bug_list as cmd_update_bug_list
from click.testing import CliRunner

class TestBugList(unittest.TestCase):
    def test_bug_list_test(self):
        self.maxDiff = None
        runner =  CliRunner()
        result = runner.invoke(cmd_update_bug_list.update_bug_list, '--help')
        expect = '''--notify / --no-notify  Send notification to bug owner, default value is true'''
        self.assertIn(expect, result.output)
        result = runner.invoke(cmd_update_bug_list.update_bug_list, '--notify')
        self.assertEqual(result.exit_code, 1)
        result = runner.invoke(cmd_update_bug_list.update_bug_list, '--no-notify')
        self.assertEqual(result.exit_code, 1)
        result = runner.invoke(cmd_update_bug_list.update_bug_list, '--notify/--no-notify')
        self.assertIn('Error: No such option: --notify/--no-notify Did you mean --no-notify', result.output)