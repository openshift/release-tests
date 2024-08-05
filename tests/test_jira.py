import unittest
import os
from oar.core.configstore import ConfigStore
from oar.core.exceptions import JiraException
from oar.core.jira import JiraManager
from oar.core.const import *


class TestJiraManager(unittest.TestCase):
    token = os.environ.get(ENV_VAR_JIRA_TOKEN)
    token_not_found = token == None
    token_is_dummy = token and token.startswith("dummy")

    def setUp(self):
        try:
            self.jm = JiraManager(ConfigStore("4.12.11"))
        except:
            raise

    @unittest.skipIf(not token_not_found, "token is found, skip this case")
    def test_init(self):
        self.assertRaises(JiraException, JiraManager, ConfigStore("4.12.11"))

    @unittest.skipUnless(token_is_dummy, "token is not dummy one, skip this case")
    def test_invalid_token(self):
        self.assertRaises(JiraException, JiraManager, ConfigStore("4.12.11"))

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_get_issue_fields(self):
        issue = self.jm.get_issue("OCPBUGS-6622")
        self.assertEqual(issue.get_qa_contact(), "rioliu@redhat.com")
        self.assertEqual(issue.get_priority(), "Critical")
        self.assertEqual(issue.get_status(), "Closed")
        self.assertIn("FastFix", issue.get_labels())
        self.assertEqual(issue.get_release_blocker(), "Rejected")
        self.assertEqual(issue.get_sfdc_case_counter(), "6.0")
        self.assertIn("03394641", issue.get_sfdc_case_links().split(" "))
        self.assertTrue(issue.is_critical_issue())
        self.assertTrue(issue.is_customer_case())
        self.assertFalse(issue.is_cve_tracker())

    @unittest.skip("don't run this case by default")
    def test_create_issue(self):
        issue = self.jm.create_issue(
            project="OCPQE",
            summary="dummy summary from jira manager",
            description="dummy description from jira manager",
            issuetype={"name": "Bug"},
        )

        self.assertEqual(issue.get_summary(), "dummy summary from jira manager")

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_update_issue(self):
        key = "OCPQE-15027"
        self.jm.assign_issue(key, "rioliu@redhat.com")
        self.assertEqual(self.jm.get_issue(key).get_assignee(), "rioliu@redhat.com")

        self.jm.transition_issue(key, JIRA_STATUS_IN_PROGRESS)
        self.assertEqual(self.jm.get_issue(key).get_status(), JIRA_STATUS_IN_PROGRESS)

        self.jm.transition_issue(key, JIRA_STATUS_CLOSED)
        self.assertEqual(self.jm.get_issue(key).get_status(), JIRA_STATUS_CLOSED)

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_get_subtasks(self):
        key = "ART-6731"
        subtasks = self.jm.get_sub_tasks(key)
        self.assertIsNotNone(subtasks)
        self.assertTrue(len(subtasks) > 0)
        for st in subtasks:
            if st.is_qe_subtask():
                print(f"qe task: {st.get_key()} - {st.get_summary()}")
                self.assertIn(st.get_summary(), JIRA_QE_TASK_SUMMARIES)

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_change_assignee_of_qe_tasks(self):
        key = "OCPQE-15027"
        self.jm._cs.set_jira_ticket(key)
        self.jm.change_assignee_of_qe_subtasks()
        subtasks = self.jm.get_sub_tasks(key)
        for st in subtasks:
            self.assertEqual(st.get_assignee(), "rioliu@redhat.com")

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_add_comment(self):
        key = "OCPQE-15027"
        self.jm.add_comment(key, "test result url is https://xxx")
        self.assertRaises(JiraException, self.jm.add_comment, None, "dummy comment")
        self.assertRaises(JiraException, self.jm.add_comment, key, "")
        self.assertRaises(JiraException, self.jm.add_comment, "", "")
        self.assertRaises(JiraException, self.jm.add_comment, None, None)
