import os
import unittest
from collections import ChainMap
from unittest.mock import Mock

from jira.client import ResultList

from oar.core.configstore import ConfigStore
from oar.core.const import *
from oar.core.exceptions import JiraException
from oar.core.jira import Issue, JIRA, JiraManager
from oar.core.util import get_advisory_link


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
        self.assertEqual(issue.get_need_info_from(), None)

    @unittest.skipIf(
        token_not_found or token_is_dummy, "token is not found, skip this case"
    )
    def test_set_issue_fields(self):
        issue = self.jm.get_issue("OCPBUGS-59288")
        qa_contact = issue._issue.fields.customfield_12315948
        self.assertEqual(issue.get_need_info_from(), None)
        issue.set_need_info_from([qa_contact.raw])
        self.assertEqual(issue.get_need_info_from(), [qa_contact])

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

    def test_get_high_severity_and_can_drop_issues(self):
        # Prepare test data
        # Fields indicating CVE, release blocker and customer case issue at the same time
        fields_full = {
            "summary": "CVE - Full: CVE, release blocker and customer case issue",  # Is CVE issue
            "labels": ["CVE_TestLabel", "TestBlocker"],  # Is CVE issue, is Blocker issue
            "customfield_12319743": "Approved",  # Is Release Blocker
            "customfield_12313440": 2,  # Is Customer Case
            "customfield_12313441": "03955817 03955962"  # Is Customer Case
        }

        fields_CVE_1 = {
            "summary": "CVE Issue 1",  # Is CVE issue
            "labels": ["TestLabel1"]
        }

        fields_CVE_2 = {
            "summary": "* Issue 2",
            "labels": ["TestLabel1", "CVE_TestLabel"]  # Is CVE issue
        }

        fields_blocker_1 = {
            "summary": "Blocker Issue 1",
            "labels": ["TestBlocker"]  # Is Blocker issue
        }

        fields_blocker_2 = {
            "summary": "Blocker Issue 2",
            "customfield_12319743": "Approved",  # Is Release Blocker
        }

        fields_blocker_3 = {
            "summary": "Blocker Issue 3",
            "customfield_12319743": "Proposed",  # May be Release Blocker
        }

        fields_customer_case = {
            "summary": "Customer Case Issue 1",
            "customfield_12313440": 1,  # Is Customer Case
            "customfield_12313441": "03955817"  # Is Customer Case
        }

        fields_low_severity = {
            "summary": "Low severity fields Issue",
            "labels": ["TestLabel1", "TestLabel2"],
            "customfield_12319743": "Rejected",
            "customfield_12313440": 0,
            "customfield_12313441": ""
        }

        high_severity_issues_data = {
            "OCPBUGS-n100": {"status": "ON_QA", "priority": "Blocker"},
            "OCPBUGS-n101": {"status": "ON_QA", "priority": "Critical"},
            "OCPBUGS-n102": {"status": "ON_QA", "priority": "Major", "fields": fields_full},
            "OCPBUGS-n103": {"status": "ON_QA", "priority": "Normal", "fields": fields_CVE_1},
            "OCPBUGS-n104": {"status": "ON_QA", "priority": "Minor", "fields": fields_CVE_2},
            "OCPBUGS-n105": {"status": "ON_QA", "priority": "Major", "fields": fields_blocker_1},
            "OCPBUGS-n106": {"status": "ON_QA", "priority": "Major", "fields": fields_blocker_2},
            "OCPBUGS-n107": {"status": "ON_QA", "priority": "Undefined", "fields": fields_blocker_3},
            "OCPBUGS-n108": {"status": "ON_QA", "priority": "Major", "fields": fields_customer_case},
            "OCPBUGS-n109": {"status": "ON_QA", "priority": "Blocker", "fields": fields_low_severity},
            "OCPBUGS-n110": {"status": "New", "priority": "Blocker"},
            "OCPBUGS-n111": {"status": "Assigned", "priority": "Critical", "fields": fields_full},
        }

        can_drop_issues_data = {
            "OCPBUGS-n150": {"status": "ON_QA", "priority": "Major"},
            "OCPBUGS-n151": {"status": "ON_QA", "priority": "Normal"},
            "OCPBUGS-n152": {"status": "ON_QA", "priority": "Minor"},
            "OCPBUGS-n153": {"status": "ON_QA", "priority": "Undefined"},
            "OCPBUGS-n154": {"status": "New", "priority": "Major"},
            "OCPBUGS-n155": {"status": "Assigned", "priority": "Major"},
            "OCPBUGS-n156": {"status": "POST", "priority": "Major"},
            "OCPBUGS-n157": {"status": "MODIFIED", "priority": "Major"},
            "OCPBUGS-n158": {"status": "ON_QA", "priority": "Major", "fields": fields_low_severity}
        }

        closed_issues_data = {
            "OCPBUGS-n180": {"status": "Closed", "priority": "Blocker"},
            "OCPBUGS-n181": {"status": "Closed", "priority": "Critical", "fields": fields_full},
            "OCPBUGS-n182": {"status": "Closed", "priority": "Major"},
            "OCPBUGS-n183": {"status": "Verified", "priority": "Normal"}
        }

        all_issues_data = ChainMap(high_severity_issues_data, can_drop_issues_data, closed_issues_data)

        # Prepare mocks
        mock_issues = {}
        for issue_id, data in all_issues_data.items():
            mock_issues[issue_id] = self._mock_issue(issue_id, data["status"], data["priority"], data.get("fields"))

        mock_jira = Mock(spec=JIRA)
        mock_jira.issue.side_effect = lambda key: mock_issues.get(key, None)
        self.jm._svc = mock_jira

        # Call the tested method
        high_severity_issues, can_drop_issues = self.jm.get_high_severity_and_can_drop_issues(all_issues_data)

        # Assertions
        for key in high_severity_issues_data:
            self.assertIn(key, high_severity_issues)
        for key in can_drop_issues_data:
            self.assertIn(key, can_drop_issues)
        for key in closed_issues_data:
            self.assertNotIn(key, high_severity_issues)
            self.assertNotIn(key, can_drop_issues)

    def _mock_issue(self, key, status_name, priority_name, fields=None):
        fields = fields or {}

        mock_issue = Mock(spec=Issue)
        mock_issue.key = key

        mock_field = Mock()
        mock_field.status.name = status_name
        mock_field.priority.name = priority_name
        mock_field.labels = []
        mock_field.summary = "Default issue summary"
        mock_field.customfield_12313440 = 0  # SFDC Cases Counter
        mock_field.customfield_12313441 = None  # SFDC Cases Links
        mock_field.customfield_12319743 = None  # Release Blocker: None, Rejected, Approved, Proposed

        for field_name, field_value in fields.items():
            if field_name == "customfield_12319743":
                mock_customfield_12319743 = Mock()
                mock_field.customfield_12319743 = mock_customfield_12319743
                mock_field.customfield_12319743.value = field_value
            else:
                setattr(mock_field, field_name, field_value)

        mock_issue.fields = mock_field

        return mock_issue

    def test__prepare_greenwave_cvp_jira_description(self):
        test_data = [
            {"nvr_id": 200, "errata_id": 100, "nvr": "nvrB"},
            {"nvr_id": 201, "errata_id": 100, "nvr": "nvrC"},
            {"nvr_id": 202, "errata_id": 102, "nvr": "nvrD"},
            {"nvr_id": 203, "errata_id": 103, "nvr": "nvrE"}
        ]

        abnormal_tests = []
        for data in test_data:
            abnormal_tests.append(
                {
                    "id": data["nvr_id"],
                    "relationships": {
                        "errata": {
                            "id": data["errata_id"]
                        },
                        "brew_build": {
                            "nvr": data["nvr"]
                        }
                    }
                }
            )

        expected_description = f"""[{self.jm._cs.release}] Greenwave CVP test failed in the advisories listed below.

Failed Nvrs in advisory [{test_data[0]["errata_id"]}|{get_advisory_link(test_data[0]["errata_id"])}]:
* nvrB ([test_run/{test_data[0]["nvr_id"]}|{get_advisory_link(test_data[0]["errata_id"])}/test_run/{test_data[0]["nvr_id"]}])
* nvrC ([test_run/{test_data[1]["nvr_id"]}|{get_advisory_link(test_data[1]["errata_id"])}/test_run/{test_data[1]["nvr_id"]}])

Failed Nvrs in advisory [{test_data[2]["errata_id"]}|{get_advisory_link(test_data[2]["errata_id"])}]:
* nvrD ([test_run/{test_data[2]["nvr_id"]}|{get_advisory_link(test_data[2]["errata_id"])}/test_run/{test_data[2]["nvr_id"]}])

Failed Nvrs in advisory [{test_data[3]["errata_id"]}|{get_advisory_link(test_data[3]["errata_id"])}]:
* nvrE ([test_run/{test_data[3]["nvr_id"]}|{get_advisory_link(test_data[3]["errata_id"])}/test_run/{test_data[3]["nvr_id"]}])
"""

        jira_description = self.jm._prepare_greenwave_cvp_jira_description(abnormal_tests)
        assert jira_description == expected_description

    def test_is_cvp_issue_reported(self):
        self._mock_jira_with_issues(True)
        assert self.jm.is_cvp_issue_reported()

        self._mock_jira_with_issues(False)
        assert not self.jm.is_cvp_issue_reported()

    def _mock_jira_with_issues(self, issues_present: bool):
        mock_jira = Mock(spec=JIRA)
        result_list = ResultList()
        if issues_present:
            result_list.append(Mock(spec=Issue))
        mock_jira.search_issues.return_value = result_list
        self.jm._svc = mock_jira
