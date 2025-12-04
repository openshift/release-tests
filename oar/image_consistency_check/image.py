import json
import logging
import re
import subprocess


class OpenshiftImage:

    def __init__(self, pull_spec, **kwargs):
        logging.debug(f'OpenshiftImage: initial image {pull_spec}')
        self.pull_spec = pull_spec
        self.digest = ""
        self.listdigest = ""
        self.metadata = None
        self.build_commit_id = ""
        self.name = ""
        self.release = ""
        self.version = ""
        self.vcs_ref = ""
        self.tag = ""

        for key, value in kwargs.items():
            setattr(self, key, value)

        self._set_image_info()

    def _set_image_info(self):
        self._guess_image_info()
        self._get_image_metadata()
        if self.metadata:
            self._set_image_using_metadata()

    def _guess_image_info(self):
        if self.digest:
            m1 = re.match(r'.*@(sha256:\w{64})', self.digest)
            if m1:
                self.digest = m1.group(1)
            else:
                self.digest = ""

        if self.listdigest:
            m2 = re.match(r'.*@(sha256:\w{64})', self.listdigest)
            if m2:
                self.listdigest = m2.group(1)
            else:
                self.listdigest = ""

        # Guess digest
        m3 = re.match(r'.*@(sha256:\w{64})', self.pull_spec)
        if m3:
            if self.listdigest == "":
                self.listdigest = m3.group(1)
            if self.digest == "":
                self.digest = m3.group(1)

        m4 = re.match(r'registry-proxy.engineering.redhat.com/rh-osbs/openshift-(.*)@sha256:\w{64}', self.pull_spec)
        if m4:
            self.name = m4.group(1)
        m5 = re.match(r'registry-proxy.engineering.redhat.com/rh-osbs/openshift-(.*):v.*', self.pull_spec)
        if m5:
            self.name = m5.group(1)

        m6 = re.match(r'.*openshift4/(.*)@sha256:\w{64}', self.pull_spec)
        if m6:
            self.name = m6.group(1)
        m7 = re.match(r'.*openshift4/(.*):v.*', self.pull_spec)
        if m7:
            self.name = m7.group(1)

        m8 = re.match(r'.*:(v.*)', self.pull_spec)
        if m8:
            self.tag = m8.group(1)

    def _set_image_using_metadata(self):
        self.digest = self.metadata.get('digest', self.digest)
        self.listdigest = self.metadata.get('listDigest', self.listdigest)

        try:
            self.name = self.metadata['config']['config']['Labels']['name']
            self.release = self.metadata['config']['config']['Labels']['release']
            self.version = self.metadata['config']['config']['Labels']['version']
            self.vcs_ref = self.metadata['config']['config']['Labels']['vcs-ref']
            self.build_commit_id = self.metadata['config']['config']['Labels']['io.openshift.build.commit.id']
            self.tag = f"{self.version}-{self.release}"
        except KeyError:
            pass

        return True

    def _get_image_metadata(self):
        image_url = self.pull_spec
        # Use registry-proxy.engineering.redhat.com as proxy to get image info
        if self.pull_spec.startswith("image-registry.openshift-image-registry.svc:5000"):
            image_url = self.pull_spec.replace(
                r"image-registry.openshift-image-registry.svc:5000/openshift/",
                "registry-proxy.engineering.redhat.com/rh-osbs/openshift-"
            )

        logging.debug(f"OpenshiftImage: oc image info {image_url}")
        (status, output) = subprocess.getstatusoutput(
            f"oc image info --filter-by-os linux/amd64 -o json --insecure=true {image_url} 2>/tmp/stderr.out"
        )
        if status == 0:
            self.metadata = json.loads(output)
        else:
            logging.warning(f"OpenshiftImage: oc image info {self.pull_spec} Return code: {status}")
            logging.warning(f"Stderr: {subprocess.getoutput('cat /tmp/stderr.out')}")
            return None

    def __eq__(self, other):
        """Overrides the default implementation"""
        if self.listdigest != "" and self.listdigest == other.listdigest:
            return True
        if self.digest != "" and self.digest == other.digest:
            return True
        if self.vcs_ref != "" and self.vcs_ref == other.vcs_ref:
            return True
        return False
