import unittest

import oar.core.util as util
from oar.core.configstore import ConfigStore
from oar.core.exceptions import ConfigStoreException


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
        # add new case to cover OCPERT-35
        cs = ConfigStore("4.15.41")
        jira = cs.get_jira_ticket()
        self.assertEqual(jira, "ART-11549")

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

        self.assertRaises(ConfigStoreException,
                          self.cs.get_slack_contact, "dummy")

    def test_get_email_contact(self):
        contact = self.cs.get_email_contact("qe")
        self.assertEqual(contact, "aos-qe@redhat.com")

        self.assertRaises(ConfigStoreException,
                          self.cs.get_email_contact, "dummy")

    def test_get_report_template(self):
        template = self.cs.get_report_template()
        self.assertEqual(
            template, "1Xv8qfYUwp61lOOMQaXNO7wnlo9b8mXACgug49cZHCTM")

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

    def test_get_jenkins_server(self):
        server_url = self.cs.get_jenkins_server()
        self.assertTrue(
            "dno.corp.redhat.com" in server_url)
        
    def test_get_release_version(self):
        version = "4.18.1"
        self.assertEqual(version, util.get_release_key(version))
        version = "4.18.0-rc.8"
        self.assertEqual("rc.8", util.get_release_key(version))
        version = "4.19.0-ec.1"
        self.assertEqual("ec.1", util.get_release_key(version))

        for r in ["4.18.0-rc.8", "4.19.0-ec.1"]:
            cs = ConfigStore(r)
            self.assertGreater(len(cs.get_advisories()), 0)
    
    def test_get_gitlab_url(self):
        self.assertEqual(self.cs.get_gitlab_url(), "https://gitlab.cee.redhat.com")
        
