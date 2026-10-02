"""
The customer-facing legal documents, served to the app so wording can change without an
app release.

Bumping a document's ``version`` asks every customer to accept it again the next time
they open the app (see ``pending_documents``).

DRAFT: this wording was written to cover how the product works today. It must be
reviewed and approved by GH Trust's legal/compliance team (and the entity details
filled in) before launch; ``DRAFT`` makes the app say so.
"""

from dataclasses import dataclass

DRAFT = True
COMPANY = "GH Trust"


@dataclass(frozen=True)
class Section:
    heading: str
    body: str


@dataclass(frozen=True)
class LegalDocument:
    slug: str
    title: str
    version: str
    effective_date: str
    summary: str
    sections: tuple[Section, ...]


TERMS = LegalDocument(
    slug="terms",
    title="Terms of Use",
    version="2026-10-02",
    effective_date="2026-10-02",
    summary="The rules for using the GH Trust app: your account, your PINs, loans, the wallet, and what happens if something goes wrong.",
    sections=(
        Section(
            "About these terms",
            f"These terms are an agreement between you and {COMPANY} about your use of the GH Trust app and "
            "the services in it. By creating an account or using the app you agree to them. Please read them "
            "with our Privacy Policy, which explains how we use your information.",
        ),
        Section(
            "Your account",
            "You must be 18 or older, have a valid Bank Verification Number (BVN), and give us true and "
            "complete information. Your account is personal: you may not open it for someone else or let "
            "anyone else use it. We verify your identity with your BVN, a one-time code sent to the phone "
            "number on your BVN, and a live face check.",
        ),
        Section(
            "Keeping your account safe",
            "Keep your sign-in PIN and transaction PIN secret, and never share one-time codes. We will never "
            "ask for your PINs or codes by phone, SMS, email or social media. Signing in on a new phone needs "
            "approval from a phone that is already signed in. If you think someone else has access to your "
            "account, contact us immediately and use 'Sign out of all devices' in the app. You are "
            "responsible for transactions approved with your PIN or biometrics until you tell us your account "
            "may be compromised.",
        ),
        Section(
            "Loans",
            "Applying does not guarantee a loan. We assess every application, may check credit bureaus and "
            "the information you provide, and may approve a different amount or duration, or decline. Before "
            "any loan is paid out we show you a loan offer with the amount, interest, fees, total to repay "
            "and repayment dates. The loan only goes ahead if you accept that offer in the app with your "
            "transaction PIN. The accepted offer and its loan agreement form part of these terms.",
        ),
        Section(
            "Repayments",
            "Repay on or before each due date shown in the app. You can repay early at any time. Payments go "
            "to your oldest unpaid instalment first, interest before principal. If you pay late, the charges "
            "set out in your loan offer apply, and we may report the loan to licensed credit bureaus, which "
            "can affect your ability to borrow elsewhere. We will contact you about missed payments "
            "respectfully and only through you and the contacts you have given us permission to use.",
        ),
        Section(
            "Wallet",
            "Where available, your wallet lets you add money by bank transfer, repay loans and withdraw to a "
            "bank account in your own name. Withdrawals and changes to your payout account need your "
            "transaction PIN. Transfers are usually instant but depend on the banks involved. If a transfer "
            "fails, the money is returned to your wallet. For your security, withdrawals may be paused for 24 "
            "hours after you sign in on a new phone without your old one.",
        ),
        Section(
            "Things you must not do",
            "Do not give false information, use the app for anything illegal including fraud or money "
            "laundering, try to access another person's account, or interfere with the app or our systems. "
            "We may suspend or close accounts involved in these activities and report them to the "
            "authorities.",
        ),
        Section(
            "Fees",
            "Opening an account and using the app are free. Loan interest and fees are shown in each loan "
            "offer before you accept it. We will tell you before introducing any new fee.",
        ),
        Section(
            "When things go wrong",
            "We work hard to keep the app available and accurate, but it may sometimes be unavailable, for "
            "example during maintenance. If we make a mistake with your money we will put it right. We are "
            "not responsible for losses caused by events outside our reasonable control, or by you sharing "
            "your PINs, codes or phone.",
        ),
        Section(
            "Complaints",
            "If you are unhappy with anything, use Help & support in the app, or call or email us. We will "
            "acknowledge your complaint promptly and aim to resolve it within the timelines set by our "
            "regulators. If you are not satisfied with our response, you may escalate it to the relevant "
            "regulator.",
        ),
        Section(
            "Changes and deleting your account",
            "We may update these terms. If the change is significant we will ask you to accept the new "
            "version in the app before you continue. You can delete your account yourself at any time in the "
            "app (Profile, then Delete account) or on our website, once you have no loan or repayment "
            "outstanding, no application being processed, no money in your wallet and no withdrawal on its "
            "way. Our Privacy Policy explains what is deleted and what we must keep. We may close or restrict "
            "an account if required by law or if these terms are broken.",
        ),
        Section(
            "Law",
            "These terms are governed by the laws of the Federal Republic of Nigeria.",
        ),
    ),
)

