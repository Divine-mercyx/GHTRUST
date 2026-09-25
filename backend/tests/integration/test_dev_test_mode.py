"""Development test mode: sign up / sign in from a real phone before SMS and BVN keys exist."""

from tests.conftest import TEST_BVN, TEST_OTP, refresh_settings

DEV_PHONE = "08027218077"


async def test_dev_mode_registers_your_number_and_echoes_the_code(
    api_client, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DOJAH_MOCK_PHONE", DEV_PHONE)
    refresh_settings()

    sent = (
        await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
    ).json()
    assert sent["phone_masked"].endswith("8077")  # the mock identity uses your number
    assert sent["dev_code"] == TEST_OTP

    verified = await api_client.post(
        "/api/v1/auth/register/verify-otp",
        json={"bvn": TEST_BVN, "otp": sent["dev_code"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["customer"]["phone"].endswith(
        "8077"
    )  # masked in the profile

    login = (
        await api_client.post(
            "/api/v1/auth/login/request-otp", json={"phone": DEV_PHONE}
        )
    ).json()
    assert login["dev_code"] == TEST_OTP


async def test_unknown_numbers_get_no_code_even_in_dev_mode(api_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    refresh_settings()
    res = (
        await api_client.post(
            "/api/v1/auth/login/request-otp", json={"phone": "08099999999"}
        )
    ).json()
    assert res["dev_code"] is None


async def test_codes_are_never_echoed_outside_development(api_client):
    # conftest runs as APP_ENV=test with SMS mocked
    res = (
        await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
    ).json()
    assert res["dev_code"] is None
