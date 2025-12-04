import logging
import re
import subprocess
import sys
import click
import requests

from oar.image_consistency_check.image import OpenshiftImage
from oar.image_consistency_check.payload import Payload
from oar.image_consistency_check.shipment import Shipment


logger = logging.getLogger(__name__)


class ImageConsistencyChecker:
    def __init__(self):
        self.all_openshift_images = {}

    def is_image_exist_in_list(self, image_to_check, images_list):

        test_result = {"name": image_to_check, "status": "WAIT", "desc": ""}
        status = "PASS"
        reason = "Unknown"
        detail = []

        #return PASS when image is found in registry.redhat.io
        if (re.match(r'registry.redhat.io.*',image_to_check)):
            (status, output) = subprocess.getstatusoutput("oc image info --filter-by-os linux/amd64  -o json --insecure=true {} 2>/tmp/stderr.out".format(image_to_check))
            if status==0:
                test_result["status"] = "PASS"
                test_result["desc"] = "Found product image"
                return test_result
            else:
                image_to_check=image_to_check.replace(r"registry.redhat.io", "brew.registry.redhat.io")

        if (image_to_check not in self.all_openshift_images.keys()):
            self.all_openshift_images[image_to_check] = OpenshiftImage(image_to_check)
            print("#####", self.all_openshift_images[image_to_check].digest, "#####")

        for image_pullspec in images_list:
            if (image_pullspec not in self.all_openshift_images.keys()):
                self.all_openshift_images[image_pullspec] = OpenshiftImage(
                    image_pullspec)

        match_images = []
        for image_pullspec in images_list:
            # Compare image using digest ids. We had overwritten the method __eq__. For more detail,refer the __eq__ in class OpenshiftImage
            if (self.all_openshift_images[image_pullspec] == self.all_openshift_images[image_to_check]):
                match_images.append(image_pullspec)

        if (len(match_images) > 0):
            status = "PASS"
            if (len(match_images) == 1):
                reason = "Found same image"
            else:
                reason = "Found more than one same images in Advisory"

            for image_pullspec in match_images:
                detail.append("pull_spec: " + image_to_check + " <==> " + image_pullspec)
                detail.append("digest: " + self.all_openshift_images[image_to_check].digest)
                detail.append("listdigest: " + self.all_openshift_images[image_to_check].listdigest)
                detail.append("src_commit ID: " + self.all_openshift_images[image_to_check].build_commit_id)
                detail.append( "vcs-ref: " + self.all_openshift_images[image_to_check].vcs_ref)
                detail.append("tag  :" + self.all_openshift_images[image_to_check].tag)
        else:
            # check if the image_to_check had been released. make status "PASS" too
            status = "FAIL"
            name_same = False
            
            image = self.all_openshift_images[image_to_check]
            digest = image.digest
            release = image.release
            # query images from pyxis.engineering.redhat.com.
            url = f"https://catalog.redhat.com/api/containers/v1/images?filter=image_id=={digest}'"
            resp = requests.get(url)
            
            if resp.ok:
                json = resp.json()
                if json["total"] > 0:
                    reason = f"This image isn't attached to advisories, but can be found in"
                    for item in json["data"]:
                        # reference is like registry.redhat.io/openshift4/ose-cluster-baremetal-operator-rhel9:v4.15.0-202407080939.p0.gfdce2d0.assembly.stream.el9
                        ref = item["reference"]
                        if release in ref:
                            logging.info(
                                f"image {image_to_check} is already shipped: {ref}"
                            )
                            status = "PASS"
                            reason += f" {ref.split('/')[0]} "
                else:
                    logging.error(
                        f"cannot find image {image_to_check} in redhat ecosystem catalog"
                    )
            else:
                logging.error(f"access pyxis failed: {resp.status_code}:{resp.reason}")
                
            if status == "FAIL":
                # if status FAIL, report reason
                for image_pullspec in images_list:
                    if (self.all_openshift_images[image_to_check].name != "" and self.all_openshift_images[image_to_check].name == self.all_openshift_images[image_pullspec].name):
                        name_same = True
                        detail.append("pull_spec: " + image_to_check +
                                    " != " + image_pullspec)
                        detail.append(
                            "digest: " + self.all_openshift_images[image_to_check].digest + " <==> " + self.all_openshift_images[image_pullspec].digest)
                        detail.append(
                            "listdigest: " + self.all_openshift_images[image_to_check].listdigest + " <==> " + self.all_openshift_images[image_pullspec].listdigest)
                        detail.append(
                            "src_commit ID: " + self.all_openshift_images[image_to_check].build_commit_id + "< ==> " + self.all_openshift_images[image_pullspec].build_commit_id)
                        detail.append(
                            "vcs-ref: " + self.all_openshift_images[image_to_check].vcs_ref + "< ==> " + self.all_openshift_images[image_pullspec].vcs_ref)
                        detail.append(
                            "tag: " + self.all_openshift_images[image_to_check].tag + " <==> " + self.all_openshift_images[image_pullspec].tag)

                if (name_same):
                    reason = "Find a image with same name, but the verison is different, please checking manually ....."
                else:
                    reason = "Couldn't find this image on either advisory or registry.redhat.io. please checking manually....."
                    detail.append("pull_spec: " + image_to_check + " != None")
                    detail.append(
                        "digest: " + self.all_openshift_images[image_to_check].digest)
                    detail.append("listdigest: " +
                                self.all_openshift_images[image_to_check].listdigest)
                    detail.append(
                        "src_commit ID :" + self.all_openshift_images[image_to_check].build_commit_id)
                    detail.append(
                        "vcs-ref: " + self.all_openshift_images[image_to_check].vcs_ref)
                    detail.append(
                        "tag  :" + self.all_openshift_images[image_to_check].tag)

        test_result["status"] = status
        test_result["desc"] = reason + "\n" + "\n".join(detail)
        return test_result

@click.command()
@click.option("-p", "--payload-url", type=str, required=True, help="Payload URL")
@click.option("-m", "--mr-id", type=int, required=True, help="Merge request ID")
def image_consistency_check(payload_url: str, mr_id: int) -> None:

    checker = ImageConsistencyChecker()
    payload = Payload(payload_url)
    shipment = Shipment(mr_id)
    shipment_images = shipment.get_image_pullspecs()

    payload_results = []
    for payload_image in payload.images:
        logging.info(f"Checking {payload_image}")
        result = checker.is_image_exist_in_list(payload_image, shipment_images)
        payload_results.append(result)

    for result in payload_results:
        if result['status'] == 'FAIL':
            logging.error(f"There are images that are not found in the shipment.")
            sys.exit(1)
    logging.info("All images are found in the shipment.")
    sys.exit(0)

if __name__ == "__main__":
    image_consistency_check()