PRIVACY = LegalDocument(
    slug="privacy",
    title="Privacy Policy",
    version="2026-10-02",
    effective_date="2026-10-02",
    summary="What personal data we collect, why, who we share it with, how long we keep it, and your rights under the Nigeria Data Protection Act 2023.",
    sections=(
        Section(
            "Who we are",
            f"{COMPANY} is the data controller for the personal data you give us through the GH Trust app. We "
            "process it in line with the Nigeria Data Protection Act 2023 and guidance from the Nigeria Data "
            "Protection Commission (NDPC). You can contact our Data Protection Officer through Help & support "
            "in the app.",
        ),
        Section(
            "What we collect",
            "Identity: your BVN and the details linked to it (name, date of birth, phone number, photo). "
            "Verification: the selfie and short live video frames from your face check. Contact: phone, email "
            "and address. Loan applications: employment, income, business, next of kin, guarantors, "
            "collateral and the documents you upload. Financial: your wallet, transactions, loans, repayments "
            "and payout bank account. Device and security: device name, app version, IP address, sign-in "
            "history and push notification tokens.",
        ),
        Section(
            "What we don't collect",
            "We do not read your contacts, call logs, SMS messages, photos or other files on your phone, and we "
            "never contact people in your phone book. We only use the camera when you choose to take a photo "
            "or do the face check.",
        ),
        Section(
            "Why we use it",
            "To open and secure your account and prevent fraud (our legal obligations and legitimate "
            "interests); to assess, provide and manage your loans and wallet (to perform our contract with "
            "you); to meet anti-money-laundering, 'know your customer' and reporting duties (legal "
            "obligation); and to send you service messages such as repayment reminders. We only send "
            "marketing if you agree, and you can say no at any time.",
        ),
        Section(
            "Automated decisions",
            "We use automated checks to help verify your identity (matching your selfie to your BVN photo) "
            "and to support credit decisions. A member of our team reviews loan decisions, and you can ask "
            "for a decision to be reviewed by a person.",
        ),
        Section(
            "Who we share it with",
            "Only with those who need it to provide the service or where the law requires: identity "
            "verification providers (to check your BVN and face), licensed credit bureaus, our banking and "
            "payment partners (to move money), SMS and push notification providers, cloud hosting providers, "
            "our professional advisers, and regulators, courts or law enforcement when legally required. We "
            "never sell your personal data.",
        ),
        Section(
            "Transfers outside Nigeria",
            "Some of our service providers may store or process data outside Nigeria. When that happens we "
            "make sure the transfer is allowed under the Nigeria Data Protection Act and that your data is "
            "protected to the same standard.",
        ),
        Section(
            "How long we keep it",
            "We keep your data while you are a customer and for as long afterwards as the law requires "
            "(financial records are generally kept for at least 5 years after the relationship ends). Face "
            "check images are kept only as long as needed to prove your identity was verified. We then delete "
            "or anonymise it.",
        ),
        Section(
            "Deleting your account",
            "You can delete your account yourself in the app (Profile, then Delete account) or on our "
            "website, after confirming it's you with your sign-in PIN (and, on the website, a code sent to "
            "your phone). You can't delete it while you have a loan or repayment outstanding, an application "
            "being processed, money in your wallet or a withdrawal on its way, because we still owe each "
            "other money. When you delete your account we sign you out on every phone and delete your PINs, "
            "profile and BVN photos, contact details, address, payout bank account, saved phones, "
            "notifications, unfinished applications and the text of your support messages. We keep records "
            "of loans, repayments, payments, your wallet, signed agreements and applications you submitted "
            "for the period the law requires, together with only the details that link them to you (BVN, "
            "name, date of birth and account number). If you never had a loan or payment with us, those "
            "details are deleted too. Information already shared with identity, credit bureau, payment or "
            "SMS providers is kept by them under their own legal duties. Deleting an account can't be "
            "undone; to bank with us again, contact us.",
        ),
        Section(
            "How we protect it",
            "Data is encrypted in transit and access is limited to staff who need it. Your PINs are stored "
            "only as secure hashes, and sensitive app data is kept in your phone's secure storage. If a breach "
            "is likely to put you at risk, we will tell you and the NDPC as the law requires.",
        ),
        Section(
            "Your rights",
            "You can ask to see the data we hold about you, correct it, have it deleted (unless we must keep "
            "it by law or for an outstanding loan), restrict or object to how we use it, get a copy in a "
            "portable format, and withdraw any consent you have given. Ask through Help & support and we will "
            "respond within the time the law allows. If you are not satisfied, you can complain to the "
            "Nigeria Data Protection Commission.",
        ),
        Section(
            "Changes",
            "We will tell you in the app about significant changes to this policy and ask you to accept them "
            "before you continue.",
        ),
    ),
)

