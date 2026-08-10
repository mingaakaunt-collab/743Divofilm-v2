import telebot
import json
import os
import database
from telebot import custom_filters
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

database.init_db()

TOKEN = os.environ.get("BOT_TOKEN", "8879689840:AAGxX1xVpZlOAFAb3jV6DrYUbaRCacWqoqY")
state_storage = StateMemoryStorage()
bot = telebot.TeleBot(TOKEN, state_storage=state_storage)
# Retrieve bot username once for link generation (will be set lazily)
BOT_USERNAME = None


ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "6316926082").split(",")))

class MovieState(StatesGroup):
    code = State()
    name = State()
    lang = State()
    quality = State()

class SearchState(StatesGroup):
    code = State()

class ChannelState(StatesGroup):
    chat_id = State()
    name = State()
    url = State()
    style = State()
    emoji_id = State()

class BroadcastState(StatesGroup):
    message = State()

class RemoveChannelState(StatesGroup):
    chat_id = State()

def premium_emoji(emoji_id, fallback="👍"):
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

def colorful_reply_button(text, style="default"):
    return {"text": text, "style": style}

def get_main_menu():
    keyboard = [
        [colorful_reply_button("🔍 Kino Qidirish", "primary"), colorful_reply_button("💾 Saqlanganlar", "success")],
        [colorful_reply_button("ℹ️ Yordam", "danger")]
    ]
    return json.dumps({"keyboard": keyboard, "resize_keyboard": True})

def get_admin_keyboard():
    keyboard = [
        [colorful_reply_button("📢 Majburiy obuna", "danger")],
        [colorful_reply_button("📊 Statistika", "primary"), colorful_reply_button("✉️ Rassilka", "success")],
        [colorful_reply_button("🎬 Yangi kino", "danger"), colorful_reply_button("🏠 Asosiy menyu", "default")]
    ]
    return json.dumps({"keyboard": keyboard, "resize_keyboard": True})

def get_admin_channels_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Kanal qo'shish", callback_data="admin_add_ch"),
        InlineKeyboardButton("➖ Kanal o'chirish", callback_data="admin_rem_ch"),
        InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="admin_list_ch")
    )
    return markup

def get_movie_keyboard(code, user_id=None):
    """Return inline keyboard with only the **Saqlash** button.
    The share functionality has been removed per user request.
    """
    markup = {
        "inline_keyboard": [
            [
                {"text": "💾 Saqlash", "callback_data": f"save_{code}", "style": "success"}
            ]
        ]
    }
    return json.dumps(markup)

# Inline query handler – allows users to share a movie by code
@bot.inline_handler(func=lambda query: bool(query.query))
def inline_movie_share(inline_query):
    code = inline_query.query.strip()
    movie = database.get_movie(code)
    if not movie:
        # No movie found – show no results
        bot.answer_inline_query(inline_query.id, results=[])
        return
    # Generate a one‑time secret link for sharing, include referrer ID
    secret = database.create_share_secret(code, referrer_id=inline_query.from_user.id)
    # Ensure BOT_USERNAME is set
    global BOT_USERNAME
    if BOT_USERNAME is None:
        try:
            BOT_USERNAME = bot.get_me().username
        except Exception:
            BOT_USERNAME = "your_bot_username"
    share_url = f"https://t.me/{BOT_USERNAME}?start=share_{secret}"
    # Build an article result that sends the share link as a message
    result = telebot.types.InlineQueryResultArticle(
        id=code,
        title=movie['name'],
        description=f"{movie['lang']} | {movie['quality']} – share link",
        input_message_content=telebot.types.InputTextMessageContent(
            message_text=share_url,
            parse_mode="HTML",
            disable_web_page_preview=False,
        ),
        thumb_url=movie.get('thumb_url', ''),
    )
    bot.answer_inline_query(inline_query.id, results=[result], cache_time=0)


# --- MAJBURIY OBUNA TEKSHIRUVI ---
def check_subscription(user_id):
    if user_id in ADMIN_IDS: return []
    channels = database.get_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch['chat_id'], user_id)
            if member.status in ['left', 'kicked']:
                if not database.has_join_request(user_id, ch['chat_id']):
                    not_subscribed.append(ch)
        except Exception as e:
            print(f"Error checking sub for {ch['chat_id']}: {e}")
            if not database.has_join_request(user_id, ch['chat_id']):
                not_subscribed.append(ch)
    return not_subscribed

