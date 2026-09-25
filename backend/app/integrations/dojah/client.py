import structlog
import httpx
from app.integrations.retry import transient_retry

from app.core.config import settings
from app.integrations.dojah.schemas import (
    DojahBvnEntity,
    DojahBvnResponse,
    DojahError,
    TransientDojahError,
)

logger = structlog.get_logger()

SANDBOX_BVN = "22222222222"

MOCK_ENTITY = DojahBvnEntity(
    bvn=SANDBOX_BVN,
    first_name="ADAEZE",
    last_name="OKAFOR",
    middle_name="CHINWE",
    gender="Female",
    date_of_birth="1995-03-15",
    phone_number1="08035794364",
    phone_number2="08134709697",
    email="adaeze.okafor@email.com",
    enrollment_bank="GTB",
    enrollment_branch="OGBA",
    level_of_account="LEVEL 2",
    lga_of_origin="ONITSHA NORTH",
    lga_of_residence="IKEJA",
    marital_status="SINGLE",
    name_on_card="ADAEZE C OKAFOR",
    nationality="NIGERIAN",
    registration_date="15-MAR-2018",
    residential_address="52 Ijaye Road, Ogba, Lagos",
    state_of_origin="ANAMBRA",
    state_of_residence="LAGOS",
    title="MISS",
    watch_listed="NO",
    image=None,
)


class DojahClient:
    """
    Dojah BVN Advanced lookup.
    Docs: https://docs.dojah.io/docs/nigeria/lookup-bvn#bvn-advanced
    """

    def __init__(self):
        self.base_url = settings.dojah_base_url.rstrip("/")
        self.app_id = settings.dojah_app_id
        self.secret_key = settings.dojah_secret_key

    @transient_retry()
    async def lookup_bvn_advanced(self, bvn: str) -> DojahBvnEntity:
        if settings.dojah_mock or not settings.dojah_enabled:
            logger.info("dojah_mock_lookup", bvn=bvn[:3] + "****")
            update = {"bvn": bvn}
            if settings.dojah_mock_phone:
                update["phone_number1"] = settings.dojah_mock_phone
            entity = MOCK_ENTITY.model_copy(update=update)
            return entity

        url = f"{self.base_url}/api/v1/kyc/bvn/advance"
        headers = {
            "AppId": self.app_id,
            "Authorization": self.secret_key,
        }
        params = {"bvn": bvn}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("dojah_transport_error", error=str(exc))
            raise TransientDojahError(
                "BVN verification is temporarily unavailable. Please try again.", status_code=502
            ) from exc

        if response.status_code == 404:
            raise DojahError("BVN not found or invalid", status_code=404)
        if response.status_code >= 500:
            logger.error("dojah_api_unavailable", status=response.status_code)
            raise TransientDojahError(
                "BVN verification is temporarily unavailable. Please try again.", status_code=502
            )
        if response.status_code >= 400:
            logger.error("dojah_api_error", status=response.status_code, body=response.text[:200])
            raise DojahError("BVN verification failed. Please try again.", status_code=502)

        data = DojahBvnResponse.model_validate(response.json())
        return data.entity
