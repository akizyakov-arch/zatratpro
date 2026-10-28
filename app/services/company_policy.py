"""Platform-independent company roles and access error."""
MANAGER_ROLE = "manager"
EMPLOYEE_ROLE = "employee"
MASTER_ROLE = "master"
ADMIN_ROLES = {MANAGER_ROLE}
WORKER_ROLES = {EMPLOYEE_ROLE}
VALID_MEMBER_ROLES = {MANAGER_ROLE, EMPLOYEE_ROLE, MASTER_ROLE}
EMPLOYEE_LIMIT = 10
INVITE_TTL_HOURS = 72


class CompanyAccessError(RuntimeError):
    pass