def send_subscription_warning(chat_id, not_subscribed):
    inline_keyboard = []
    for ch in not_subscribed:
        btn = {"text": ch['name'], "url": ch['url']}
        if ch.get('style'):
            btn["style"] = ch['style']
        if ch.get('emoji_id') and ch['emoji_id'] != "0":
            btn["emoji_id"] = ch['emoji_id']
        inline_keyboard.append([btn])
    inline_keyboard.append([{"text": "Tekshirish", "callback_data": "check_sub", "style": "success", "emoji_id": "6296367896398399651"}])
    
    markup = json.dumps({"inline_keyboard": inline_keyboard})
    text = f"{premium_emoji('6296341890371422476', '❗️')} Kechirasiz, botimizdan to‘liq foydalanish uchun quyidagi kanallarga a‘zo bo‘ling {premium_emoji('6296303781126604562', '👇')}"
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

# Zayavkalarni ushlab qolish (qabul qilmaydi, shunchaki ro'yxatga oladi)
@bot.chat_join_request_handler
def handle_join_request(request):
    print(f"Zayavka tushdi: User {request.from_user.id} -> Chat {request.chat.id}")
    database.add_join_request(request.from_user.id, request.chat.id)

def handle_start_deep_link(message):
    """Process /start commands that contain a deep‑link token.
    Supported tokens:
    - ``movie_<code>``: direct movie code link.
    - ``share_<secret>``: one‑time secret link generated by the share button.
    If the user is subscribed to mandatory channels, the bot will send the movie.
    """
    text = message.text or ""
    parts = text.split()
    if len(parts) < 2:
        return False  # not a deep link
    token = parts[1]
    # Direct code link
    if token.startswith('movie_'):
        code = token.split('_', 1)[1]
        user_id = message.from_user.id
        not_subscribed = check_subscription(user_id)
        if not_subscribed:
            send_subscription_warning(message.chat.id, not_subscribed)
            return True
        movie = database.get_movie(code)
        if movie:
            caption = f"🎬 Nomi: <b>{movie['name']}</b>\n🇺🇿 Til: <b>{movie['lang']}</b>\n🎞 Sifati: <b>{movie['quality']}</b>"
            try:
                bot.send_video(message.chat.id, movie['file_id'], caption=caption, parse_mode="HTML", reply_markup=get_movie_keyboard(code), protect_content=True)
            except Exception:
                bot.send_message(message.chat.id, "Kino yuborishda xatolik: Video yaroqsiz.")
        else:
            bot.send_message(message.chat.id, "❌ Bunday kod bilan kino topilmadi.")
        return True
    # One‑time secret share link
    if token.startswith('share_'):
        secret = token.split('_', 1)[1]
        user_id = message.from_user.id
        not_subscribed = check_subscription(user_id)
        if not_subscribed:
            send_subscription_warning(message.chat.id, not_subscribed)
            return True
        movie = database.get_movie_by_secret(secret)
        if movie:
            caption = f"🎬 Nomi: <b>{movie['name']}</b>\n🇺🇿 Til: <b>{movie['lang']}</b>\n🎞 Sifati: <b>{movie['quality']}</b>"
            try:
                bot.send_video(message.chat.id, movie['file_id'], caption=caption, parse_mode="HTML", reply_markup=get_movie_keyboard(movie['code']), protect_content=True)
            except Exception:
                bot.send_message(message.chat.id, "Kino yuborishda xatolik: Video yaroqsiz.")
        else:
            bot.send_message(message.chat.id, "❌ Invalid or expired share link.")
        return True
    return False

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id in ADMIN_IDS:
        bot.send_message(message.chat.id, "👨‍💻 <b>Admin panelga xush kelibsiz!</b>", parse_mode="HTML", reply_markup=get_admin_keyboard())

@bot.message_handler(commands=['start'])
def start_handler(message):
    # Attempt deep link handling; if not a deep link, send welcome message
    if not handle_start_deep_link(message):
        user_first = message.from_user.first_name
        bot.send_message(message.chat.id,
                         f"Salom, <b>{user_first}</b>! Botga hush kelibsiz.",
                         parse_mode="HTML",
                         reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda call: call.data == 'check_sub')
def check_sub_callback(call):
    not_subscribed = check_subscription(call.from_user.id)
    if not not_subscribed:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Botdan toliq foydalanishingiz mumkun", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Kechirasiz kanallarga toliq obuna bolmagansz", show_alert=True)

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(message.chat.id, "✉️ Xabarni kiriting (barcha foydalanuvchilarga yuboriladi):")
    bot.set_state(message.from_user.id, BroadcastState.message, message.chat.id)

