"""Staff RBAC permission identifiers."""

STAFF_READ = "staff:read"
STAFF_CREATE = "staff:create"
STAFF_UPDATE = "staff:update"
STAFF_ACTIVATE = "staff:activate"

ROLE_READ = "role:read"
ROLE_CREATE = "role:create"
ROLE_UPDATE = "role:update"
ROLE_DELETE = "role:delete"

LOAN_READ = "loan:read"
LOAN_REVIEW = "loan:review"
LOAN_VERIFY_DOCS = "loan:verify_documents"
LOAN_DISBURSE = "loan:disburse"
LOAN_CONFIGURE_WORKFLOW = "loan:configure_workflow"
LOAN_RECORD_REPAYMENT = "loan:record_repayment"

PAYMENT_READ = "payment:read"

SUPPORT_READ = "support:read"
SUPPORT_RESPOND = "support:respond"

INVESTMENT_READ = "investment:read"
INVESTMENT_MANAGE = "investment:manage"

ALL_PERMISSIONS: tuple[str, ...] = (
    STAFF_READ,
    STAFF_CREATE,
    STAFF_UPDATE,
    STAFF_ACTIVATE,
    ROLE_READ,
    ROLE_CREATE,
    ROLE_UPDATE,
    ROLE_DELETE,
    LOAN_READ,
    LOAN_REVIEW,
    LOAN_VERIFY_DOCS,
    LOAN_DISBURSE,
    LOAN_CONFIGURE_WORKFLOW,
    LOAN_RECORD_REPAYMENT,
    PAYMENT_READ,
    SUPPORT_READ,
    SUPPORT_RESPOND,
    INVESTMENT_READ,
    INVESTMENT_MANAGE,
)

SUPER_ADMIN_ROLE_NAME = "Super Admin"
