import unittest

from oar.core.advisory import Advisory, AdvisoryManager
from oar.core.configstore import ConfigStore
from oar.core.exceptions import AdvisoryException

class TestAdvisoryGrade(unittest.TestCase):
    def test_overall_grade(self):
        self.assertEqual("B", Advisory(errata_id=140504).get_overall_grade())
        self.assertEqual("F", Advisory(errata_id=140505).get_overall_grade())
        self.assertEqual("A", Advisory(errata_id=140506).get_overall_grade())
        self.assertRaises(AdvisoryException, Advisory(errata_id=140508).get_overall_grade)

    def test_build_grades(self):
        ad = Advisory(errata_id=140505)

        a_nvr = "ironic-agent-container-v4.14.0-202410241808.p0.ge839a4e.assembly.stream.el9"
        a_grades = ad.get_build_grades(a_nvr)
        self.assertEqual(2, len(a_grades))

        self.assertEqual(a_nvr, a_grades[0]["nvr"])
        self.assertEqual("A", a_grades[0]["grade"])
        self.assertEqual("arm64", a_grades[0]["arch"])

        self.assertEqual(a_nvr, a_grades[1]["nvr"])
        self.assertEqual("A", a_grades[1]["grade"])
        self.assertEqual("amd64", a_grades[1]["arch"])

        b_nvr = "ose-gcp-cloud-controller-manager-container-v4.14.0-202410182001.p0.g09e96a9.assembly.stream.el8"
        b_grades = ad.get_build_grades(b_nvr)
        self.assertEqual(3, len(b_grades))

        self.assertEqual(b_nvr, b_grades[0]["nvr"])
        self.assertEqual("B", b_grades[0]["grade"])
        self.assertEqual("amd64", b_grades[0]["arch"])

        self.assertEqual(b_nvr, b_grades[1]["nvr"])
        self.assertEqual("B", b_grades[1]["grade"])
        self.assertEqual("arm64", b_grades[1]["arch"])

        self.assertEqual(b_nvr, b_grades[2]["nvr"])
        self.assertEqual("B", b_grades[2]["grade"])
        self.assertEqual("ppc64le", b_grades[2]["arch"])

    def test_all_advisories_grades_healthy(self):
        am = AdvisoryManager(ConfigStore("4.14.40"))
        unhealthy_advisories = am.check_advisories_grades_health()

        self.assertEqual(1, len(unhealthy_advisories))

        builds = unhealthy_advisories[0]["unhealthy_builds"]

        self.assertEqual(140505, unhealthy_advisories[0]["errata_id"])
        self.assertEqual("F", unhealthy_advisories[0]["ad_grade"])
        self.assertEqual(4, len(builds))

        self.assertEqual("ose-ovn-kubernetes-container-v4.14.0-202410300909.p0.geb3869e.assembly.stream.el9", builds[0]["nvr"])
        self.assertEqual("F", builds[0]["grade"])
        self.assertEqual("s390x", builds[0]["arch"])

        self.assertEqual("ose-ovn-kubernetes-container-v4.14.0-202410300909.p0.geb3869e.assembly.stream.el9", builds[1]["nvr"])
        self.assertEqual("F", builds[1]["grade"])
        self.assertEqual("ppc64le", builds[1]["arch"])

        self.assertEqual("ose-ovn-kubernetes-container-v4.14.0-202410300909.p0.geb3869e.assembly.stream.el9", builds[2]["nvr"])
        self.assertEqual("F", builds[2]["grade"])
        self.assertEqual("arm64", builds[2]["arch"])

        self.assertEqual("ose-ovn-kubernetes-container-v4.14.0-202410300909.p0.geb3869e.assembly.stream.el9", builds[3]["nvr"])
        self.assertEqual("F", builds[3]["grade"])
        self.assertEqual("amd64", builds[3]["arch"])
