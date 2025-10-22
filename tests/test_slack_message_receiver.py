import unittest
import sys
import os
import re
import shlex

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import only the validation functions we need (not the whole module to avoid Slack client initialization)
# We'll copy the functions here for testing purposes


def is_oar_related_message(message):
    """Copied from slack_message_receiver.py for testing"""
    return message.startswith("oar") or message.startswith("oarctl") or re.search(r"^<@.*>\s+oar\s+", message) or re.search(r"^<@.*>\s+oarctl\s+", message)


def validate_oar_command(message):
    """Copied from slack_message_receiver.py for testing"""
    # Shell metacharacters that could be used for command injection
    DANGEROUS_CHARS = [';', '&', '|', '`', '$', '(', ')', '<', '>', '\n', '\r']

    # Extract the command part (handle both direct commands and @mentions)
    if message.startswith("oar") or message.startswith("oarctl"):
        cmd = message
    else:
        # Extract from @mention format: <@U12345> oar -r 4.19.1 ...
        match = re.search(r'<@.*?>\s+(oar(?:ctl)?(?:\s|$).*)', message)
        if not match:
            return False, None, "Could not extract OAR command from message"
        cmd = match.group(1)

    # Check for dangerous shell metacharacters
    for char in DANGEROUS_CHARS:
        if char in cmd:
            return False, None, f"Invalid character '{char}' detected in command. Command injection attempt blocked."

    # Validate command starts with allowed commands
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        return False, None, f"Invalid command syntax: {e}"

    if not cmd_parts:
        return False, None, "Empty command"

    ALLOWED_COMMANDS = ['oar', 'oarctl']
    if cmd_parts[0] not in ALLOWED_COMMANDS:
        return False, None, f"Command must start with 'oar' or 'oarctl', got: {cmd_parts[0]}"

    return True, cmd, None


