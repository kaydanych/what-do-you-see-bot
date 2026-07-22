# Per-user localized texts. Users pick their language after /start (or via
# /lang); prompts from the library are always sent verbatim, whatever language
# they were written in.

DEFAULT_LANG = "en"

# Shown before the user has picked a language — deliberately bilingual.
CHOOSE_LANG = "Choose your language / Выбери язык:"

LANG_BUTTONS = [("English 🇬🇧", "en"), ("Русский 🇷🇺", "ru")]

STRINGS = {
    "ru": {
        "LANG_SET": "Готово, дальше общаемся по-русски 🇷🇺",
        "WELCOME": (
            "Привет, {name}, добро пожаловать в маленькую игру, которую я придумал!\n\n"
            "Мне нравится замечать мир вокруг через фотографии, и хочется "
            "поделиться этим с тобой. Мы так часто не замечаем магию обычной "
            "жизни — цвета, кожа, предметы, то, как один кадр может значить "
            "столько разного для разных пар глаз, как две фотографии могут вдруг "
            "совпасть и связаться на каком-то более глубоком уровне. Эта игра — "
            "маленький повод замечать, ловить, делиться и смотреть.\n\n"
            "Как это работает. Каждое утро в {prompt_time} (по Берлину) я "
            "присылаю задание — например, «пришли фото с водой». До {deadline} ты "
            "отправляешь мне своё фото, понимая задание так, как тебе близко, а "
            "вечером все, кто участвовал, получают общий коллаж дня. Ближе к "
            "вечеру я мягко напомню, и ещё раз — незадолго до дедлайна. Хочешь "
            "заменить фото? Просто "
            "пришли новое — оно заменит старое.\n\n"
            "Есть своя идея для задания? Напиши /suggest_prompt со своей идеей — "
            "если она станет заданием дня, все увидят, что её автор — ты 💡\n\n"
            "Команды: /start — перезапустить, /today — задание дня, "
            "/feedback — обратная связь, /suggest_prompt — предложить задание, "
            "/lang — язык, /stop — отписаться.\n\n"
            "Разработка всё ещё в процессе — буду рад любой обратной связи: "
            "просто напиши /feedback и пару слов. Вперед замечать!"
        ),
        "PROMPT": "📸 Задание на сегодня:\n\n{text}",
        "PROMPT_TODAY_ACTIVE": "Сегодняшнее задание ещё в силе — лови:",
        "ACCEPTED": "Фото принято ✅ Коллаж пришлю после {deadline}.",
        "REPLACED": "Понял, заменил твоё фото на новое ✅",
        "ALBUM_ONE": "Из альбома я беру только одно фото — взял первое 😉",
        "PHOTO_FAILED": (
            "Не смог получить твоё фото — похоже, связь с Telegram подвела 😔 "
            "Пришли его ещё раз, пожалуйста."
        ),
        "LATE": "Увы, приём фото на сегодня уже закрыт 😔 Жди новое задание завтра!",
        "NO_ACTIVE_DAY": (
            "Сейчас нет активного задания. Задания приходят каждое утро в {prompt_time} ⏰"
        ),
        "NOT_A_PHOTO": (
            "Мне нужна именно фотография 🙂 Пришли фото — и ты в сегодняшнем коллаже."
        ),
        "TEXT_NUDGE": "Словами не отделаешься — жду фото 😉",
        "REMINDER": (
            "⏰ Напоминание: дедлайн в {deadline}, а твоего фото ещё нет!\n\n"
            "Задание на сегодня:\n{text}"
        ),
        "FINAL_REMINDER": (
            "🚨 Последний звонок: до дедлайна {minutes} мин, а твоего фото ещё нет!\n\n"
            "Задание на сегодня:\n{text}"
        ),
        "IDEA_CREDIT": "Идея: {name}",
        "COLLAGE_CAPTION": "🖼 Коллаж дня — участников: {n}. До завтра!",
        "COLLAGE_CAPTION_SOLO": (
            "🖼 Сегодня ты участвовал(а) в одиночку — но коллаж всё равно твой! До завтра!"
        ),
        "COLLAGE_ZOOM": "📎 Полное разрешение — открой, чтобы рассмотреть каждое фото",
        "TODAY_SUBMITTED": "\n\nТвоё фото уже у меня ✅ (можешь прислать другое — заменю)",
        "TODAY_NOT_SUBMITTED": "\n\nТвоего фото ещё нет — жду до {deadline}!",
        "RATE_THANKS": "Спасибо за оценку! {emoji}",
        "POLL_THANKS": "Спасибо! Твой голос учтён.",
        "POLL_CLOSED": "Опрос закрыт — голосование завершено.",
        "TZ_SUFFIX": "по Берлину",
        "FEEDBACK_ASK": (
            "Напиши свой отзыв следующим сообщением — я передам его организатору 🙏"
        ),
        "FEEDBACK_THANKS": "Спасибо! Передал организатору 🙏",
        "SUGGEST_ASK": (
            "Напиши свою идею для задания следующим сообщением. Если она станет "
            "заданием дня — все узнают, что это твоя 💡"
        ),
        "SUGGEST_THANKS": (
            "Отличная идея, спасибо! Передал организатору — если она станет "
            "заданием дня, укажу твоё авторство 💡"
        ),
        "STOPPED": "Ок, больше не буду присылать задания. Захочешь вернуться — /start 👋",
        "KICKED": "Доступ к игре закрыт. Если это ошибка — напиши организатору.",
        "HELP": (
            "Как это работает:\n"
            "• каждое утро в {prompt_time} приходит задание\n"
            "• до {deadline} присылаешь одно фото (новое заменяет старое)\n"
            "• после {deadline} все участники дня получают общий коллаж\n"
            "• кнопки 🔥/👍/😐 под коллажем — оцени день, счёт видят все\n"
            "• все времена — по Берлину (CET/CEST)\n\n"
            "/today — задание дня и статус твоего фото\n"
            "/feedback <текст> — обратная связь организатору\n"
            "/suggest_prompt <идея> — предложить задание дня\n"
            "/lang — сменить язык\n"
            "/stop — отписаться\n\n"
            "Код живёт на GitHub — github.com/kaydanych/what-do-you-see-bot"
        ),
    },
    "en": {
        "LANG_SET": "Done, English it is 🇬🇧",
        "WELCOME": (
            "Hey {name}, welcome to the little game I made!\n\n"
            "I love noticing the world around us through photos, and I want to "
            "share that with you. We so often forget the magic of everyday life — "
            "the colours, the skin, the objects, how one moment can mean so many "
            "things to different pairs of eyes, how two photos can quietly click "
            "and connect on some deeper level. This game is a small nudge to "
            "notice, to capture, to share, and to look.\n\n"
            "Here's how it works. Every morning at {prompt_time} (Berlin time) I "
            "send a prompt — e.g. “send me a photo with water”. You send me "
            "your photo before {deadline}, following the prompt however it "
            "makes sense to you, and in the evening everyone who took part gets "
            "the collage of the day. I'll nudge you once in the evening, and once "
            "more just before the deadline. "
            "Want to swap your photo? Just send a new one and it replaces the old.\n\n"
            "Got an idea for a prompt yourself? Send /suggest_prompt with your "
            "idea — if I pick it as the prompt of the day, everyone will see it "
            "was yours 💡\n\n"
            "Commands: /start — restart, /today — today's prompt, "
            "/feedback — share feedback, /suggest_prompt — suggest a prompt, "
            "/lang — language, /stop — unsubscribe.\n\n"
            "Still very much a work in progress — I'd love your feedback: just "
            "send /feedback with a few words. Enjoy noticing!"
        ),
        "PROMPT": "📸 Today's challenge:\n\n{text}",
        "PROMPT_TODAY_ACTIVE": "Today's challenge is still on — here it is:",
        "ACCEPTED": "Photo accepted ✅ I'll send the collage after {deadline}.",
        "REPLACED": "Got it — replaced your photo with the new one ✅",
        "ALBUM_ONE": "I only take one photo from an album — kept the first one 😉",
        "PHOTO_FAILED": (
            "I couldn't fetch your photo — looks like the connection to Telegram "
            "hiccuped 😔 Please send it again."
        ),
        "LATE": "Sorry, today's submissions are closed 😔 A new challenge comes tomorrow!",
        "NO_ACTIVE_DAY": (
            "There's no active challenge right now. Challenges arrive every morning "
            "at {prompt_time} ⏰"
        ),
        "NOT_A_PHOTO": (
            "I need an actual photo 🙂 Send one and you're in today's collage."
        ),
        "TEXT_NUDGE": "Words won't cut it — I'm waiting for a photo 😉",
        "REMINDER": (
            "⏰ Reminder: the deadline is {deadline} and I don't have your photo yet!\n\n"
            "Today's challenge:\n{text}"
        ),
        "FINAL_REMINDER": (
            "🚨 Last call: {minutes} min to the deadline and I still don't have "
            "your photo!\n\nToday's challenge:\n{text}"
        ),
        "IDEA_CREDIT": "Idea: {name}",
        "COLLAGE_CAPTION": "🖼 Collage of the day — {n} participants. See you tomorrow!",
        "COLLAGE_CAPTION_SOLO": (
            "🖼 You were the only one today — but the collage is still yours! "
            "See you tomorrow!"
        ),
        "COLLAGE_ZOOM": "📎 Full resolution — open it to look closely at every photo",
        "TODAY_SUBMITTED": "\n\nYour photo is in ✅ (send another one to replace it)",
        "TODAY_NOT_SUBMITTED": "\n\nNo photo from you yet — you have until {deadline}!",
        "RATE_THANKS": "Thanks for rating! {emoji}",
        "POLL_THANKS": "Thanks! Your vote is counted.",
        "POLL_CLOSED": "This poll is closed — voting has ended.",
        "TZ_SUFFIX": "Berlin time",
        "FEEDBACK_ASK": (
            "Send your feedback as your next message — I'll pass it on to the organizer 🙏"
        ),
        "FEEDBACK_THANKS": "Thank you! Passed it on to the organizer 🙏",
        "SUGGEST_ASK": (
            "Send your challenge idea as your next message. If it becomes the "
            "challenge of the day, everyone will know it's yours 💡"
        ),
        "SUGGEST_THANKS": (
            "Great idea, thanks! Passed it to the organizer — if it becomes the "
            "challenge of the day, you'll get the credit 💡"
        ),
        "STOPPED": "OK, no more challenges from me. Come back anytime with /start 👋",
        "KICKED": "Access to the game is closed. If this is a mistake, contact the organizer.",
        "HELP": (
            "How it works:\n"
            "• every morning at {prompt_time} a challenge arrives\n"
            "• you send one photo before {deadline} (a new one replaces the old)\n"
            "• after {deadline} everyone who took part gets the collage\n"
            "• tap 🔥/👍/😐 under the collage to rate the day — tallies are "
            "visible to everyone\n"
            "• all times are Berlin time (CET/CEST)\n\n"
            "/today — today's challenge and your photo status\n"
            "/feedback <text> — send feedback to the organizer\n"
            "/suggest_prompt <idea> — suggest a challenge of the day\n"
            "/lang — change language\n"
            "/stop — unsubscribe\n\n"
            "The code lives on GitHub — github.com/kaydanych/what-do-you-see-bot"
        ),
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    table = STRINGS.get(lang or DEFAULT_LANG, STRINGS[DEFAULT_LANG])
    s = table[key]
    return s.format(**kwargs) if kwargs else s
