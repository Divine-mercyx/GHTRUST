"""Loan product codes, document types, and seed definitions.

Product wording and terms follow GH Trust's website (ghtrustintlltd.com/loans, Oct 2026).
Changing a seeded product here only reaches new databases; existing ones need a migration
(see 029_loan_catalogue_website) or an edit in the admin portal.
"""

from decimal import Decimal

from app.modules.loans.schemas import InterestMethod

BUSINESS_LOAN = "business_loan"
PAYDAY_LOAN = "payday_loan"
STUDY_LOAN = "study_loan"
ASSET_LOAN = "asset_loan"
LPO_LOAN = "lpo_invoice_financing"
CLUSTER_LOAN = "cluster_group_loan"

# Universal + product-specific document type codes
DOC_VALID_ID = "valid_id"
DOC_BVN = "bvn"
DOC_PASSPORT_PHOTO = "passport_photo"
DOC_PASSPORT_PHOTO_2 = "passport_photo_2"
DOC_SHOP_RENT_RECEIPT = "shop_rent_receipt"
DOC_CASH_FLOW_PROOF = "cash_flow_proof"
DOC_SALARY_STATEMENT_6M = "salary_statement_6m"
DOC_STAFF_ID = "staff_id"
DOC_UTILITY_BILL = "utility_bill"
DOC_PRESIGNED_CHEQUE = "presigned_cheque"
DOC_COLLATERAL_AFFIDAVIT = "collateral_affidavit"
DOC_COLLATERAL_ORIGINAL = "collateral_original"
DOC_GUARANTOR_ID = "guarantor_id"
DOC_GUARANTOR_PHOTO = "guarantor_photo"
DOC_GUARANTOR_PHOTO_2 = "guarantor_photo_2"
DOC_ADMISSION_LETTER = "admission_letter"
DOC_RELATIONSHIP_PROOF = "relationship_proof"
DOC_COLLATERAL_C_OF_O = "collateral_c_of_o"
DOC_OFFER_LETTER_SIGNED = "offer_letter_signed"
DOC_COURT_AFFIDAVIT = "court_affidavit"
DOC_INCOME_PROOF = "income_proof"
DOC_BUSINESS_REGISTRATION = "business_registration"
DOC_LPO_INVOICE = "lpo_invoice"
DOC_GROUP_MEMBER_LIST = "group_member_list"
DOC_GROUP_LEADER_ID = "group_leader_id"

# Business loans: a guarantor OR collateral, only from this amount (naira) up.
BUSINESS_SECURITY_FROM = 100_000
# Documents that are that "guarantor or collateral" security (optional below the amount).
SECURITY_DOCUMENT_TYPES = (DOC_GUARANTOR_ID, DOC_GUARANTOR_PHOTO, DOC_COLLATERAL_ORIGINAL)
MAX_GROUP_MEMBERS = 15

UNIVERSAL_DOCUMENT_TYPES = (
    DOC_VALID_ID,
    DOC_BVN,
)

PRODUCT_DOCUMENTS: dict[str, tuple[str, ...]] = {
    BUSINESS_LOAN: (
        DOC_VALID_ID,
        DOC_BVN,
        DOC_PASSPORT_PHOTO,
        DOC_PASSPORT_PHOTO_2,
        DOC_SHOP_RENT_RECEIPT,
        DOC_CASH_FLOW_PROOF,
        DOC_GUARANTOR_ID,
        DOC_GUARANTOR_PHOTO,
        DOC_COLLATERAL_ORIGINAL,
    ),
    PAYDAY_LOAN: (
        DOC_VALID_ID,
        DOC_BVN,
        DOC_PASSPORT_PHOTO,
        DOC_SALARY_STATEMENT_6M,
        DOC_STAFF_ID,
        DOC_UTILITY_BILL,
        DOC_PRESIGNED_CHEQUE,
        DOC_COLLATERAL_AFFIDAVIT,
        DOC_COLLATERAL_ORIGINAL,
        DOC_GUARANTOR_ID,
        DOC_GUARANTOR_PHOTO,
    ),
    STUDY_LOAN: (
        DOC_VALID_ID,
        DOC_ADMISSION_LETTER,
        DOC_RELATIONSHIP_PROOF,
        DOC_STAFF_ID,
        DOC_UTILITY_BILL,
        DOC_SALARY_STATEMENT_6M,
        DOC_PRESIGNED_CHEQUE,
        DOC_COLLATERAL_C_OF_O,
        DOC_GUARANTOR_ID,
        DOC_GUARANTOR_PHOTO,
    ),
    ASSET_LOAN: (
        DOC_VALID_ID,
        DOC_PASSPORT_PHOTO,
        DOC_PASSPORT_PHOTO_2,
        DOC_INCOME_PROOF,
        DOC_GUARANTOR_ID,
        DOC_GUARANTOR_PHOTO,
        DOC_GUARANTOR_PHOTO_2,
        DOC_COURT_AFFIDAVIT,
    ),
    LPO_LOAN: (
        DOC_VALID_ID,
        DOC_BVN,
        DOC_BUSINESS_REGISTRATION,
        DOC_LPO_INVOICE,
        DOC_GUARANTOR_ID,
    ),
    CLUSTER_LOAN: (
        DOC_VALID_ID,
        DOC_BVN,
        DOC_PASSPORT_PHOTO,
        DOC_CASH_FLOW_PROOF,
        DOC_GROUP_MEMBER_LIST,
        DOC_GROUP_LEADER_ID,
        DOC_SHOP_RENT_RECEIPT,
        DOC_GUARANTOR_ID,
    ),
}

