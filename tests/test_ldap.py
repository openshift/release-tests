import unittest

from oar.core.ldap import LdapHelper


class TestLdapHelper(unittest.TestCase):
    def setUp(self):
        self.ldap = LdapHelper()

    def test_get_user_email_from_id(self):
        user_email = self.ldap._get_user_email("tdavid")
        self.assertEqual("tdavid@redhat.com", user_email)

    def test_get_manager_id_from_user_email(self):
        manager_id = self.ldap._get_manager_id("tdavid@redhat.com")
        self.assertEqual("gjospin", manager_id)

    def test_get_manager_email_from_user_email(self):
        manager_email = self.ldap.get_manager_email("gjospin@redhat.com")
        self.assertEqual("vlaad@redhat.com", manager_email)

    def test_get_group_members_emails(self):
        expected_members_emails = {
            "tdavid@redhat.com",
            "gjospin@redhat.com",
            "bsiskova@redhat.com",
            "lterifaj@redhat.com",
            "cardelea@redhat.com",
            "jhuttana@redhat.com",
            "rioliu@redhat.com",
            "minl@redhat.com",
            "ltroiano@redhat.com",
        }
        group_members_emails = self.ldap.get_group_members_emails(
            "ocp-errata-reliability-team"
        )
        self.assertCountEqual(expected_members_emails, group_members_emails)
