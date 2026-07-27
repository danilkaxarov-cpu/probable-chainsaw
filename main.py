import os
import asyncio
import aiosqlite
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from datetime import timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command

TOKEN = "8969732309:AAFXb0-QapYhxftl9zEPiBEBtvBT3RLJME"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Заглушка для Render, чтобы он видел открытый порт
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

async def init_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                chat_id INTEGER,
                user_id INTEGER,
                messages_count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                chat_id INTEGER,
                user_id INTEGER,
                warn_count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.commit()

async def is_admin(message: types.Message) -> bool:
    member = await message.chat.get_member(message.from_user.id)
    return member.status in ("administrator", "creator")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def track_stats(message: types.Message):
    if message.text and message.text.startswith("/"):
        return

    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            INSERT INTO stats (chat_id, user_id, messages_count) 
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET messages_count = messages_count + 1
        """, (message.chat.id, message.from_user.id))
        await db.commit()

@dp.message(Command("stats"))
async def get_stats(message: types.Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT messages_count FROM stats WHERE chat_id = ? AND user_id = ?", 
                              (message.chat.id, target.id)) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0
        
        async with db.execute("SELECT warn_count FROM warns WHERE chat_id = ? AND user_id = ?", 
                              (message.chat.id, target.id)) as cursor:
            row_warns = await cursor.fetchone()
            warns = row_warns[0] if row_warns else 0

    await message.reply(f"📊 **Статистика {target.first_name}:**\n"
                        f"✉️ Сообщений: {count}\n"
                        f"⚠️ Варнов: {warns}/3", parse_mode="Markdown")

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message):
    if not await is_admin(message):
        return await message.reply("❌ Эта команда только для админов.")
    if not message.reply_to_message:
        return await message.reply("Ответьте на сообщение нарушителя.")

    target = message.reply_to_message.from_user
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            INSERT INTO warns (chat_id, user_id, warn_count) 
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET warn_count = warn_count + 1
        """, (message.chat.id, target.id))
        await db.commit()

        async with db.execute("SELECT warn_count FROM warns WHERE chat_id = ? AND user_id = ?", 
                              (message.chat.id, target.id)) as cursor:
            row = await cursor.fetchone()
            warns = row[0]

    if warns >= 3:
        await message.chat.ban(target.id)
        await db.execute("DELETE FROM warns WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id))
        await db.commit()
        await message.reply(f"🚫 {target.first_name} получил(а) 3/3 варнов и переходит в бан!")
    else:
        await message.reply(f"⚠️ {target.first_name} получил(а) варн! ({warns}/3)")

@dp.message(Command("mute"))
async def cmd_mute(message: types.Message):
    if not await is_admin(message):
        return await message.reply("❌ Эта команда только для админов.")
    if not message.reply_to_message:
        return await message.reply("Ответьте на сообщение нарушителя.")

    args = message.text.split()
    duration = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
    target = message.reply_to_message.from_user

    until_date = timedelta(minutes=duration)
    permissions = types.ChatPermissions(can_send_messages=False)
    await message.chat.restrict(target.id, permissions=permissions, until_date=until_date)
    await message.reply(f"🔇 {target.first_name} замучен(а) на {duration} мин.")

@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if not await is_admin(message):
        return await message.reply("❌ Эта команда только для админов.")
    if not message.reply_to_message:
        return await message.reply("Ответьте на сообщение нарушителя.")

    target = message.reply_to_message.from_user
    await message.chat.ban(target.id)
    await message.reply(f"🚫 {target.first_name} успешно забанен(а).")

async def main():
    # Запускаем фоновый веб-сервер для порта Render
    threading.Thread(target=run_health_check_server, daemon=True).start()
    
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