class TestSlackMessageReceiver(unittest.TestCase):
    """Test security and functionality of Slack message processing"""

    def test_validate_valid_oar_command(self):
        """Test that valid OAR commands pass validation"""
        test_cases = [
            "oar -r 4.19.1 create-test-report",
            "oarctl start-release-detector -r 4.19",
            "oar -r 4.19.1 update-bug-list --no-notify",
            "oar -r 4.19.1 take-ownership -e user@redhat.com",
        ]

        for cmd in test_cases:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertTrue(is_valid, f"Command should be valid: {cmd}")
                self.assertEqual(extracted_cmd, cmd)
                self.assertIsNone(error)

    def test_validate_oar_command_with_mention(self):
        """Test that @mention format commands are properly extracted"""
        message = "<@U12345> oar -r 4.19.1 create-test-report"
        is_valid, extracted_cmd, error = validate_oar_command(message)

        self.assertTrue(is_valid)
        self.assertEqual(extracted_cmd, "oar -r 4.19.1 create-test-report")
        self.assertIsNone(error)

    def test_validate_blocks_command_injection_with_semicolon(self):
        """Test that semicolon command chaining is blocked"""
        malicious_cmds = [
            "oar -r 4.19.1 create-test-report; rm -rf /",
            "oar -r 4.19.1 update-bug-list; cat /etc/passwd",
            "oarctl start-release-detector -r 4.19; whoami",
        ]

        for cmd in malicious_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                self.assertIn(";", error)
                self.assertIn("Command injection attempt blocked", error)

    def test_validate_blocks_command_injection_with_ampersand(self):
        """Test that & and && command chaining is blocked"""
        malicious_cmds = [
            "oar -r 4.19.1 create-test-report & rm -rf /",
            "oar -r 4.19.1 update-bug-list && cat /etc/passwd",
            "oarctl start-release-detector -r 4.19 & whoami",
        ]

        for cmd in malicious_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                self.assertIn("&", error)

    def test_validate_blocks_command_injection_with_pipe(self):
        """Test that pipe command chaining is blocked"""
        malicious_cmds = [
            "oar -r 4.19.1 create-test-report | grep secret",
            "oar -r 4.19.1 update-bug-list || cat /etc/passwd",
        ]

        for cmd in malicious_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                self.assertIn("|", error)

    def test_validate_blocks_command_substitution(self):
        """Test that command substitution attempts are blocked"""
        malicious_cmds = [
            "oar -r 4.19.1 create-test-report $(whoami)",
            "oar -r 4.19.1 update-bug-list `cat /etc/passwd`",
            "oar -r $(malicious_command) create-test-report",
        ]

        for cmd in malicious_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                # Should fail on $, (, ), or `
                self.assertTrue(any(char in error for char in ['$', '(', ')', '`']))

    def test_validate_blocks_redirection(self):
        """Test that I/O redirection is blocked"""
        malicious_cmds = [
            "oar -r 4.19.1 create-test-report > /tmp/output",
            "oar -r 4.19.1 update-bug-list < /etc/passwd",
            "oar -r 4.19.1 drop-bugs >> /tmp/secrets",
        ]

        for cmd in malicious_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                self.assertTrue(any(char in error for char in ['<', '>']))

    def test_validate_blocks_newline_injection(self):
        """Test that newline characters are blocked"""
        malicious_cmd = "oar -r 4.19.1 create-test-report\nrm -rf /"
        is_valid, extracted_cmd, error = validate_oar_command(malicious_cmd)

        self.assertFalse(is_valid)
        self.assertIsNone(extracted_cmd)
        # The error contains a literal newline character
        self.assertIn("Invalid character", error)
        self.assertIn("Command injection attempt blocked", error)

    def test_validate_blocks_invalid_command_names(self):
        """Test that only 'oar' and 'oarctl' commands are allowed"""
        invalid_cmds = [
            "rm -rf /",
            "cat /etc/passwd",
            "curl http://evil.com",
            "python malicious.py",
        ]

        for cmd in invalid_cmds:
            with self.subTest(cmd=cmd):
                is_valid, extracted_cmd, error = validate_oar_command(cmd)
                self.assertFalse(is_valid, f"Command should be blocked: {cmd}")
                self.assertIsNone(extracted_cmd)
                self.assertIsNotNone(error)

    def test_validate_handles_empty_command(self):
        """Test that empty commands are rejected"""
        is_valid, extracted_cmd, error = validate_oar_command("")

        self.assertFalse(is_valid)
        self.assertIsNone(extracted_cmd)
        # Empty string doesn't start with oar/oarctl and doesn't match mention pattern
        self.assertIn("Could not extract OAR command", error)

    def test_validate_handles_malformed_quotes(self):
        """Test that malformed quoted strings are caught"""
        malformed_cmd = 'oar -r 4.19.1 -e "unclosed quote'
        is_valid, extracted_cmd, error = validate_oar_command(malformed_cmd)

        self.assertFalse(is_valid)
        self.assertIsNone(extracted_cmd)
        self.assertIn("Invalid command syntax", error)

    def test_is_oar_related_message_detects_direct_commands(self):
        """Test that direct OAR commands are detected"""
        self.assertTrue(is_oar_related_message("oar -r 4.19.1 create-test-report"))
        self.assertTrue(is_oar_related_message("oarctl start-release-detector -r 4.19"))

    def test_is_oar_related_message_detects_mentions(self):
        """Test that @mention OAR commands are detected"""
        self.assertTrue(is_oar_related_message("<@U12345> oar -r 4.19.1 create-test-report"))
        self.assertTrue(is_oar_related_message("<@U12345> oarctl jira-notificator"))

    def test_is_oar_related_message_ignores_non_oar(self):
        """Test that non-OAR messages are not detected"""
        self.assertFalse(is_oar_related_message("Hello, how are you?"))
        self.assertFalse(is_oar_related_message("Please check the oar logs"))
        self.assertFalse(is_oar_related_message("The oarctl command is useful"))

    def test_validate_allows_email_addresses(self):
        """Test that email addresses in valid commands are allowed"""
        cmd = "oar -r 4.19.1 take-ownership -e user@redhat.com"
        is_valid, extracted_cmd, error = validate_oar_command(cmd)

        self.assertTrue(is_valid)
        self.assertEqual(extracted_cmd, cmd)
        self.assertIsNone(error)

    def test_validate_allows_version_numbers(self):
        """Test that version numbers are properly handled"""
        cmd = "oar -r 4.19.1 update-bug-list"
        is_valid, extracted_cmd, error = validate_oar_command(cmd)

        self.assertTrue(is_valid)
        self.assertEqual(extracted_cmd, cmd)
        self.assertIsNone(error)


if __name__ == '__main__':
    unittest.main()
