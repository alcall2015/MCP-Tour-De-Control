import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import SmsReply


async def test_one_reply_per_trigger_is_enforced_by_the_database(session):
    for _ in range(2):
        session.add(SmsReply(trigger_kind="sms", trigger_ref="sms:42", sim_id=872,
                             to_number="0700003331", whatsapp_number="33600000000",
                             content="x", status="sent"))
    with pytest.raises(IntegrityError):
        await session.commit()
