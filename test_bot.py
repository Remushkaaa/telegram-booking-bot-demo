"""Сквозной тест Telegram-слоя без интернета (подмена сессии)."""
import asyncio
import os
import time
from datetime import date, datetime, timedelta

os.environ["ADMIN_IDS"] = "999"
os.environ["DB_PATH"] = ":memory:"

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage  # noqa: E402
from aiogram.types import Chat, Message  # noqa: E402

import bot as app  # noqa: E402


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=len(self.calls), date=int(time.time()),
                           chat=Chat(id=getattr(method, "chat_id", 1), type="private"), text=method.text)
        return True

    async def close(self): pass
    async def stream_content(self, *a, **k): yield b""

    def sent(self, to):
        return [m.text for m in self.calls if isinstance(m, SendMessage) and m.chat_id == to]


def msg(uid, text, n=[0]):
    n[0] += 1
    return {"update_id": n[0], "message": {"message_id": n[0], "date": int(time.time()),
            "chat": {"id": uid, "type": "private"}, "from": {"id": uid, "is_bot": False, "first_name": "T"},
            "text": text}}


def cbq(uid, data, n=[1000]):
    n[0] += 1
    return {"update_id": n[0], "callback_query": {"id": str(n[0]), "chat_instance": "x",
            "from": {"id": uid, "is_bot": False, "first_name": "T"}, "data": data,
            "message": {"message_id": 5, "date": int(time.time()), "chat": {"id": uid, "type": "private"}, "text": "x"}}}


def test_client_books_and_cancels():
    async def run():
        s = FakeSession()
        bot = Bot("123456:TEST", session=s)
        dp = Dispatcher(); dp.include_router(app.router)
        feed = lambda u: dp.feed_raw_update(bot, u)
        sid = app.db.add_service("Стрижка", 60, 500)
        tomorrow = date.today() + timedelta(days=1)
        slot = datetime.combine(tomorrow, datetime.min.time()).replace(hour=12)

        await feed(msg(1, "/start"))
        await feed(cbq(1, app.Svc(id=sid).pack()))
        await feed(cbq(1, app.Day(svc=sid, iso=tomorrow.isoformat()).pack()))
        await feed(cbq(1, app.Slot(svc=sid, stamp=slot.strftime("%Y%m%d%H%M")).pack()))
        await feed(msg(1, "Анна"))
        await feed(msg(1, "12"))
        assert "полностью" in s.sent(1)[-1]
        await feed(msg(1, "+380501112233"))

        rows = app.db.my(1)
        assert len(rows) == 1 and datetime.fromisoformat(rows[0]["start"]) == slot
        assert any("Запись №" in t for t in s.sent(999))  # мастер получил уведомление

        await feed(msg(2, "/schedule"))
        assert s.sent(2)[-1] == "Нет доступа."
        await feed(cbq(2, app.Cancel(id=rows[0]["id"]).pack()))  # чужая отмена не проходит
        assert len(app.db.my(1)) == 1
        await feed(cbq(1, app.Cancel(id=rows[0]["id"]).pack()))
        assert app.db.my(1) == []
        await bot.session.close()
    asyncio.run(run())
