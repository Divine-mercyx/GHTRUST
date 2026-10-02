"""Side-effect imports so Alembic sees all mapped tables."""

from app.modules.auth.models import AuthSession, CustomerDevice, DeviceApproval, SelfieAttempt  # noqa: F401

from app.modules.contributions.models import (  # noqa: F401
    ContributionGroup,
    GroupContribution,
    GroupMember,
)
from app.modules.food_basket.models import (  # noqa: F401
    FoodBasketDelivery,
    FoodBasketPlan,
    FoodBasketSubscription,
)
from app.modules.investments.models import CustomerInvestment, InvestmentPlan  # noqa: F401
from app.modules.payments.models import (  # noqa: F401
    CustomerWallet,
    LedgerEntry,
    LedgerJournal,
    LoanDisbursement,
    PaymentTransaction,
    ProcessedWebhookEvent,
    WithdrawalRequest,
)
from app.modules.loans.models import (  # noqa: F401
    ApplicationCollateral,
    ApplicationDocument,
    ApplicationGuarantor,
    ApplicationStatusLog,
    Loan,
    LoanApplication,
    LoanDraft,
    LoanProduct,
    LoanRepayment,
    RepaymentSchedule,
)
from app.modules.loans.workflow_models import (  # noqa: F401
    ApplicationAuditLog,
    ApplicationStageDecision,
    LoanWorkflow,
    LoanWorkflowStage,
)
from app.modules.savings.models import SavingsAccount, SavingsProduct  # noqa: F401
from app.modules.admin.models import Role, Staff  # noqa: F401
from app.modules.users.models import Customer  # noqa: F401
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.legal.models import LegalAcceptance  # noqa: F401
from app.modules.support.models import SupportMessage, SupportTicket  # noqa: F401
