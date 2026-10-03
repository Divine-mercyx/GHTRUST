/** Aliases over the generated OpenAPI types (`npm run gen:api` regenerates schema.d.ts). */
import type { components } from './schema';

type S = components['schemas'];

export type AppConfig = S['AppConfigResponse'];
export type OtpSent = S['app__modules__auth__schemas__OtpSentResponse'];
export type AuthTokens = S['AuthTokenResponse'];
export type TokenPair = S['TokenPair'];
export type DeviceInfo = S['DeviceInfo'];
export type Profile = S['CustomerProfileResponse'];
export type UpdateContact = S['UpdateContactRequest'];
export type Session = S['SessionResponse'];
export type ApprovalRequired = S['DeviceApprovalRequiredResponse'];
export type SelfieRequired = S['SelfieRequiredResponse'];
export type ApprovalStatus = S['ApprovalStatusResponse'];
export type PendingApproval = S['PendingApprovalResponse'];
export type ApproveResult = S['ApproveDeviceResponse'];

export type LoanProduct = S['LoanProductResponse'];
export type ApplicationSummary = S['LoanApplicationSummaryResponse'];
export type Application = S['LoanApplicationDetailResponse'];
export type ApplicationStatus = S['ApplicationStatus'];
export type UniversalForm = S['UniversalFormData'];
export type StepUpdate = S['UpdateApplicationStepRequest'];
export type GuarantorInput = S['GuarantorInput'];
export type CollateralInput = S['CollateralInput'];
export type ChecklistItem = S['DocumentChecklistItem'];

export type Loan = S['LoanResponse'];
export type LoanDetail = S['LoanDetailResponse'];
export type ScheduleItem = S['RepaymentScheduleItem'];
export type Repayment = S['LoanRepaymentResponse'];

export type Bank = S['BankResponse'];
export type ResolvedAccount = S['ResolveAccountResponse'];

export type Wallet = S['WalletSummaryResponse'];
export type WalletFundSession = S['WalletFundSessionResponse'];
export type PayoutAccount = S['PayoutAccountSummary'];
export type PayoutAccountSaved = S['PayoutAccountSavedResponse'];
export type Withdrawal = S['WithdrawalResponse'];
export type WalletTransaction = S['WalletTransactionResponse'];
export type WalletTransactionPage = S['WalletTransactionPage'];
export type TransactionDirection = 'in' | 'out';

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type AppNotification = S['NotificationResponse'];
export type NotificationPage = S['NotificationPage'];
export type LegalDocumentSummary = S['DocumentSummary'];
export type LegalDocument = S['DocumentResponse'];
export type LoanOffer = S['LoanOfferResponse'];
export type Faqs = S['FaqsResponse'];
export type SupportTicket = S['TicketResponse'];
export type TicketCategory = S['CreateTicketRequest']['category'];
export type TicketRelated = NonNullable<S['CreateTicketRequest']['related_type']>;
export type SupportMessage = S['MessageResponse'];
export type ProfilePhoto = S['ProfilePhotoResponse'];
export type DeletionCheck = S['DeletionCheckResponse'];
export type AccountDeleted = S['AccountDeletedResponse'];
