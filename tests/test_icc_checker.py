import unittest
from unittest.mock import patch, MagicMock

from oar.image_consistency_check.checker import ImageConsistencyChecker


class TestImageConsistencyChecker(unittest.TestCase):

    def _create_mock_image_metadata(self, digest='', listdigest='', vcs_ref='', name=''):
        """Helper to create a mock ImageMetadata object."""
        mock = MagicMock()
        mock.digest = digest
        mock.listdigest = listdigest
        mock.vcs_ref = vcs_ref
        mock.name = name
        mock.has_same_identifier = MagicMock(return_value=False)
        mock.has_same_name = MagicMock(return_value=False)
        mock.log_details = MagicMock()
        return mock

    def _create_mock_payload_image(self, name='', pullspec=''):
        """Helper to create a mock PayloadImage object."""
        mock = MagicMock()
        mock.name = name
        mock.pullspec = pullspec
        return mock

    def _create_mock_shipment_component(self, name='', pullspec=''):
        """Helper to create a mock ShipmentComponent object."""
        mock = MagicMock()
        mock.name = name
        mock.pullspec = pullspec
        return mock

    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_create_image_metadata(self, mock_image_metadata_class):
        """Test that image metadata is created for all unique pullspecs."""
        mock_payload = MagicMock()
        payload_image1 = self._create_mock_payload_image(name='image1', pullspec='pullspec1')
        payload_image2 = self._create_mock_payload_image(name='image2', pullspec='pullspec2')
        mock_payload.get_images.return_value = [payload_image1, payload_image2]

        mock_shipment = MagicMock()
        shipment_component1 = self._create_mock_shipment_component(name='component3', pullspec='pullspec3')
        shipment_component2 = self._create_mock_shipment_component(name='component2', pullspec='pullspec2')
        mock_shipment.get_components.return_value = [shipment_component1, shipment_component2]

        mock_image_metadata_class.side_effect = lambda ps: MagicMock(pull_spec=ps)

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)

        # Should create metadata for 3 unique pullspecs (pullspec2 is shared)
        self.assertEqual(mock_image_metadata_class.call_count, 3)
        self.assertIn('pullspec1', checker.all_image_metadata)
        self.assertIn('pullspec2', checker.all_image_metadata)
        self.assertIn('pullspec3', checker.all_image_metadata)

    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_payload_image_in_shipment_found(self, mock_image_metadata_class):
        """Test that payload image is found in shipment when identifiers match."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]

        mock_shipment = MagicMock()
        shipment_component = self._create_mock_shipment_component(name='shipment_component', pullspec='shipment_pullspec')
        mock_shipment.get_components.return_value = [shipment_component]

        payload_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        shipment_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        payload_metadata.has_same_identifier.return_value = True

        mock_image_metadata_class.side_effect = lambda ps: payload_metadata if 'payload' in ps else shipment_metadata

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_payload_image_in_shipment(payload_image)

        self.assertTrue(result)

    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_payload_image_in_shipment_not_found(self, mock_image_metadata_class):
        """Test that payload image is not found in shipment when identifiers don't match."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]

        mock_shipment = MagicMock()
        shipment_component = self._create_mock_shipment_component(name='shipment_component', pullspec='shipment_pullspec')
        mock_shipment.get_components.return_value = [shipment_component]

        payload_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        shipment_metadata = self._create_mock_image_metadata(digest='sha256:def456')
        payload_metadata.has_same_identifier.return_value = False

        mock_image_metadata_class.side_effect = lambda ps: payload_metadata if 'payload' in ps else shipment_metadata

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_payload_image_in_shipment(payload_image)

        self.assertFalse(result)

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_payload_image_released_found(self, mock_image_metadata_class, mock_requests_get):
        """Test that payload image is found in Red Hat catalog."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]
        mock_shipment = MagicMock()
        mock_shipment.get_components.return_value = []

        payload_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        mock_image_metadata_class.return_value = payload_metadata

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'total': 1,
            'data': [{'repositories': [{'registry': 'registry.redhat.io', 'repository': 'openshift4/ose-cli'}]}]
        }
        mock_requests_get.return_value = mock_response

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_payload_image_released(payload_image)

        self.assertTrue(result)
        mock_requests_get.assert_called_once()

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_payload_image_released_not_found(self, mock_image_metadata_class, mock_requests_get):
        """Test that payload image is not found in Red Hat catalog."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]
        mock_shipment = MagicMock()
        mock_shipment.get_components.return_value = []

        payload_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        mock_image_metadata_class.return_value = payload_metadata

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {'total': 0, 'data': []}
        mock_requests_get.return_value = mock_response

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_payload_image_released(payload_image)

        self.assertFalse(result)

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_payload_image_released_api_error(self, mock_image_metadata_class, mock_requests_get):
        """Test that API error returns False."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]
        mock_shipment = MagicMock()
        mock_shipment.get_components.return_value = []

        payload_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        mock_image_metadata_class.return_value = payload_metadata

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.reason = 'Internal Server Error'
        mock_requests_get.return_value = mock_response

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_payload_image_released(payload_image)

        self.assertFalse(result)

    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_find_images_with_same_name(self, mock_image_metadata_class):
        """Test that images with same name are found."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='payload_image', pullspec='payload_pullspec')
        mock_payload.get_images.return_value = [payload_image]

        mock_shipment = MagicMock()
        shipment_component = self._create_mock_shipment_component(name='shipment_component', pullspec='shipment_pullspec')
        mock_shipment.get_components.return_value = [shipment_component]

        payload_metadata = self._create_mock_image_metadata(name='openshift/ose-cli')
        shipment_metadata = self._create_mock_image_metadata(name='openshift/ose-cli')
        payload_metadata.has_same_name.return_value = True

        mock_image_metadata_class.side_effect = lambda ps: payload_metadata if 'payload' in ps else shipment_metadata

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        checker._find_images_with_same_name(payload_image)

        shipment_metadata.log_details.assert_called()

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_consistent_all_in_shipment(self, mock_image_metadata_class, mock_requests_get):
        """Test that is_consistent returns True when all images are in shipment."""
        mock_payload = MagicMock()
        payload_image1 = self._create_mock_payload_image(name='image1', pullspec='payload1')
        payload_image2 = self._create_mock_payload_image(name='image2', pullspec='payload2')
        mock_payload.get_images.return_value = [payload_image1, payload_image2]

        mock_shipment = MagicMock()
        shipment_component1 = self._create_mock_shipment_component(name='component1', pullspec='shipment1')
        shipment_component2 = self._create_mock_shipment_component(name='component2', pullspec='shipment2')
        mock_shipment.get_components.return_value = [shipment_component1, shipment_component2]

        mock_metadata = self._create_mock_image_metadata()
        mock_metadata.has_same_identifier.return_value = True
        mock_image_metadata_class.return_value = mock_metadata

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker.is_consistent()

        self.assertTrue(result)

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_consistent_all_in_catalog(self, mock_image_metadata_class, mock_requests_get):
        """Test that is_consistent returns True when all images are in Red Hat catalog."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='image1', pullspec='payload1')
        mock_payload.get_images.return_value = [payload_image]

        mock_shipment = MagicMock()
        mock_shipment.get_components.return_value = []

        mock_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        mock_metadata.has_same_identifier.return_value = False
        mock_image_metadata_class.return_value = mock_metadata

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'total': 1,
            'data': [{'repositories': [{'registry': 'registry.redhat.io', 'repository': 'openshift4/ose-cli'}]}]
        }
        mock_requests_get.return_value = mock_response

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker.is_consistent()

        self.assertTrue(result)

    @patch('oar.image_consistency_check.checker.requests.get')
    @patch('oar.image_consistency_check.checker.ImageMetadata')
    def test_is_consistent_not_found(self, mock_image_metadata_class, mock_requests_get):
        """Test that is_consistent returns False when image is not found anywhere."""
        mock_payload = MagicMock()
        payload_image = self._create_mock_payload_image(name='image1', pullspec='payload1')
        mock_payload.get_images.return_value = [payload_image]

        mock_shipment = MagicMock()
        shipment_component = self._create_mock_shipment_component(name='component1', pullspec='shipment1')
        mock_shipment.get_components.return_value = [shipment_component]

        mock_metadata = self._create_mock_image_metadata(digest='sha256:abc123')
        mock_metadata.has_same_identifier.return_value = False
        mock_metadata.has_same_name.return_value = False
        mock_image_metadata_class.return_value = mock_metadata

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {'total': 0, 'data': []}
        mock_requests_get.return_value = mock_response

        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker.is_consistent()

        self.assertFalse(result)

    def test_is_shipment_payload_version_same_check_version_false_equal(self):
        """Test that is_shipment_payload_version_same returns True when versions are the same."""
        mock_payload = MagicMock()
        mock_payload.version = '4.16.55'
        mock_shipment = MagicMock()
        mock_shipment.version = '4.16.55'
        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_shipment_payload_version_same(mock_payload, mock_shipment)
        self.assertTrue(result)

    def test_is_shipment_payload_version_same_check_version_true_not_equal(self):
        """Test that is_shipment_payload_version_same returns False when versions are not the same."""
        mock_payload = MagicMock()
        mock_payload.version = '4.16.55'
        mock_shipment = MagicMock()
        mock_shipment.version = '4.16.56'
        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=False)
        result = checker._is_shipment_payload_version_same(mock_payload, mock_shipment)
        self.assertFalse(result)

    def test_is_shipment_payload_version_same_check_version_true_error(self):
        """Test that is_shipment_payload_version_same raises an error when versions are not the same."""
        mock_payload = MagicMock()
        mock_payload.version = '4.16.55'
        mock_shipment = MagicMock()
        mock_shipment.version = '4.16.56'
        with self.assertRaises(ValueError):
            ImageConsistencyChecker(mock_payload, mock_shipment, check_version=True)
            

    def test_is_shipment_payload_version_same_check_version_true(self):
        """Test that is_shipment_payload_version_same returns True when versions are the same."""
        mock_payload = MagicMock()
        mock_payload.version = '4.16.55'
        mock_shipment = MagicMock()
        mock_shipment.version = '4.16.55'
        checker = ImageConsistencyChecker(mock_payload, mock_shipment, check_version=True)
        # no error should be raised
        result = checker._is_shipment_payload_version_same(mock_payload, mock_shipment)
        self.assertTrue(result)
