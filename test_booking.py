from datetime import date, datetime, timedelta

import pytest
from booking import Booking

DAY = date(2030, 1, 14)
NOW = datetime(2030, 1, 1, 9, 0)


@pytest.fixture
def b():
    x = Booking()
    x.hair = x.add_service("Стрижка", 60, 500)
    x.color = x.add_service("Окрашивание", 120, 1500)
    return x


def test_slots_fit_in_working_day(b):
    slots = b.free_slots(b.color, DAY, NOW)
    assert slots[0] == datetime(2030, 1, 14, 10, 0)
    assert slots[-1] == datetime(2030, 1, 14, 17, 0)  # 17:00 + 2 часа = 19:00, позже нельзя


def test_booking_blocks_overlapping_slots(b):
    b.book(1, "Анна", "+380", b.hair, datetime(2030, 1, 14, 12, 0), NOW)
    times = [s.strftime("%H:%M") for s in b.free_slots(b.hair, DAY, NOW)]
    assert "11:30" not in times and "12:00" not in times and "12:30" not in times
    assert "11:00" in times and "13:00" in times  # ровно встык — можно


def test_double_booking_rejected(b):
    b.book(1, "Анна", "+380", b.hair, datetime(2030, 1, 14, 12, 0), NOW)
    with pytest.raises(ValueError):
        b.book(2, "Борис", "+381", b.hair, datetime(2030, 1, 14, 12, 30), NOW)


def test_past_time_rejected(b):
    with pytest.raises(ValueError):
        b.book(1, "A", "1", b.hair, datetime(2030, 1, 14, 10, 0), now=datetime(2030, 1, 14, 11, 0))


def test_cancel_frees_slot_and_only_owner_cancels(b):
    t = datetime(2030, 1, 14, 12, 0)
    aid = b.book(1, "Анна", "+380", b.hair, t, NOW)
    assert b.cancel(aid, user_id=2) is False  # чужую отменить нельзя
    assert b.cancel(aid, user_id=1) is True
    assert t in b.free_slots(b.hair, DAY, NOW)


def test_reminder_sent_once(b):
    b.book(1, "Анна", "+380", b.hair, datetime(2030, 1, 14, 12, 0), NOW)
    now = datetime(2030, 1, 13, 15, 0)
    assert len(b.due_reminders(now)) == 1
    assert b.due_reminders(now) == []
