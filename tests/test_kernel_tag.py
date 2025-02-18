import unittest

from oar.core.advisory import Advisory

class TestKernelTag(unittest.TestCase):
    def test_kernel_tag(self):
       Advisory(errata_id=144853, impetus='image').check_kernel_tag()
       Advisory(errata_id=144854, impetus='metadata').check_kernel_tag()
