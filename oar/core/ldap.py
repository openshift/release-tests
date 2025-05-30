import logging
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException
from ldap3.utils.dn import parse_dn

logger = logging.getLogger(__name__)


class LdapHelper:
    """
    Helper class is used to acquire data from LDAP server.
    """

    MANAGER = "manager"
    PRIMARY_MAIL = "rhatPrimaryMail"
    UID = "uid"

    def __init__(self):
        self.server = Server("ldaps://ldap.corp.redhat.com", get_info=ALL)

    def get_manager_email(self, user_email: str) -> str:
        """
        Get manager email for specified user email

        Args:
            user_email (str): User primary email

        Returns:
            str: Found manager email for specified user email
        """

        manager_id = self._get_manager_id(user_email)
        return self._get_user_email(manager_id)

    def get_group_members_emails(self, group_name: str) -> set[str]:
        """
        Get emails of all members in the specified group.

        Args:
            group_name (str): Name of group

        Returns:
            set[str]: Emails of group members
        """

        members = set()

        try:
            conn = Connection(self.server, auto_bind=True)
            conn.search(
                search_base="dc=redhat,dc=com",
                search_filter=f"(memberOf=cn={group_name},ou=adhoc,ou=managedGroups,dc=redhat,dc=com)",
                search_scope=SUBTREE,
                attributes=[LdapHelper.PRIMARY_MAIL],
            )

            for entry in conn.entries:
                if LdapHelper.PRIMARY_MAIL in entry:
                    members.add(entry[LdapHelper.PRIMARY_MAIL].value)
        except LDAPException as e:
            logger.error(f"LDAP connection failed: {e}")
        finally:
            if conn:
                conn.unbind()

        return members

    def _get_manager_id(self, user_email: str):
        """
        Get manager id for specified user email

        Args:
            user_email (str): User primary email

        Returns:
            str: Found manager id for specified user email
        """
        manager_id = None

        try:
            conn = Connection(self.server, auto_bind=True)
            conn.search(
                search_base="dc=redhat,dc=com",
                search_filter=f"({LdapHelper.PRIMARY_MAIL}={user_email})",
                search_scope=SUBTREE,
                attributes=[LdapHelper.MANAGER],
            )

            if conn.entries:
                entry = conn.entries[0]
                if LdapHelper.MANAGER in entry:
                    dn = parse_dn(entry[LdapHelper.MANAGER].value)
                    for attr, value, _ in dn:
                        if attr == LdapHelper.UID:
                            manager_id = value
                            break
        except LDAPException as e:
            logger.error(f"LDAP connection failed: {e}")
        finally:
            if conn:
                conn.unbind()

        return manager_id

    def _get_user_email(self, user_id: str) -> str:
        """
        Get user email for specified user id

        Args:
            user_id (str): User id

        Returns:
            str: Found user email for specified user id
        """

        user_email = None

        try:
            conn = Connection(self.server, auto_bind=True)
            conn.search(
                search_base="dc=redhat,dc=com",
                search_filter=f"({LdapHelper.UID}={user_id})",
                search_scope=SUBTREE,
                attributes=[LdapHelper.PRIMARY_MAIL],
            )

            if conn.entries:
                entry = conn.entries[0]
                if LdapHelper.PRIMARY_MAIL in entry:
                    user_email = entry[LdapHelper.PRIMARY_MAIL].value

        except LDAPException as e:
            logger.error(f"LDAP connection failed: {e}")
        finally:
            if conn:
                conn.unbind()

        return user_email
