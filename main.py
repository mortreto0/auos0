#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sqlite3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ----------------------------
# إعداد تسجيل الأخطاء
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ----------------------------
# الإعدادات العامة
# ----------------------------
MANDATORY_CHANNEL = "@bay_un"
DATABASE_NAME     = "bot.db"

# ----------------------------
# دوال قاعدة البيانات
# ----------------------------
def get_db_connection():
    return sqlite3.connect(DATABASE_NAME, check_same_thread=False)

def initialize_database():
    conn = get_db_connection()
    cur = conn.cursor()
    # جدول إعدادات المستخدم
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            mandatory_message TEXT DEFAULT 'يرجى الاشتراك في القناة.',
            vote_emoji TEXT DEFAULT '❤️',
            vote_notification_enabled INTEGER DEFAULT 0
        )
    """)
    # جدول المشاركات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            vote_count INTEGER DEFAULT 0
        )
    """)
    # جدول التصويتات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            voter_id INTEGER,
            submission_id INTEGER,
            UNIQUE(voter_id, submission_id)
        )
    """)
    conn.commit()
    conn.close()

def ensure_user_settings(user_id: int):
    conn = get_db_connection()
    conn.execute(
        "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()
    conn.close()

def fetch_user_settings(user_id: int):
    ensure_user_settings(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT vote_emoji, channel_id, mandatory_message, vote_notification_enabled
          FROM user_settings
         WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row  # (emoji, channel_id, mandatory_message, notif_flag)

# ----------------------------
# فحص الاشتراك بالقناة
# ----------------------------
async def is_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(MANDATORY_CHANNEL, user_id)
        return member.status in ("member", "creator", "administrator")
    except Exception:
        return False

def build_subscription_prompt():
    kb = [
        [InlineKeyboardButton(
            "🔗 الاشتراك في القناة",
            url=f"https://t.me/{MANDATORY_CHANNEL.lstrip('@')}"
        )],
        [InlineKeyboardButton("✅ تحقق الاشتراك", callback_data="check_sub")]
    ]
    text = (
        f"للاستخدام، يجب أولاً الاشتراك في قناتنا: {MANDATORY_CHANNEL}\n\n"
        "بعد الانضمام، اضغط «✅ تحقق الاشتراك»."
    )
    return text, InlineKeyboardMarkup(kb)

# ----------------------------
# بناء القوائم وأزرار الإجراءات
# ----------------------------
def build_main_menu(first_name, emoji, channel_id, msg, notif_flag):
    text = (
        f"· مرحبًا بك {first_name}!\n\n"
        f"- الإيموجي: {emoji}\n"
        f"- قناة النشر: <code>{channel_id or 'لم يتم التعيين'}</code>\n"
        f"- رسالة الاشتراك: {msg}\n\n"
        "· أرسل نصًا أو وسائط للنشر"
    )
    kb = [
        [InlineKeyboardButton("✏️ كليشة الاشتراك", callback_data="set_msg")],
        [
            InlineKeyboardButton("🔗 ربط القناة", callback_data="set_chan"),
            InlineKeyboardButton("😊 تعيين إيموجي", callback_data="set_emoji"),
        ],
        [
            InlineKeyboardButton(
                f"🔔 إشعار تصويت {'✅' if notif_flag else '❌'}",
                callback_data="toggle_notif",
            )
        ],
    ]
    return text, InlineKeyboardMarkup(kb)

def build_confirmation_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافق", callback_data="confirm"),
            InlineKeyboardButton("❌ رفض", callback_data="reject"),
        ]
    ])

# ----------------------------
# معالجات التحديثات
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        text, markup = build_subscription_prompt()
        await update.effective_message.reply_text(text, reply_markup=markup)
        return

    emoji, chan, msg, notif = fetch_user_settings(user.id)
    text, markup = build_main_menu(user.first_name, emoji, chan, msg, notif)
    await update.effective_message.reply_text(text, reply_markup=markup, parse_mode="HTML")

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if await is_subscribed(context.bot, user.id):
        await query.message.delete()
        await start(update, context)
    else:
        await query.answer(
            "لم يتم العثور على اشتراك. يرجى الانضمام أولاً ثم إعادة المحاولة.",
            show_alert=True
        )

async def handle_menu_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user = query.from_user

    ensure_user_settings(user.id)

    if action in ("set_msg", "set_emoji", "set_chan"):
        prompts = {
            "set_msg":   "🔧 أرسل كليشة الاشتراك الجديدة:",
            "set_emoji": "🔧 أرسل الإيموجي الجديد:",
            "set_chan":  "🔧 قم بتوجيه رسالة من قناتك لربطها:",
        }
        back = InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data="back")]])
        await query.edit_message_text(prompts[action], reply_markup=back)
        context.user_data['action'] = action
        return

    if action == "toggle_notif":
        conn = get_db_connection()
        conn.execute(
            "UPDATE user_settings SET vote_notification_enabled = 1 - vote_notification_enabled WHERE user_id = ?",
            (user.id,)
        )
        conn.commit()
        conn.close()
        emoji, chan, msg_setting, notif_flag = fetch_user_settings(user.id)
        _, new_markup = build_main_menu(user.first_name, emoji, chan, msg_setting, notif_flag)
        await query.edit_message_reply_markup(new_markup)
        return

    if action == "back":
        emoji, chan, msg, notif = fetch_user_settings(user.id)
        text, markup = build_main_menu(user.first_name, emoji, chan, msg, notif)
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_subscribed(context.bot, user.id):
        text, markup = build_subscription_prompt()
        await update.effective_message.reply_text(text, reply_markup=markup)
        return

    m = update.effective_message
    action = context.user_data.get('action')

    if action:
        if action == 'set_msg' and m.text:
            conn = get_db_connection()
            conn.execute(
                "UPDATE user_settings SET mandatory_message = ? WHERE user_id = ?",
                (m.text, user.id)
            )
            conn.commit()
            conn.close()
            await m.reply_text("✅ تم تحديث كليشة الاشتراك.")
        elif action == 'set_emoji' and m.text:
            conn = get_db_connection()
            conn.execute(
                "UPDATE user_settings SET vote_emoji = ? WHERE user_id = ?",
                (m.text.strip(), user.id)
            )
            conn.commit()
            conn.close()
            await m.reply_text("✅ تم تحديث الإيموجي.")
        elif action == 'set_chan' and m.forward_from_chat:
            chan_id = m.forward_from_chat.id
            conn = get_db_connection()
            conn.execute(
                "UPDATE user_settings SET channel_id = ? WHERE user_id = ?",
                (chan_id, user.id)
            )
            conn.commit()
            conn.close()
            await m.reply_text(f"✅ تم ربط القناة: <code>{chan_id}</code>", parse_mode="HTML")
        else:
            await m.reply_text("⚠️ المعطى غير صالح.")
        context.user_data.pop('action')
        return

    # نشر الرسالة بعد تأكيد المستخدم
    context.user_data['pending_message'] = m
    await m.reply_text("⚠️ هل تريد نشر هذه الرسالة؟", reply_markup=build_confirmation_menu())

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user = query.from_user

    if action == "confirm":
        pending = context.user_data.pop("pending_message", None)
        if not pending:
            return await query.message.reply_text("⚠️ لا يوجد رسالة معلق للنشر.")

        emoji, chan, _, _ = fetch_user_settings(user.id)
        if not chan:
            return await query.message.reply_text("⚠️ لم يتم ربط القناة بعد.")

        result = await context.bot.copy_message(
            chat_id=chan,
            from_chat_id=pending.chat_id,
            message_id=pending.message_id,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(fetch_user_settings(user.id)[0], callback_data="vote")]
            ])
        )
        text_to_store = pending.caption or pending.text or ""
        new_msg_id    = result.message_id

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO submissions (user_id, text, chat_id, message_id) VALUES (?, ?, ?, ?)",
            (user.id, text_to_store, chan, new_msg_id)
        )
        conn.commit()
        conn.close()

        await query.message.reply_text("✅ تم النشر!")
    else:
        context.user_data.pop("pending_message", None)
        await query.message.reply_text("❌ تم إلغاء النشر.")

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    voter = query.from_user
    msg   = query.message

    if not await is_subscribed(context.bot, voter.id):
        return await query.answer("يرجى الاشتراك أولاً في القناة.", show_alert=True)

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, vote_count, chat_id, user_id, text FROM submissions WHERE message_id = ?",
        (msg.message_id,)
    )
    sub = cur.fetchone()
    if not sub:
        conn.close()
        return
    sub_id, cnt, chan, owner, sub_text = sub

    member = await context.bot.get_chat_member(chan, voter.id)
    cur.execute(
        "SELECT mandatory_message, vote_emoji, vote_notification_enabled FROM user_settings WHERE user_id = ?",
        (owner,)
    )
    req_msg, emoji, notify = cur.fetchone() or ("يرجى الاشتراك أولًا!", "❤️", 0)

    if member.status not in ("member", "administrator", "creator"):
        conn.close()
        return await query.answer(req_msg, show_alert=True)

    cur.execute(
        "SELECT 1 FROM votes WHERE voter_id = ? AND submission_id = ?",
        (voter.id, sub_id)
    )
    if cur.fetchone():
        cur.execute("DELETE FROM votes WHERE voter_id = ? AND submission_id = ?", (voter.id, sub_id))
        cur.execute("UPDATE submissions SET vote_count = vote_count - 1 WHERE id = ?", (sub_id,))
        new_cnt = cnt - 1
        await query.answer("تم سحب التصويت")
    else:
        cur.execute("INSERT INTO votes (voter_id, submission_id) VALUES (?,?)", (voter.id, sub_id))
        cur.execute("UPDATE submissions SET vote_count = vote_count + 1 WHERE id = ?", (sub_id,))
        new_cnt = cnt + 1
        await query.answer("تم التصويت")
        if notify:
            lang = voter.language_code or "unknown"
            text_notify = (
                f"<b>• تصويت جديد على منشور {emoji}:</b> {sub_text}\n"
                "---------------------------\n"
                f"- <b>اسم المستخدم</b>: {voter.full_name}\n"
                f"- <b>ايدي المستخدم</b>: {voter.id}\n"
                f"- <b>معرف المستخدم</b>: @{voter.username or 'لا يوجد'}\n"
                f"- <b>لغة الجهاز</b>: {lang}\n\n"
                f"<b>• عدد الأصوات الكلي</b>: {new_cnt}"
            )
            await context.bot.send_message(owner, text_notify, parse_mode="HTML")

    conn.commit()
    conn.close()

    await query.edit_message_reply_markup(
        InlineKeyboardMarkup([[InlineKeyboardButton(f"{emoji} {new_cnt}", callback_data="vote")]])
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception occurred:", exc_info=context.error)

# ----------------------------
# نقطة البداية وتشغيل البوت
# ----------------------------
def main():
    initialize_database()
    app = Application.builder().token("8033592945:AAGKTB23ILjz3dGqG3nIVyF5GqyluO3wns0").build()

    app.bot.set_my_commands([BotCommand("start", "رسالة البدء")], language_code="ar")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_subscription, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(handle_menu_query, pattern="^(set_msg|set_emoji|set_chan|toggle_notif|back)$"))
    app.add_handler(CallbackQueryHandler(handle_confirmation, pattern="^(confirm|reject)$"))
    app.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()