DOCUMENTS: dict[str, LegalDocument] = {d.slug: d for d in (TERMS, PRIVACY)}

# Documents every customer must have accepted (at their current version) to use the app.
REQUIRED = ("terms", "privacy")

# Loan agreement: general conditions shown with every loan offer. Offer-specific figures
# (amount, interest, fees, dates) are added per offer.
LOAN_AGREEMENT_VERSION = "2026-10-02"
LOAN_AGREEMENT_SECTIONS: tuple[Section, ...] = (
    Section(
        "The loan",
        "We agree to lend you the amount in this offer and pay it into your GH Trust wallet or the bank account "
        "shown, and you agree "
        "to repay it with interest in the instalments and on the dates shown. The schedule in the app is "
        "part of this agreement.",
    ),
    Section(
        "Paying early",
        "You can repay part or all of the loan early at any time from the app. Paying early reduces what you "
        "owe; interest already charged for past periods is not refunded.",
    ),
    Section(
        "Late payment",
        "If an instalment is not paid by its due date it becomes overdue. Any late-payment charge shown in "
        "this offer applies only to the overdue amount. We will remind you before and after due dates.",
    ),
    Section(
        "If the loan is not repaid",
        "If payments remain overdue we will contact you to agree a way forward. We may report the loan to "
        "licensed credit bureaus and, as a last resort, recover the debt through lawful means, including "
        "from guarantors or collateral you provided. We will never publish your information or contact "
        "people who are not your listed contacts or guarantors.",
    ),
    Section(
        "Your information",
        "You confirm the information in your application is true. Giving false information may end this "
        "agreement and make the full balance payable. Our Privacy Policy explains how we use your data.",
    ),
    Section(
        "Accepting",
        "Accepting this offer in the app with your transaction PIN is your electronic signature. We record "
        "the time you accepted and the exact terms shown to you. You can see this agreement in the app at "
        "any time while the loan is open.",
    ),
)


def pending_documents(accepted: dict[str, str | None]) -> list[str]:
    """Required documents the customer hasn't accepted at their current version."""
    return [slug for slug in REQUIRED if accepted.get(slug) != DOCUMENTS[slug].version]
