from dependency_injector import providers
from orglib.main import OrgData
from orglib.container import Container
from orglib.settings import Settings
from orglib.org import OrgField
from orglib.org_models.custom_types import AllowedConfigTypes, AllowedRoleTypes


class Cyborg:

    def __init__(self):
        container = Container()
        container.settings.override(
            providers.Singleton(
                Settings,
                run_jira_checks=False,
                run_ldap_checks=False,
                run_file_checks=False,
                run_google_group_checks=False,
                org_git_url_or_path="git@gitlab.cee.redhat.com:hybrid-platforms/org.git"
            )
        )
        container.gc_manager.override(None)
        container.files_cache.add_kwargs(warm=True)
        org_data = OrgData(container)
        self._teams = org_data.query(
            conditions={
                OrgField.VISUALIZE_GROUPS.value: "ocp",
                OrgField.VISUALIZE.value: True,
                OrgField.TYPE.value: AllowedConfigTypes.team.value,
            }
        )

    def get_manager_ids(self, qa_concact_id: str) -> set[str]:
        return self._get_role_ids(qa_concact_id, AllowedRoleTypes.manager.value)

    def get_team_lead_ids(self, qa_concact_id: str) -> set[str]:
        return self._get_role_ids(qa_concact_id, AllowedRoleTypes.team_lead.value)

    def _get_role_ids(self, qa_concact_id: str, role: str) -> set[str]:
        ids = set()
        for t in self._teams:
            people = t.group.resolved_people
            for p in people:
                if qa_concact_id == p.uid:
                    roles = t.group.resolve_roles
                    for e in roles.get_employees_for_role(role):
                        ids.add(e.uid)
        return ids
