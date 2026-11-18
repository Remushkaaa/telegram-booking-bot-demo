"""Бот записи клиентов: услуга → день → время → контакты. Отмена, расписание мастера, напоминания за сутки.

Запуск: BOT_TOKEN=... ADMIN_IDS=123 python bot.py
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from booking import Booking

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
db = Booking(os.getenv("DB_PATH", "booking.db"))
router = Router()
DAYS_AHEAD = 7


class Svc(CallbackData, prefix="svc"):
    id: int


class Day(CallbackData, prefix="day"):
    svc: int
    iso: str


class Slot(CallbackData, prefix="slot"):
    svc: int
    stamp: str  # "203001141200": двоеточие в callback-данных запрещено, поэтому без разделителей


class Cancel(CallbackData, prefix="cancel"):
    id: int


class Contact(StatesGroup):
    name = State()
    phone = State()


@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    for s in db.services():
        kb.button(text=f"{s['name']} · {s['minutes']} мин · {s['price']:.0f} ₴", callback_data=Svc(id=s["id"]))
    kb.adjust(1)
    await m.answer("Здравствуйте! Выберите услугу для записи:", reply_markup=kb.as_markup())


@router.callback_query(Svc.filter())
async def pick_day(cb: CallbackQuery, callback_data: Svc):
    await cb.answer()
    kb = InlineKeyboardBuilder()
    for i in range(DAYS_AHEAD):
        d = date.today() + timedelta(days=i)
        if db.free_slots(callback_data.id, d):
            kb.button(text=d.strftime("%d.%m"), callback_data=Day(svc=callback_data.id, iso=d.isoformat()))
    kb.adjust(4)
    await cb.message.answer("Выберите день:" if kb.buttons else "На ближайшую неделю мест нет 😔",
                            reply_markup=kb.as_markup())


@router.callback_query(Day.filter())
async def pick_time(cb: CallbackQuery, callback_data: Day):
    await cb.answer()
    slots = db.free_slots(callback_data.svc, date.fromisoformat(callback_data.iso))
    kb = InlineKeyboardBuilder()
    for t in slots:
        kb.button(text=t.strftime("%H:%M"), callback_data=Slot(svc=callback_data.svc, stamp=t.strftime("%Y%m%d%H%M")))
    kb.adjust(4)
    await cb.message.answer("Свободное время:" if slots else "На этот день всё занято.", reply_markup=kb.as_markup())


@router.callback_query(Slot.filter())
async def pick_slot(cb: CallbackQuery, callback_data: Slot, state: FSMContext):
    await cb.answer()
    await state.update_data(svc=callback_data.svc, iso=datetime.strptime(callback_data.stamp, "%Y%m%d%H%M").isoformat())
    await state.set_state(Contact.name)
    await cb.message.answer("Как вас зовут?")


@router.message(Contact.name, F.text)
async def get_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(Contact.phone)
    await m.answer("Телефон для связи:")


@router.message(Contact.phone, F.text)
async def get_phone(m: Message, state: FSMContext):
    if sum(ch.isdigit() for ch in m.text) < 10:
        return await m.answer("Введите номер полностью, например +380501112233.")
    d = await state.get_data()
    await state.clear()
    start_at = datetime.fromisoformat(d["iso"])
    try:
        aid = db.book(m.from_user.id, d["name"], m.text.strip(), d["svc"], start_at)
    except ValueError as e:  # время успели занять
        return await m.answer(f"{e}. Нажмите /start и выберите другое.")
    await m.answer(f"Вы записаны ✅ №{aid}, {start_at:%d.%m в %H:%M}. Напомню за сутки. Отмена: /my")
    for admin in ADMIN_IDS:
        await m.bot.send_message(admin, f"🆕 Запись №{aid}: {d['name']}, {m.text.strip()}, {start_at:%d.%m %H:%M}")


@router.message(Command("my"))
async def my(m: Message):
    rows = db.my(m.from_user.id)
    if not rows:
        return await m.answer("Активных записей нет.")
    for r in rows:
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отменить", callback_data=Cancel(id=r["id"]))
        await m.answer(f"№{r['id']} · {r['service']} · {datetime.fromisoformat(r['start']):%d.%m %H:%M}",
                       reply_markup=kb.as_markup())


@router.callback_query(Cancel.filter())
async def cancel(cb: CallbackQuery, callback_data: Cancel):
    ok = db.cancel(callback_data.id, user_id=cb.from_user.id)
    await cb.answer("Запись отменена" if ok else "Не получилось отменить", show_alert=not ok)
    if ok:
        await cb.message.edit_text(f"№{callback_data.id} — отменена")


@router.message(Command("schedule"))
async def schedule(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return await m.answer("Нет доступа.")
    rows = db.schedule(date.today())
    text = "\n".join(f"{datetime.fromisoformat(r['start']):%H:%M} — {r['client']}, {r['service']}, {r['phone']}"
                     for r in rows)
    await m.answer(text or "Сегодня записей нет.")


async def reminders(bot: Bot):
    while True:
        for r in db.due_reminders(datetime.now()):
            try:
                await bot.send_message(r["user_id"], f"Напоминаю: завтра {datetime.fromisoformat(r['start']):%H:%M}, {r['service']} 🙂")
            except Exception:
                logging.info("Клиент недоступен")
        await asyncio.sleep(600)


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(os.environ["BOT_TOKEN"])
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(reminders(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
