import telebot, json
bot = telebot.TeleBot('8879689840:AAGxX1xVpZlOAFAb3jV6DrYUbaRCacWqoqY')

# Test: tg-emoji tag directly in button text (raw, no parse_mode)
keyboard = {
    "keyboard": [
        [
            {"text": "<tg-emoji emoji-id=\"5375464961822695044\">🔍</tg-emoji> Kino Qidirish", "style": "primary"},
            {"text": "<tg-emoji emoji-id=\"5443127283898405358\">💾</tg-emoji> Saqlanganlar", "style": "success"}
        ],
        [
            {"text": "<tg-emoji emoji-id=\"5197269100878907942\">ℹ️</tg-emoji> Yordam", "style": "danger"}
        ]
    ],
    "resize_keyboard": True
}
try:
    bot.send_message(8363733728, "Test: tg-emoji in button text", reply_markup=json.dumps(keyboard))
    print('SUCCESS')
except Exception as e:
    print('ERROR:', e)