PRODUCT_WIZARD_STEPS: dict[str, list[str]] = {
    BUSINESS_LOAN: [
        "product_selection",
        "universal_form",
        "business_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
    PAYDAY_LOAN: [
        "product_selection",
        "universal_form",
        "employment_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
    STUDY_LOAN: [
        "product_selection",
        "universal_form",
        "student_school_details",
        "guardian_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
    ASSET_LOAN: [
        "product_selection",
        "universal_form",
        "asset_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
    LPO_LOAN: [
        "product_selection",
        "universal_form",
        "lpo_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
    CLUSTER_LOAN: [
        "product_selection",
        "universal_form",
        "group_details",
        "guarantor_collateral",
        "documents",
        "review_submit",
    ],
}

# Every application step the customer apps have screens for, in their usual order.
WIZARD_STEPS: tuple[str, ...] = (
    "product_selection",
    "universal_form",
    "business_details",
    "employment_details",
    "student_school_details",
    "guardian_details",
    "asset_details",
    "lpo_details",
    "group_details",
    "guarantor_collateral",
    "documents",
    "review_submit",
)

BUSINESS_DESCRIPTION = (
    "Working capital for traders who buy and sell goods: restock, pay suppliers and meet demand. "
    "For businesses trading for 3 years or more. Repay daily, weekly or monthly to match your cash flow. "
    "From ₦100,000, add a guarantor or acceptable collateral."
)
PAYDAY_DESCRIPTION = (
    "Quick support for salary earners before payday: medical bills, school fees, rent and other "
    "urgent needs. Repay over up to 120 days, in line with your salary cycle."
)
STUDY_DESCRIPTION = (
    "Study-abroad tuition financing with Famolex Integrated: up to 70% of the student's first-year "
    "tuition, decided within 7 working days. A parent or guardian applies for the student."
)
LPO_DESCRIPTION = (
    "Working capital to deliver verified LPOs, supply contracts and approved invoices from reputable "
    "organisations. 3% processing fee upfront, then a 7% charge when the job is paid."
)
CLUSTER_DESCRIPTION = (
    "Group financing for market women, small traders and cooperatives. Up to 15 members who know and "
    "trust one another share responsibility. Repayments start 7 days after payout."
)

LOAN_PRODUCT_SEED: list[dict] = [
    {
        "code": BUSINESS_LOAN,
        "name": "GH Trust Business Loan",
        "description": BUSINESS_DESCRIPTION,
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        "interest_rate_pct_monthly": Decimal("8.00"),
        "max_tenure_days": None,
        "default_penalty_pct_daily": None,
        "repayment_cadence_options": ["daily", "weekly", "monthly"],
        "required_document_types": list(PRODUCT_DOCUMENTS[BUSINESS_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[BUSINESS_LOAN],
        "eligibility_rules": {
            "min_years_in_business": 3,
            "business_type": "trader",
            "requires_shop_proof": True,
            "requires_cash_flow_proof": True,
            "security_from_amount": BUSINESS_SECURITY_FROM,
        },
    },
    {
        "code": PAYDAY_LOAN,
        "name": "Payday Loan",
        "description": PAYDAY_DESCRIPTION,
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        "interest_rate_pct_monthly": Decimal("8.00"),
        "max_tenure_days": 120,
        "default_penalty_pct_daily": Decimal("1.50"),
        "repayment_cadence_options": ["salary_date"],
        "required_document_types": list(PRODUCT_DOCUMENTS[PAYDAY_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[PAYDAY_LOAN],
        "eligibility_rules": {
            "borrower_type": "salary_earner",
            "min_salary_statement_months": 6,
            "requires_remita_mandate": True,
            "no_cash_repayment": True,
        },
    },
    {
        "code": STUDY_LOAN,
        "name": "GH Trust Study Loan",
        "description": STUDY_DESCRIPTION,
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        "interest_rate_pct_monthly": Decimal("8.00"),
        "max_tenure_days": 180,
        "default_penalty_pct_daily": None,
        "repayment_cadence_options": ["monthly"],
        "required_document_types": list(PRODUCT_DOCUMENTS[STUDY_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[STUDY_LOAN],
        "eligibility_rules": {
            "ghtrust_contribution_pct": 70,
            "applicant_contribution_pct": 30,
            "tuition_year": 1,
            "guardian_min_years_employed": 5,
            "guardian_max_age": 50,
            "guardian_resident_nigeria": True,
            "disburse_to": "school_account",
            "processing_days": 7,
        },
    },
    {
        "code": ASSET_LOAN,
        "name": "Asset Loan",
        "description": "Asset financing — asset purchased in GH Trust name until fully repaid.",
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        "interest_rate_pct_monthly": Decimal("8.00"),
        "max_tenure_days": None,
        "default_penalty_pct_daily": None,
        "repayment_cadence_options": ["monthly"],
        "required_document_types": list(PRODUCT_DOCUMENTS[ASSET_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[ASSET_LOAN],
        "eligibility_rules": {
            "asset_owner_until_paid": "ghtrust_international_ltd",
            "requires_court_affidavit": True,
            "requires_verifiable_income": True,
        },
    },
    {
        "code": LPO_LOAN,
        "name": "Trust LPO / Invoice / Supply Financing",
        "description": LPO_DESCRIPTION,
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        # The 7% back-end charge, once for the whole facility, repaid when the client pays.
        "interest_rate_pct_monthly": Decimal("7.00"),
        "interest_method": InterestMethod.ONE_OFF,
        "max_tenure_days": None,
        "default_penalty_pct_daily": None,
        "repayment_cadence_options": ["end_of_term"],
        "required_document_types": list(PRODUCT_DOCUMENTS[LPO_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[LPO_LOAN],
        "eligibility_rules": {
            "requires_verified_lpo": True,
            "collateral_if_no_domiciliation": True,
        },
    },
    {
        "code": CLUSTER_LOAN,
        "name": "GHT Cluster / Group Loan",
        "description": CLUSTER_DESCRIPTION,
        "is_active": True,
        "processing_fee_pct": Decimal("3.00"),
        "interest_rate_pct_monthly": Decimal("8.00"),
        "max_tenure_days": None,
        "default_penalty_pct_daily": None,
        # Weekly: the first repayment falls 7 days after payout, as the website states.
        "repayment_cadence_options": ["weekly"],
        "required_document_types": list(PRODUCT_DOCUMENTS[CLUSTER_LOAN]),
        "workflow_steps": PRODUCT_WIZARD_STEPS[CLUSTER_LOAN],
        "eligibility_rules": {
            "borrower_type": "market_trader",
            "max_group_members": MAX_GROUP_MEMBERS,
            "group_guarantee": True,
            "repayment_starts_after_days": 7,
            "no_cash_repayment": True,
        },
    },
]

DOCUMENT_LABELS: dict[str, str] = {
    DOC_VALID_ID: "Valid means of identification",
    DOC_BVN: "BVN verification",
    DOC_PASSPORT_PHOTO: "Recent passport photograph",
    DOC_PASSPORT_PHOTO_2: "Second passport photograph",
    DOC_SHOP_RENT_RECEIPT: "Shop rent receipt / proof of ownership",
    DOC_CASH_FLOW_PROOF: "Verifiable cash flow / proof of trading",
    DOC_SALARY_STATEMENT_6M: "6 months salary account statement",
    DOC_STAFF_ID: "Staff ID card",
    DOC_UTILITY_BILL: "Utility bill (not older than 3 months)",
    DOC_PRESIGNED_CHEQUE: "Pre-signed cheque on salary account",
    DOC_COLLATERAL_AFFIDAVIT: "Affidavit for collateral",
    DOC_COLLATERAL_ORIGINAL: "Original collateral documents",
    DOC_GUARANTOR_ID: "Guarantor valid ID",
    DOC_GUARANTOR_PHOTO: "Guarantor passport photograph",
    DOC_GUARANTOR_PHOTO_2: "Guarantor second passport photograph",
    DOC_ADMISSION_LETTER: "Student admission letter",
    DOC_RELATIONSHIP_PROOF: "Proof of relationship with student",
    DOC_COLLATERAL_C_OF_O: "Collateral C of O (Lagos property)",
    DOC_OFFER_LETTER_SIGNED: "Signed offer letter",
    DOC_COURT_AFFIDAVIT: "Court affidavit (asset as collateral)",
    DOC_INCOME_PROOF: "Proof of verifiable income",
    DOC_BUSINESS_REGISTRATION: "Business registration (CAC) documents",
    DOC_LPO_INVOICE: "Verified LPO, invoice or supply contract",
    DOC_GROUP_MEMBER_LIST: "Group membership list",
    DOC_GROUP_LEADER_ID: "Group leader's ID",
}
