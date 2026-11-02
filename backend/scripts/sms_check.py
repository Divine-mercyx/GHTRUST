"""
Check that Dojah Messaging delivers to a real phone (SMS_PROVIDER=dojah). Each send costs a
little from the Dojah wallet.

    python scripts/sms_check.py --to 08031234567            # a text, then a code to type back
    python scripts/sms_check.py --to 08031234567 --no-otp   # the text only

1. Send SMS, then Message Status until it says DELIVERED (or FAILED, or 60 seconds pass).
2. Send OTP (Dojah makes the code), you type what arrived, Validate OTP says if it matches.

Uses DOJAH_APP_ID / DOJAH_SECRET_KEY / DOJAH_SENDER_ID / DOJAH_BASE_URL from backend/.env (or
the server's variables when run there). Exits non-zero if anything fails.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.integrations.sms import DojahMessaging  # noqa: E402

FINAL = {"DELIVERED", "FAILED", "REJECTED", "UNDELIVERED", "EXPIRED"}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="phone number to send to, e.g. 08031234567")
    parser.add_argument("--no-otp", action="store_true", help="skip the code test")
    args = parser.parse_args()

    s = get_settings()
    missing = [n for n, v in (("DOJAH_APP_ID", s.dojah_app_id), ("DOJAH_SECRET_KEY", s.dojah_secret_key),
                              ("DOJAH_SENDER_ID", s.dojah_sender_id)) if not v]  # fmt: skip
    if missing:
        print(f"Set {', '.join(missing)} first (backend/.env).")
        return 1
    print(f"Dojah {s.dojah_base_url}, sender ID {s.dojah_sender_id}, channel {s.dojah_sms_channel}")
    api = DojahMessaging()
    ok = True

    try:
        sent = await api.send_sms(args.to, "GH Trust: this is a test message. No action needed.")
        message_id = sent.get("message_id")
        print(f"  SMS queued: {sent.get('status')} (message_id {message_id})")
        status = "UNKNOWN"
        for _ in range(12):
            await asyncio.sleep(5)
            status = await api.message_status(message_id)
            print(f"  status: {status}")
            if status in FINAL:
                break
        ok &= status == "DELIVERED"
    except AppError:
        print("  SMS failed: see the sms_dojah_* log line above (401 keys, 402 wallet, 422 sender ID).")
        ok = False

    if not args.no_otp:
        try:
            sent = await api.send_otp(args.to)
            print(f"  Code sent: {sent.get('status')}")
            code = input("  Type the code you received: ").strip()
            valid = await api.validate_otp(sent["reference_id"], code)
            print(f"  Code {'valid' if valid else 'NOT valid'}")
            ok &= valid
        except AppError:
            print("  OTP failed: see the sms_dojah_* log line above.")
            ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
