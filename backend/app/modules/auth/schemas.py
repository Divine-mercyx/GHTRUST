from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class BvnRegisterRequest(BaseModel):
    bvn: str = Field(..., min_length=11, max_length=11, description="11-digit Bank Verification Number")

    @field_validator("bvn")
    @classmethod
    def digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("BVN must contain digits only")
        return v


class PhoneLoginRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15, description="Phone number linked to BVN account")


class DeviceInfo(BaseModel):
    """Optional client/device metadata. Send it from the mobile app on every OTP verify."""

    device_id: str | None = Field(
        default=None,
        max_length=128,
        description="Stable per-install ID. Re-login from the same device replaces its old session.",
    )
    device_name: str | None = Field(default=None, max_length=128, examples=["Ada's iPhone"])
    platform: Literal["ios", "android", "web"] | None = None
    app_version: str | None = Field(default=None, max_length=32, examples=["1.0.0"])
    device_token: str | None = Field(
        default=None,
        max_length=128,
        description="The `device_token` this phone was given at its last sign-in, if any. "
        "Proves it is a phone the customer already trusts, so no approval is needed.",
    )


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    refresh_token: str = Field(description="Opaque; rotates on every refresh. Store securely.")
    refresh_expires_in: int = Field(description="Refresh token lifetime in seconds")
    session_id: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20, max_length=256)


class SessionResponse(BaseModel):
    id: str
    device_id: str | None = None
    device_name: str | None = None
    platform: str | None = None
    app_version: str | None = None
    ip_address: str | None = None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool = False


class VerifyOtpRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=8)
    device: DeviceInfo | None = None

    @field_validator("otp")
    @classmethod
    def digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("OTP must contain digits only")
        return v


class VerifyRegistrationOtpRequest(VerifyOtpRequest):
    bvn: str = Field(..., min_length=11, max_length=11)


class VerifyLoginOtpRequest(VerifyOtpRequest):
    phone: str = Field(..., min_length=10, max_length=15)


class SelfieRequiredResponse(BaseModel):
    """SMS code accepted; the account opens once a selfie matches the BVN photo."""

    status: Literal["selfie_required"] = "selfie_required"
    registration_token: str = Field(description="Send with the selfie. Single use; keep in memory only.")
    expires_in: int
    attempts_left: int
    first_name: str


class RegistrationSelfieRequest(BaseModel):
    registration_token: str = Field(..., min_length=20, max_length=128)
    selfie_image: str = Field(
        ...,
        min_length=1000,
        max_length=4_000_000,
        description=(
            "JPEG/PNG, base64 (a data: URL prefix is accepted and removed): the frame taken "
            "while the customer looks straight at the live camera, in good light."
        ),
    )
    liveness_frames: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Other frames from the same live capture (e.g. after a blink or a slight turn). "
            "They must differ from each other and from `selfie_image`, which a replayed "
            "still photo can't do."
        ),
    )
    device: DeviceInfo | None = None


class ResendRegistrationOtpRequest(BaseModel):
    bvn: str = Field(..., min_length=11, max_length=11)


class OtpSentResponse(BaseModel):
    message: str
    phone_masked: str
    expires_in: int
    purpose: str  # registration | login
    dev_code: str | None = Field(
        None,
        description="Local development with mocked SMS only: the code, so a dev build can fill it in. "
        "Never present when SMS is real or outside APP_ENV=development.",
    )


