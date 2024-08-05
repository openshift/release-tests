import unittest
from oar.core.exceptions import ConfigStoreException
from oar.core.advisory import AdvisoryManager
from oar.core.jira import JiraManager
from oar.core.worksheet import WorksheetManager
from oar.core.configstore import ConfigStore


class TestConfigStore(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.cs = ConfigStore("4.12.11")

    def test_init(self):
        self.assertRaises(ConfigStoreException, ConfigStore, "")
        self.assertRaises(ConfigStoreException, ConfigStore, "4.")
        self.assertRaises(ConfigStoreException, ConfigStore, "4.12")

    def test_get_advisories(self):
        advisories = self.cs.get_advisories()
        ad_types = advisories.keys()
        ad_values = advisories.values()
        # verify advisory types
        self.assertIn("extras", ad_types)
        self.assertIn("image", ad_types)
        self.assertIn("metadata", ad_types)
        self.assertIn("rpm", ad_types)
        # verify advisory values, one item is enough
        self.assertIn(112393, ad_values)

    def test_get_cadidate_builds(self):
        cb = self.cs.get_candidate_builds()
        build_types = cb.keys()
        build_nums = cb.values()
        # verify build types e.g. x86_64
        self.assertIn("x86_64", build_types)
        self.assertIn("aarch64", build_types)
        self.assertIn("ppc64le", build_types)
        self.assertIn("s390x", build_types)
        # verify build nums, one build is enough
        self.assertIn("4.12.0-0.nightly-2023-04-04-050651", build_nums)

    def test_get_jira(self):
        jira = self.cs.get_jira_ticket()
        self.assertEqual(jira, "ART-6489")

    def test_get_owner(self):
        # verify default value, if minor release not found in conf
        owner = self.cs.get_owner()
        self.assertEqual(owner, "rioliu@redhat.com")

        cs = ConfigStore("4.11.10")
        owner = cs.get_owner()
        self.assertEqual(owner, "wenwang@redhat.com")

    def test_get_slack_contact(self):
        contact = self.cs.get_slack_contact("qe")
        self.assertEqual(contact["channel"], "#forum-qe")
        self.assertEqual(contact["id"], "openshift-qe")

        self.assertRaises(ConfigStoreException, self.cs.get_slack_contact, "dummy")

    def test_get_email_contact(self):
        contact = self.cs.get_email_contact("qe")
        self.assertEqual(contact, "aos-qe@redhat.com")

        self.assertRaises(ConfigStoreException, self.cs.get_email_contact, "dummy")

    def test_get_report_template(self):
        template = self.cs.get_report_template()
        self.assertEqual(template, "1Xv8qfYUwp61lOOMQaXNO7wnlo9b8mXACgug49cZHCTM")

        cs = ConfigStore("4.9.10")
        self.assertRaises(ConfigStoreException, cs.get_report_template)
        
    def test_get_inheritance_rule(self):
        cs = ConfigStore("4.13.21")
        ads = cs.get_advisories()
        self.assertEqual(123314, ads["extras"])
        
        cs = ConfigStore("4.14.1")
        ads = cs.get_advisories()
        self.assertEqual(123024, ads["rpm"])
        builds = cs.get_candidate_builds()
        self.assertEqual(len(builds), 0)
  
