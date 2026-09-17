import unittest
from unittest.mock import patch, MagicMock

from oar.cli.cmd_stage_testing import StageTesting
from oar.core.const import (
    TASK_STAGE_TESTING,
    TASK_STATUS_PASS,
    TASK_STATUS_FAIL,
    TASK_STATUS_INPROGRESS,
    TASK_STATUS_NOT_STARTED,
)


class TestStageTesting(unittest.TestCase):

    def _create_stage_testing(self):
        cs = MagicMock()
        cs.release = "4.19.1"
        with patch("oar.cli.cmd_stage_testing.NotificationManager"), \
             patch("oar.cli.cmd_stage_testing.ShipmentData"), \
             patch("oar.cli.cmd_stage_testing.StateBox"), \
             patch("oar.cli.cmd_stage_testing.Jobs"):
            st = StageTesting(cs)
        return st

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_success(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = {"jobState": "success", "jobURL": "https://prow.ci/123"}

        st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_PASS)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_pending(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = {"jobState": "pending", "jobURL": "https://prow.ci/123"}

        st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_INPROGRESS)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_triggered(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = {"jobState": "triggered", "jobURL": "https://prow.ci/123"}

        st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_INPROGRESS)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_failure(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = {"jobState": "failure", "jobURL": "https://prow.ci/123"}

        st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_FAIL)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_aborted(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = {"jobState": "aborted", "jobURL": "https://prow.ci/123"}

        st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_NOT_STARTED)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_check_job_status_not_found(self, mock_util):
        st = self._create_stage_testing()
        st.jobs.get_job_results.return_value = None

        with self.assertRaises(Exception):
            st.check_job_status("job-abc-123")

        mock_util.log_task_status.assert_called_with(TASK_STAGE_TESTING, TASK_STATUS_FAIL)

    @patch("oar.cli.cmd_stage_testing.util")
    def test_skip_when_already_passed(self, mock_util):
        st = self._create_stage_testing()
        st.statebox.get_task_status.return_value = TASK_STATUS_PASS

        st.trigger_new_job()

        st.jobs.run_stage_testing.assert_not_called()

    @patch("oar.cli.cmd_stage_testing.util")
    def test_skip_when_prow_job_still_running(self, mock_util):
        st = self._create_stage_testing()
        st.statebox.get_task_status.return_value = TASK_STATUS_INPROGRESS
        st.statebox.get_task.return_value = {
            "result": "Triggered stage testing Prow job: job-abc-123"
        }
        st.jobs.get_job_results.return_value = {"jobState": "pending"}

        st.trigger_new_job()

        st.jobs.run_stage_testing.assert_not_called()

    @patch("oar.cli.cmd_stage_testing.util")
    def test_retrigger_when_prow_job_failed(self, mock_util):
        st = self._create_stage_testing()
        st.statebox.get_task_status.return_value = TASK_STATUS_INPROGRESS
        st.statebox.get_task.return_value = {
            "result": "Triggered stage testing Prow job: job-abc-123"
        }
        st.jobs.get_job_results.return_value = {"jobState": "failure"}
        st.sd.is_stage_release_success.return_value = True
        st.jobs.run_stage_testing.return_value = {
            "jobID": "job-def-456",
            "jobURL": "https://prow.ci/456",
        }

        st.trigger_new_job()

        st.jobs.run_stage_testing.assert_called_once()

    @patch("oar.cli.cmd_stage_testing.util")
    def test_skip_when_stage_release_not_success(self, mock_util):
        st = self._create_stage_testing()
        st.statebox.get_task_status.return_value = TASK_STATUS_NOT_STARTED
        st.sd.is_stage_release_success.return_value = False

        st.trigger_new_job()

        st.jobs.run_stage_testing.assert_not_called()

    @patch("oar.cli.cmd_stage_testing.util")
    def test_trigger_success(self, mock_util):
        st = self._create_stage_testing()
        st.statebox.get_task_status.return_value = TASK_STATUS_NOT_STARTED
        st.sd.is_stage_release_success.return_value = True
        st.jobs.run_stage_testing.return_value = {
            "jobID": "job-abc-123",
            "jobURL": "https://prow.ci/123",
        }

        st.trigger_new_job()

        st.jobs.run_stage_testing.assert_called_once_with(
            "quay.io/openshift-release-dev/ocp-release:4.19.1-x86_64"
        )
        st.nm.share_prow_job_url.assert_called_once()