class UpdateContactRequest(BaseModel):
    """
    Contact details a customer may change in the app. Name, BVN, date of birth and
    phone come from the BVN record (phone changes go through new-phone approval),
    so they are not editable here.
    """

    email: EmailStr | None = None
    residential_address: str | None = Field(None, min_length=5, max_length=300)

    @field_validator("residential_address")
    @classmethod
    def tidy_address(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v is not None else None

    @model_validator(mode="after")
    def something_to_change(self) -> "UpdateContactRequest":
        if not self.model_fields_set:
            raise ValueError("Provide an email or a home address to update.")
        return self


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_number: str
    bvn_masked: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    full_name: str
    gender: str | None = None
    date_of_birth: str | None = None
    phone: str
    email: str | None = None
    residential_address: str | None = None
    state_of_residence: str | None = None
    state_of_origin: str | None = None
    nationality: str | None = None
    enrollment_bank: str | None = None
    level_of_account: str | None = None
    branch: str
    status: str
    login_pin_set: bool = False
    transaction_pin_set: bool = False
    transfers_blocked_until: datetime | None = Field(
        None, description="Money can't leave the account before this time (set after a lost-phone sign-in)."
    )
    has_custom_photo: bool = Field(
        False, description="The customer chose a profile photo (else /auth/me/photo serves the BVN photo)."
    )
    photo_version: str | None = Field(None, description="Changes whenever the profile photo changes; use it to refresh.")
    legal_pending: list[str] = Field(
        default_factory=list,
        description="Legal documents (e.g. 'terms', 'privacy') to accept at their current version before continuing.",
    )

    @classmethod
    def from_customer(cls, customer) -> "CustomerProfileResponse":
        from app.modules.users.models import Customer

        return cls(
            id=customer.id,
            account_number=customer.account_number,
            bvn_masked=CustomerMask.mask_bvn(customer.bvn),
            first_name=customer.first_name,
            last_name=customer.last_name,
            middle_name=customer.middle_name,
            full_name=customer.full_name,
            gender=customer.gender,
            date_of_birth=customer.date_of_birth.isoformat() if customer.date_of_birth else None,
            phone=Customer.mask_phone(customer.phone_primary),
            email=customer.email,
            residential_address=customer.residential_address,
            state_of_residence=customer.state_of_residence,
            state_of_origin=customer.state_of_origin,
            nationality=customer.nationality,
            enrollment_bank=customer.enrollment_bank,
            level_of_account=customer.level_of_account,
            branch=customer.branch,
            status=customer.status.value if hasattr(customer.status, "value") else customer.status,
            login_pin_set=bool(customer.login_pin_hash),
            transaction_pin_set=bool(customer.transaction_pin_hash),
            transfers_blocked_until=customer.transfers_blocked_until,
            has_custom_photo=customer.profile_photo_updated_at is not None,
            photo_version=(customer.profile_photo_updated_at or customer.created_at).isoformat()
            if (customer.profile_photo_updated_at or customer.created_at)
            else None,
            legal_pending=_legal_pending(customer),
        )


class CustomerMask:
    @staticmethod
    def mask_bvn(bvn: str) -> str:
        if len(bvn) >= 6:
            return f"{bvn[:3]}****{bvn[-3:]}"
        return "****"


class AuthTokenResponse(TokenPair):
    status: Literal["signed_in"] = "signed_in"
    customer: CustomerProfileResponse
    device_token: str | None = Field(
        None,
        description="Store securely on this phone and send it in `device` next time: it lets the "
        "customer sign back in here with their PIN, and skips new-device approval.",
    )


# ── PINs ─────────────────────────────────────────────────────────────────────


def _pin_field(length: int, what: str):
    return Field(..., min_length=length, max_length=length, pattern=r"^\d+$", description=what)


class SetLoginPinRequest(BaseModel):
    pin: str = _pin_field(6, "New 6-digit sign-in PIN")


class ChangeLoginPinRequest(BaseModel):
    current_pin: str = _pin_field(6, "Current sign-in PIN")
    new_pin: str = _pin_field(6, "New sign-in PIN")


class VerifyLoginPinRequest(BaseModel):
    pin: str = _pin_field(6, "Sign-in PIN")


class ResetLoginPinRequest(BaseModel):
    bvn: str = Field(..., min_length=11, max_length=11, pattern=r"^\d+$")
    new_pin: str = _pin_field(6, "New sign-in PIN")


class SetTransactionPinRequest(BaseModel):
    pin: str = _pin_field(4, "New 4-digit transaction PIN")


class ChangeTransactionPinRequest(BaseModel):
    current_pin: str = _pin_field(4, "Current transaction PIN")
    new_pin: str = _pin_field(4, "New transaction PIN")


class ResetTransactionPinRequest(BaseModel):
    login_pin: str = _pin_field(6, "Sign-in PIN, to prove it's you")
    new_pin: str = _pin_field(4, "New transaction PIN")


class BiometricRequest(BaseModel):
    enabled: bool
    pin: str | None = Field(
        None, min_length=6, max_length=6, pattern=r"^\d+$", description="Sign-in PIN; required to turn it on"
    )


class PinSignInRequest(BaseModel):
    device_id: str = Field(..., max_length=128)
    device_token: str = Field(..., min_length=20, max_length=128)
    pin: str = _pin_field(6, "Sign-in PIN")
    device: DeviceInfo | None = None


# ── New-device approval ──────────────────────────────────────────────────────


class DeviceApprovalRequiredResponse(BaseModel):
    """Login OTP was right, but this is a new phone: confirm it on a signed-in one first."""

    status: Literal["approval_required"] = "approval_required"
    approval_id: str
    approval_secret: str = Field(description="Keep in memory; proves this phone started the sign-in.")
    expires_in: int
    approver_devices: list[str] = Field(description="Names of the signed-in phones that can approve")
    fallback_needs_pin: bool = Field(
        description="The lost-phone route asks for the sign-in PIN as well as the BVN."
    )


class ApprovalSecretRequest(BaseModel):
    approval_secret: str = Field(..., min_length=20, max_length=128)


class ApprovalStatusResponse(BaseModel):
    status: Literal["pending", "approved", "denied", "completed", "expired", "failed"]
    expires_in: int


class CompleteApprovalRequest(ApprovalSecretRequest):
    code: str = _pin_field(6, "Code shown on the approving phone")
    device: DeviceInfo | None = None


class ApprovalFallbackRequest(ApprovalSecretRequest):
    bvn: str = Field(..., min_length=11, max_length=11, pattern=r"^\d+$")
    pin: str | None = Field(None, min_length=6, max_length=6, pattern=r"^\d+$")
    device: DeviceInfo | None = None


class PendingApprovalResponse(BaseModel):
    id: str
    device_name: str | None = None
    platform: str | None = None
    ip_address: str | None = None
    requested_at: datetime
    expires_in: int


class ApproveDeviceRequest(BaseModel):
    pin: str | None = Field(
        None, min_length=6, max_length=6, pattern=r"^\d+$", description="Sign-in PIN"
    )
    biometric: bool = Field(
        False,
        description="The customer passed Face ID / fingerprint on this phone instead. Only accepted "
        "where they turned biometrics on.",
    )


class ApproveDeviceResponse(BaseModel):
    code: str = Field(description="Show on this phone; the customer types it on the new one.")
    expires_in: int


def _legal_pending(customer) -> list[str]:
    from app.modules.legal.service import legal_pending

    return legal_pending(customer)