@bot.message_handler(state=BroadcastState.message)
def send_broadcast(message):
    text = message.text
    # fetch all user IDs from DB
    user_ids = database.get_all_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass
    bot.send_message(message.chat.id, f"✅ Xabar {sent} foydalanuvchiga yuborildi.")
    bot.delete_state(message.from_user.id, message.chat.id)

# --- MAJBURIY OBUNA ADMIN FSM ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_channels_callback(call):
    if call.from_user.id not in ADMIN_IDS: return
    if call.data == "admin_add_ch":
        bot.send_message(call.message.chat.id, "Kanalning ID raqamini (yoki @username) kiriting:\n\n💡 <i>Maslahat: Agar kanal maxfiy bo'lsa va ID sini bilmasangiz, shunchaki u yerdagi biron xabarni menga FORWARD (uzatib) yuboring!</i>", parse_mode="HTML")
        bot.set_state(call.from_user.id, ChannelState.chat_id, call.message.chat.id)
    elif call.data == "admin_rem_ch":
        bot.send_message(call.message.chat.id, "O'chirmoqchi bo'lgan kanal ID sini kiriting:")
        bot.set_state(call.from_user.id, RemoveChannelState.chat_id, call.message.chat.id)
    elif call.data == "admin_list_ch":
        channels = database.get_channels()
        if not channels:
            bot.send_message(call.message.chat.id, "Kanallar yo'q.")
            return
        text = "📋 <b>Majburiy kanallar ro'yxati:</b>\n\n"
        for idx, ch in enumerate(channels, 1):
            text += f"{idx}. <b>{ch['name']}</b> (<code>{ch['chat_id']}</code>)\n"
        bot.send_message(call.message.chat.id, text, parse_mode="HTML")

