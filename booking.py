"""Логика записи клиентов: услуги, свободные слоты, запись и отмена (SQLite)."""
import sqlite3
from datetime import date, datetime, timedelta

WORK_START, WORK_END = 10, 19  # рабочий день с 10:00 до 19:00


class Booking:
    def __init__(self, path=":memory:"):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS services(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            minutes INTEGER NOT NULL CHECK(minutes > 0), price REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS appointments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, client TEXT, phone TEXT,
            service_id INTEGER NOT NULL REFERENCES services(id),
            start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active');
        """)

    def add_service(self, name, minutes, price):
        with self.con:
            cur = self.con.execute("INSERT INTO services(name,minutes,price) VALUES(?,?,?)", (name, minutes, price))
        return cur.lastrowid

    def services(self):
        return self.con.execute("SELECT * FROM services ORDER BY name").fetchall()

    def _busy(self, day):
        rows = self.con.execute(
            "SELECT start, end FROM appointments WHERE status='active' AND substr(start,1,10)=?",
            (day.isoformat(),)).fetchall()
        return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]

    def free_slots(self, service_id, day, now=None, step=30):
        """Свободные времена начала на день: не в прошлом, не пересекаются с чужими записями."""
        now = now or datetime.now()
        minutes = self.con.execute("SELECT minutes FROM services WHERE id=?", (service_id,)).fetchone()["minutes"]
        busy, slots = self._busy(day), []
        t = datetime.combine(day, datetime.min.time()).replace(hour=WORK_START)
        close = t.replace(hour=WORK_END)
        while t + timedelta(minutes=minutes) <= close:
            end = t + timedelta(minutes=minutes)
            if t > now and all(end <= b0 or t >= b1 for b0, b1 in busy):
                slots.append(t)
            t += timedelta(minutes=step)
        return slots

    def book(self, user_id, client, phone, service_id, start, now=None):
        if start not in self.free_slots(service_id, start.date(), now):
            raise ValueError("Это время уже занято или недоступно")
        minutes = self.con.execute("SELECT minutes FROM services WHERE id=?", (service_id,)).fetchone()["minutes"]
        with self.con:
            cur = self.con.execute(
                "INSERT INTO appointments(user_id,client,phone,service_id,start,end) VALUES(?,?,?,?,?,?)",
                (user_id, client, phone, service_id, start.isoformat(),
                 (start + timedelta(minutes=minutes)).isoformat()))
        return cur.lastrowid

    def my(self, user_id):
        return self.con.execute(
            "SELECT a.*, s.name AS service FROM appointments a JOIN services s ON s.id=a.service_id "
            "WHERE a.user_id=? AND a.status='active' AND a.start>? ORDER BY a.start",
            (user_id, datetime.now().isoformat())).fetchall()

    def cancel(self, appointment_id, user_id=None):
        """Клиент отменяет только свои записи; админ (user_id=None) — любые."""
        sql, args = "UPDATE appointments SET status='cancelled' WHERE id=? AND status='active'", [appointment_id]
        if user_id is not None:
            sql += " AND user_id=?"; args.append(user_id)
        with self.con:
            return self.con.execute(sql, args).rowcount == 1

    def schedule(self, day):
        return self.con.execute(
            "SELECT a.*, s.name AS service FROM appointments a JOIN services s ON s.id=a.service_id "
            "WHERE a.status='active' AND substr(a.start,1,10)=? ORDER BY a.start", (day.isoformat(),)).fetchall()

    def due_reminders(self, now, hours=24):
        """Записи, до которых осталось меньше `hours` часов и по которым ещё не напоминали."""
        self.con.execute("CREATE TABLE IF NOT EXISTS reminded(id INTEGER PRIMARY KEY)")
        rows = self.con.execute(
            "SELECT a.*, s.name AS service FROM appointments a JOIN services s ON s.id=a.service_id "
            "WHERE a.status='active' AND a.start>? AND a.start<=? AND a.id NOT IN (SELECT id FROM reminded)",
            (now.isoformat(), (now + timedelta(hours=hours)).isoformat())).fetchall()
        with self.con:
            self.con.executemany("INSERT OR IGNORE INTO reminded(id) VALUES(?)", [(r["id"],) for r in rows])
        return rows
