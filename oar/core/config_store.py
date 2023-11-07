import requests
import json
import yaml
import os
import logging
import oar.core.util as util
from oar.core.exceptions import ConfigStoreException
from oar.core.const import *
from requests.exceptions import RequestException
from yaml import YAMLError

# get module level logger
logger = logging.getLogger(__name__)


class ConfigStore:
    """
    Config Store object will be used in other modules to retrieve
    release data and app level config settings. e.g. advisories, builds etc.

    cs = ConfigStore("4.12.11")
    ads = cs.get_advisories()

    """

    def __init__(self, release):
        if release == "":
            raise ConfigStoreException("argument release is required")

        if not util.is_valid_z_release(release):
            raise ConfigStoreException(
                f"invalid zstream release format {release}")

        self.release = release

        # load local config file
        path = os.path.dirname(__file__) + "/config_store.json"
        with open(path) as f:
            self._local_conf = json.load(f)

        # download ocp build data with release branch e.g. openshift-4.12
        branch = "openshift-%s" % util.get_y_release(self.release)
        url = self._local_conf["build_data_url"] % branch

        try:
            response = requests.get(url)
            response.raise_for_status()
        except RequestException as re:
            raise ConfigStoreException(
                "download ocp build data failed") from re

        if response.text:
            try:
                self._build_data = yaml.safe_load(response.text)
            except yaml.YAMLError as ye:
                raise ConfigStoreException(
                    "ocp build data format is invalid") from ye

        if self.release in self._build_data["releases"]:
            self._assembly = self._build_data["releases"][self.release]["assembly"]
        else:
            raise ConfigStoreException(
                f"[{self.release}] ocp build data is not ready you can check file:{url}")

    def get_advisories(self):
        """
        Get advisories info from build data e.g.
        group:
            advisories:
                extras: 113027
                image: 113026
                metadata: 113028
                rpm: 113025
        """
            
        return self._get_assembly_attr("group/advisories")

    def get_candidate_builds(self):
        """
        Get candidate nightly builds from build data e.g.

        basis:
            reference_releases:
                aarch64: 4.12.0-0.nightly-arm64-2023-04-18-151008
                ppc64le: 4.12.0-0.nightly-ppc64le-2023-04-18-151003
                s390x: 4.12.0-0.nightly-s390x-2023-04-18-151005
                x86_64: 4.12.0-0.nightly-2023-04-18-151010

        """
        # https://art-docs.engineering.redhat.com/assemblies/#building-an-updated-component
        # according to above doc, it is possible that `reference_releases` can be removed from the yaml
        # if it is true, return a empty dict instead
        
        return self._get_assembly_attr("basis/reference_releases")

    def get_jira_ticket(self):
        """
        Get JIRA ticket created by ART team e.g.
        group:
            release_jira: ART-6626
        """
        return self._assembly["group"]["release_jira"]

    def set_jira_ticket(self, key):
        """
        Overwrite default jira ticket

        Args:
            key (str): jira ticket created by art team
        """
        self._assembly["group"]["release_jira"] = key

    def get_owner(self):
        """
        Get advisory owner setting from local config
        """
        o = self._local_conf["owners"]
        yr = util.get_y_release(self.release)
        # check version exists in owner settings, if no, return default instead
        if yr not in o.keys():
            return o["default"]
        else:
            return o[yr]

    def set_owner(self, email):
        """
        Overwrite owner
        """
        o = self._local_conf["owners"]
        yr = util.get_y_release(self.release)
        o[yr] = email

    def get_slack_contact(self, team):
        """
        Get slack contact for different teams e.g. 'qe', 'art'
        """
        slack_contacts = self._local_conf["contacts"]["slack"]
        # validate team name
        if team and team not in slack_contacts.keys():
            raise ConfigStoreException(
                f"there is no slack contact found for team {team}"
            )

        return slack_contacts[team]

    def get_slack_channel_from_contact(self, contact):
        """
        Get slack channel name from contact

        Args:
            contact (str): contact name e.g. qe

        Returns:
            str: slack channel name
        """
        return self.get_slack_contact(contact)["channel"]

    def get_slack_user_group_from_contact_by_id(self, contact):
        """
        Get slack user/group name from contact

        Args:
            contact (str): contact name e.g. qe

        Returns:
            str: slack user/group name
        """
        return self.get_slack_user_group_from_contact(contact, "id")

    def get_slack_user_group_from_contact(self, contact, attribute):
        """
        Get slack user/group name from contact by json attribute

        Args:
            contact (str): contact name
            attribute (str): json attribute name

        Returns:
            str: slack user/group name
        """
        return self.get_slack_contact(contact)[attribute]

    def get_email_contact(self, team):
        """
        Get email contact for different teams e.g. 'qe','art'
        """
        email_contacts = self._local_conf["contacts"]["email"]
        # validate team name
        if team and team not in email_contacts.keys():
            raise ConfigStoreException(
                f"there is no email contact found for team {team}"
            )

        return email_contacts[team]

    def get_prodsec_id(self):
        """
        Get prodsec email from local config
        """
        return self._local_conf["contacts"]["slack"]["approver"]["prodsec_id"]

    def get_report_template(self):
        """
        Get test report template doc id, every minor release
        has its own report template file
        """
        templates = self._local_conf["report_templates"]
        yr = util.get_y_release(self.release)
        if yr not in templates.keys():
            raise ConfigStoreException(f"this is no template found for {yr}")

        return templates[yr]

    def get_jira_server(self):
        """
        Get jira server url
        """
        return self._local_conf["jira_server"]

    def get_jira_token(self):
        """
        Get jira token from env var JIRA_TOKEN
        """
        return self._get_env_var(ENV_VAR_JIRA_TOKEN)

    def get_jenkins_server(self):
        """
        Get jenkins server url
        """
        return self._local_conf["jenkins_server"]

    def get_jenkins_username(self):
        """
        Get jenkins username
        """
        return self._get_env_var(ENV_JENKINS_USER)

    def get_jenkins_token(self):
        """
        Get jenkins user token
        """
        return self._get_env_var(ENV_JENKINS_TOKEN)

    def get_google_sa_file(self):
        """
        Get google service account file path
        """

        return self._get_env_var(ENV_VAR_GCP_SA_FILE)

    def get_slack_bot_token(self):
        """
        Get slack bot token
        """
        return self._get_env_var(ENV_VAR_SLACK_BOT_TOKEN)

    def get_slack_app_token(self):
        """
        Get slack app token
        """
        return self._get_env_var(ENV_VAR_SLACK_APP_TOKEN)

    def get_google_app_passwd(self):
        """
        Get google account application password
        """
        return self._get_env_var(ENV_APP_PASSWD)

    def get_release_url(self):
        """
        Get release url
        """
        return self._local_conf["release_url"]

    def get_signature_url(self):
        """
        Get release url
        """
        return self._local_conf["signature_url"]

    def _get_env_var(self, var):
        """
        Internal func to get value of environment variable
        if not found, throw exception

        Args:
            var (str): system environment variable name
        """
        val = os.environ.get(var)
        if not val:
            raise ConfigStoreException(
                f"system environment variable {var} not found")

        return val
    
    def _get_assembly_attr(self, keypath):
        """
        Get attribute with key names followed inheritance rule
        
        e.g. if advisory! or advisories does not exist in 4.14.1, 
        we should get advisory's from parent assembly i.e. 4.14.0

        Args:
            key (_str_): attribute key name
        """
        attr_val = None
        basis = self._assembly["basis"]
        parent_assembly = self._get_value_by_path(self._build_data["releases"], f"{basis['assembly']}/assembly")
        child_keypath = "%s!" % keypath
        
        attr_val = self._get_value_by_path(self._assembly, child_keypath)
        if attr_val == None: # no child key found, i.e. suffixed with !
            attr_val = self._get_value_by_path(self._assembly, keypath)
        if attr_val == None and parent_assembly: # no key found, try to get it from parent assembly
            attr_val = self._get_value_by_path(parent_assembly, keypath)
            
        return attr_val
            
    def _get_value_by_path(self, json, path):
        """
        Get value from json path delimited by slash
        e.g. releases/4.1.4.1/assembly

        Args:
            path (_str_): attribute path based on current json object
        """
        tmp = json
        if tmp:
            for key in path.split("/"):
                if key in tmp:
                    tmp = tmp[key]
                else:
                    logger.debug(f"cannot find key {key} in json object {tmp}")
                    return None
        
        return tmp
                
                
        
            
            
        
        