@bot.message_handler(state=ChannelState.chat_id, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def add_ch_id(message):
    chat_id = message.text
    if message.forward_from_chat and message.forward_from_chat.type == 'channel':
        chat_id = str(message.forward_from_chat.id)
        
    if not chat_id:
        bot.send_message(message.chat.id, "Iltimos, kanal ID sini matn orqali yozing yoki kanaldan xabar forward qiling.")
        return

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: 
        data['chat_id'] = chat_id
    bot.send_message(message.chat.id, f"✅ Qabul qilindi: <b>{chat_id}</b>\n\nEndi kanalning tugmada chiqadigan nomini kiriting:", parse_mode="HTML")
    bot.set_state(message.from_user.id, ChannelState.name, message.chat.id)

@bot.message_handler(state=ChannelState.name)
def add_ch_name(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['name'] = message.text
    bot.send_message(message.chat.id, "Endi kanalning invite ssilkasini kiriting (https://t.me/...):")
    bot.set_state(message.from_user.id, ChannelState.url, message.chat.id)

@bot.message_handler(state=ChannelState.url)
def add_ch_url(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['url'] = message.text
    bot.send_message(message.chat.id, "Tugma qaysi rangda chiqishini xohlaysiz? Yozib yuboring (masalan: primary, success, danger, default):")
    bot.set_state(message.from_user.id, ChannelState.style, message.chat.id)

@bot.message_handler(state=ChannelState.style)
def add_ch_style(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['style'] = message.text
    bot.send_message(message.chat.id, "Premium Emoji ID kiriting (Agar yo'q bo'lsa yoki kerak bo'lmasa `0` deb yozing):", parse_mode="Markdown")
    bot.set_state(message.from_user.id, ChannelState.emoji_id, message.chat.id)

@bot.message_handler(state=ChannelState.emoji_id)
def add_ch_emoji_id(message):
    emoji_id = "" if message.text == "0" else message.text
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        database.add_channel(data['chat_id'], data['name'], data['url'], data['style'], emoji_id)
    bot.send_message(message.chat.id, "✅ Kanal bazaga rang va emoji bilan muvaffaqiyatli qo'shildi!")
    bot.delete_state(message.from_user.id, message.chat.id)

@bot.message_handler(state=RemoveChannelState.chat_id)
def remove_ch_id(message):
    database.remove_channel(message.text)
    bot.send_message(message.chat.id, "✅ Kanal o'chirildi (agar mavjud bo'lsa).")
    bot.delete_state(message.from_user.id, message.chat.id)

# --- QOLGAN FUNKSIYALAR ---
@bot.channel_post_handler(content_types=['video', 'document'])
def handle_channel_post(message):
    file_id = message.video.file_id if message.video else (message.document.file_id if message.document else None)
    if file_id:
        admin_id = ADMIN_IDS[0]
        bot.send_message(admin_id, "📥 Kanaldan yangi kino/video qabul qilindi!\n\nIltimos, ushbu kino uchun <b>KOD</b> kiriting:", parse_mode="HTML")
        bot.set_state(admin_id, MovieState.code, admin_id)
        with bot.retrieve_data(admin_id, admin_id) as data:
            data['file_id'] = file_id
            data['message_id'] = message.message_id
            data['channel_id'] = message.chat.id

@bot.message_handler(state=MovieState.code)
def get_code(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['code'] = message.text
    bot.send_message(message.chat.id, "Kino nomini yozing:")
    bot.set_state(message.from_user.id, MovieState.name, message.chat.id)

@bot.message_handler(state=MovieState.name)
def get_name(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['name'] = message.text
    bot.send_message(message.chat.id, "Kino tilini yozing (masalan: O'zbekcha):")
    bot.set_state(message.from_user.id, MovieState.lang, message.chat.id)

@bot.message_handler(state=MovieState.lang)
def get_lang(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data: data['lang'] = message.text
    bot.send_message(message.chat.id, "Kino sifatini yozing (masalan: 1080p, 720p):")
    bot.set_state(message.from_user.id, MovieState.quality, message.chat.id)

@bot.message_handler(state=MovieState.quality)
def get_quality(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        code, file_id, name, lang, quality = data['code'], data['file_id'], data['name'], data['lang'], message.text
        database.add_movie(code, file_id, name, lang, quality, data.get('message_id'), data.get('channel_id'))
    bot.send_message(message.chat.id, f"✅ <b>Kino bazaga saqlandi!</b>\n\n📌 <b>Kod:</b> {code}\n🎬 <b>Nom:</b> {name}\n🇺🇿 <b>Til:</b> {lang}\n🎞 <b>Sifat:</b> {quality}", parse_mode="HTML")
    bot.delete_state(message.from_user.id, message.chat.id)

@bot.message_handler(state=SearchState.code)
def search_movie(message):
    user_id = message.from_user.id
    not_subscribed = check_subscription(user_id)
    if not_subscribed:
        send_subscription_warning(message.chat.id, not_subscribed)
        bot.delete_state(user_id, message.chat.id)
        return

    code = message.text
    movie = database.get_movie(code)
    if movie:
        caption = f"🎬 Nomi: <b>{movie['name']}</b>\n🇺🇿 Tili: <b>{movie['lang']}</b>\n🎞 Sifati: <b>{movie['quality']}</b>"
        try:
            bot.send_video(message.chat.id, movie['file_id'], caption=caption, parse_mode="HTML", reply_markup=get_movie_keyboard(code), protect_content=True)
        except Exception:
            bot.send_message(message.chat.id, "Kino yuborishda xatolik: Video yaroqsiz.")
    else:
        bot.send_message(message.chat.id, "❌ Bunday kod bilan kino topilmadi.")
    bot.delete_state(message.from_user.id, message.chat.id)

@bot.message_handler(func=lambda message: True, state=None)
def text_handler(message):
    text = message.text
    user_id = message.from_user.id
    database.add_user(user_id)
    
    if text == "📢 Majburiy obuna" and user_id in ADMIN_IDS:
        bot.send_message(message.chat.id, "Majburiy obuna sozlamalari:", reply_markup=get_admin_channels_menu())
        return

    # Check sub before user actions
    if text in ["🔍 Kino Qidirish", "💾 Saqlanganlar", "ℹ️ Yordam"] or not text.startswith('/'):
        not_subscribed = check_subscription(user_id)
        if not_subscribed:
            send_subscription_warning(message.chat.id, not_subscribed)
            return
            
    if text == "🔍 Kino Qidirish":
        bot.send_message(message.chat.id, "✍️ Iltimos, topmoqchi bo'lgan kino kodini yozing:")
        bot.set_state(message.from_user.id, SearchState.code, message.chat.id)
    elif text == "💾 Saqlanganlar":
        saved = database.get_saved_movies(user_id)
        if not saved:
            bot.send_message(message.chat.id, "📭 Sizda hozircha saqlangan kinolar yo'q.\n\n💡 Kino topib, <b>💾 Saqlash</b> tugmasini bosing!", parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, f"💾 <b>Saqlangan kinolar ({len(saved)} ta):</b>", parse_mode="HTML")
            for movie in saved:
                caption = f"🎬 <b>{movie['name']}</b>\n🇺🇿 Til: {movie['lang']}\n🎞 Sifat: {movie['quality']}\n📌 Kod: <code>{movie['code']}</code>"
                markup = json.dumps({"inline_keyboard": [[{"text": "🗑 O'chirish", "callback_data": f"unsave_{movie['code']}", "style": "danger"}]]})
                try:
                    bot.send_video(message.chat.id, movie['file_id'], caption=caption, parse_mode="HTML", reply_markup=markup, protect_content=True)
                except:
                    bot.send_message(message.chat.id, caption, parse_mode="HTML", reply_markup=markup)
    elif text == "ℹ️ Yordam":
        # urllib is not imported, so we use a pre-encoded string or just encode on the fly if needed
        # pre-encoded: Salom%2C%20%40Dinofilmuzbot%20boyicha%20murojat%20qilyabman%20%E2%9D%A3
        url = "https://t.me/dinofuzadmin?text=Salom%2C%20%40Dinofilmuzbot%20boyicha%20murojat%20qilyabman%20%E2%9D%A3"
        markup = json.dumps({"inline_keyboard": [[{"text": "👨‍💻 Adminga yozish", "url": url, "style": "primary"}]]})
        bot.send_message(message.chat.id, "Admin bilan bog'lanish uchun quyidagi tugmani bosing:", reply_markup=markup)
    elif text == "🏠 Asosiy menyu":
        bot.send_message(message.chat.id, "Asosiy menyuga qaytdingiz.", reply_markup=get_main_menu())
    elif text == "✉️ Rassilka" and user_id in ADMIN_IDS:
        bot.send_message(message.chat.id, "✉️ Xabarni kiriting (barcha foydalanuvchilarga yuboriladi):")
        bot.set_state(message.from_user.id, BroadcastState.message, message.chat.id)
    elif text == "📊 Statistika" and user_id in ADMIN_IDS:
        total_users = database.get_user_count()
        new_users = database.get_new_user_count(7)
        total_movies = database.get_movie_count()
        total_channels = len(database.get_channels())
        stats_msg = (
            f"<b>📊 Bot statistikasiga xush kelibsiz!</b>\n\n"
            f"👥 Foydalanuvochilar: {total_users}\n"
            f"🆕 Oxirgi 7 kunda ro‘yxatga olingan: {new_users}\n"
            f"🎬 Kinolar: {total_movies}\n"
            f"📢 Majburiy kanallar: {total_channels}"
        )
        bot.send_message(message.chat.id, stats_msg, parse_mode="HTML")
    elif text == "✉️ Rassilka" and user_id in ADMIN_IDS:
        bot.send_message(message.chat.id, "Rassilka funksiyasi tayyorlanmoqda.")
    elif text == "🎬 Yangi kino" and user_id in ADMIN_IDS:
        bot.send_message(message.chat.id, "Buning uchun bot ulanadigan kanalga yangi video yuboring, bot o'zi sizdan ma'lumotlarni so'raydi!")
    else:
        if not text.startswith('/'):
            movie = database.get_movie(text)
            if movie:
                caption = f"🎬 Nomi: <b>{movie['name']}</b>\n🇺🇿 Tili: <b>{movie['lang']}</b>\n🎞 Sifati: <b>{movie['quality']}</b>"
                try: bot.send_video(message.chat.id, movie['file_id'], caption=caption, parse_mode="HTML", reply_markup=get_movie_keyboard(text), protect_content=True)
                except: bot.send_message(message.chat.id, "❌ Kino topilmadi yoki o'chirilgan.")
            else:
                bot.send_message(message.chat.id, "❌ Bunday kod bilan kino topilmadi.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_'))
def save_movie_callback(call):
    not_subscribed = check_subscription(call.from_user.id)
    if not_subscribed:
        bot.answer_callback_query(call.id, "Avval kanallarga obuna bo'ling!", show_alert=True)
        send_subscription_warning(call.message.chat.id, not_subscribed)
        return
    code = call.data.split('_', 1)[1]
    database.save_movie(call.from_user.id, code)
    bot.answer_callback_query(call.id, "✅ Kino saqlanganlarga qo'shildi!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('unsave_'))
def unsave_movie_callback(call):
    code = call.data.split('_', 1)[1]
    database.remove_saved_movie(call.from_user.id, code)
    bot.answer_callback_query(call.id, "🗑 Kino saqlanganlardan o'chirildi!", show_alert=True)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

bot.add_custom_filter(custom_filters.StateFilter(bot))

if __name__ == '__main__':
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot ishlayapti!")
        def log_message(self, format, *args):
            pass  # loglarni o'chirish

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Health check server {port}-portda ishga tushdi.")

    print("Kino bot ishga tushdi...")
    try:
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True, allowed_updates=['message', 'callback_query', 'channel_post', 'chat_join_request'])
    except Exception as e:
        print(f"Xatolik yuz berdi: {e}")
