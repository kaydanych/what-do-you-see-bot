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
            "жизни: цвета, предметы, свет, тени — и то, как один и тот же момент "
            "может по-разному открываться каждому из нас. Иногда две фотографии "
            "вдруг совпадают и связываются неожиданным образом.\n\n"
            "Эта игра — маленький повод замечать, ловить моменты, делиться и "
            "смотреть.\n\n"
            "Как это работает: каждое утро в {prompt_time} по Берлину я присылаю "
            "задание — например, «пришли фото с водой». До {deadline} по Берлину "
            "отправь свою интерпретацию задания. Вечером все, кто участвовал, "
            "получат общий коллаж дня.\n\n"
            "Ближе к вечеру я мягко напомню, а потом ещё раз — незадолго до "
            "дедлайна. Хочешь заменить фото? Просто пришли новое — оно заменит "
            "предыдущее. По умолчанию напоминания включены; если хочешь получать "
            "только утреннее задание, напиши /reminders morning. Вернуть оба "
            "напоминания можно командой /reminders all.\n\n"
            "Есть идея для задания? Напиши /suggest_prompt и поделись ею. Если я "
            "выберу её для одного из дней, все увидят, что идея была твоей 💡\n\n"
            "Команды: /start — перезапустить · /today — задание дня · /feedback — "
            "оставить отзыв · /suggest_prompt — предложить задание · /lang — "
            "сменить язык · /stop — отписаться\n\n"
            "Игра всё ещё развивается, и я буду рад любой обратной связи — просто "
            "отправь /feedback и пару слов. Приятных наблюдений!"
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
        "REMINDERS_ASK": (
            "Сколько напоминаний о фото тебе удобно получать?\n\n"
            "Утреннее задание приходит всегда. Можно дополнительно получать "
            "вечернее напоминание и последнее — незадолго до дедлайна, или оставить "
            "только утреннее задание."
        ),
        "REMINDERS_ALL_BUTTON": "Все 3 уведомления",
        "REMINDERS_MORNING_BUTTON": "Только утреннее",
        "REMINDERS_SET_ALL": "Готово — буду присылать оба вечерних напоминания ⏰",
        "REMINDERS_SET_MORNING": "Готово — оставил только утреннее задание 🌤",
        "REMINDERS_CURRENT_ALL": (
            "Сейчас включены утреннее задание и оба вечерних напоминания. "
            "Выбери другой вариант ниже, если хочешь изменить настройку."
        ),
        "REMINDERS_CURRENT_MORNING": (
            "Сейчас приходит только утреннее задание. Выбери другой вариант ниже, "
            "если хочешь изменить настройку."
        ),
        "REMINDERS_USAGE": "Использование: /reminders all или /reminders morning",
        "IDEA_CREDIT": "Идея: {name}",
        "COLLAGE_CAPTION": "🖼 Коллаж дня — участников: {n}. До завтра!",
        "COLLAGE_CAPTION_SOLO": (
            "🖼 Сегодня ты участвовал(а) в одиночку — но коллаж всё равно твой! До завтра!"
        ),
        "COLLAGE_ZOOM": "📎 Полное разрешение — открой, чтобы рассмотреть каждое фото",
        "STREAK": "\n\n🔥 Страйк: {days} дн. подряд — так держать!",
        "TODAY_SUBMITTED": "\n\nТвоё фото уже у меня ✅ (можешь прислать другое — заменю)",
        "TODAY_NOT_SUBMITTED": "\n\nТвоего фото ещё нет — жду до {deadline}!",
        "RATE_THANKS": "Спасибо за оценку! {emoji}",
        "KNOCK_EXPLAIN": (
            "За каждым снимком кто-то стоит. У тебя один стук — постучись в "
            "самый интересный, и автор снимка, набравшего больше всего стуков, "
            "(возможно) откроется и расскажет свою историю."
        ),
        "KNOCK_DONE": (
            "🚪 Ты постучал. Если в эту дверь постучат больше всего, услышим "
            "историю за ней."
        ),
        "KNOCK_TOAST": "🚪 Ты постучал",
        "KNOCK_MOVED": "🚪 Перенёс твой стук на этот снимок",
        "KNOCK_OWN": "Это твой снимок 🙂 постучись в чужой",
        "KNOCK_CLOSED": "Стучать уже поздно — двери на сегодня закрыты.",
        "KNOCK_NOT_YOURS": "Это только для тех, кто прислал фото в тот день.",
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
        "STORY_ASK": (
            "💬 Твоё фото выбрали для «Истории дня»!\n\n"
            "Задание тогда было:\n{prompt}\n\n"
            "Расскажи в паре предложений, почему ты выбрал(а) именно этот кадр? "
            "Просто напиши ответ сюда — я поделюсь твоей историей и этим фото "
            "со всеми участниками игры, под твоим именем 🙂 "
            "(не хочешь — можно не отвечать)"
        ),
        "STORY_THANKS": "Спасибо, что поделился(ась)! Передал организатору 💬",
        "STORY_LIKED": "Твоё ❤️ засчитано — автор увидит!",
        "STORY_UNLIKED": "Ок, убрал ❤️",
        "STORY_PUBLISH": (
            "💬 История дня\n\n"
            "📅 {date} — задание было:\n{prompt}\n\n"
            "{name} рассказывает, почему выбрал(а) это фото:\n«{text}»"
        ),
        # --- the weekly card (Sunday) ---
        # Two messages: the streak leader gets congratulated and asked whether to
        # show the group; everyone else with a full-enough week just gets their
        # card, with nothing to decide.
        "WEEK_CARD": (
            "🔥 {n} дней подряд — это лучшая серия в игре прямо сейчас!\n\n"
            "Ты держишь её дольше всех: {k} из {of} дней на этой неделе, и серия "
            "тянется дальше. Снимаю шляпу 🎩\n\n"
            "Вот твоя неделя одним кадром — она твоя, можешь просто оставить "
            "себе. А можно показать её всем: люди видят коллажи, но почти "
            "никогда — неделю одного человека подряд. Покажем?"
        ),
        "WEEK_GIFT": (
            "🗓 Твоя неделя — {k} из {of} дней.\n\n"
            "Держи её одним кадром, на память. Это только тебе — никто больше "
            "этого не видит."
        ),
        "WEEK_GIFT_STREAK": "\n\nИ ты идёшь {n} дней подряд 🔥",
        "WEEK_BTN_SHARE": "🖼 Показать всем",
        "WEEK_BTN_KEEP": "🤫 Оставить себе",
        "WEEK_CARD_SHARED": "Показал твою неделю всем 🖼 Спасибо!",
        "WEEK_CARD_KEPT": "Ок, она остаётся только у тебя 🤫",
        "WEEK_CARD_GONE": "Эта неделя уже закрыта 🙂",
        "WEEK_CARD_LIKED": "Твоё ❤️ засчитано — автор увидит!",
        "WEEK_CARD_UNLIKED": "Ок, убрал ❤️",
        "WEEK_CARD_PUBLIC": (
            "🔥 Серия недели — {name}\n\n"
            "{n} дней подряд, дольше всех в игре сейчас. Вот эта неделя целиком, "
            "глазами одного человека.\n\n"
            "Показываю с разрешения автора."
        ),
        # --- collage proofing (trusted users check the collage pre-publish) ---
        "PROOF_ASK": (
            "👀 ПРОВЕРКА КОЛЛАЖА — РЕШАЕШЬ ТЫ\n\n"
            "Коллаж дня, фото: {n}. Его ещё никто не видел — он уйдёт всем, "
            "как только ты нажмёшь 👍.\n\n"
            "Бань, только если фото очевидно ломает наше общее пространство: "
            "обнажённость или секс, узнаваемый человек в личном моменте, на "
            "который он явно не соглашался, кровь и насилие крупным планом, "
            "символика ненависти, чужие документы или адрес в кадре, кадр "
            "ради унижения конкретного человека.\n\n"
            "Некрасиво, скучно, плохо снято, не по заданию или просто не твой "
            "вкус — не повод. Сомневаешься — публикуй."
        ),
        "PROOF_ASK_FLAGGED": (
            "👀 ПРОВЕРКА КОЛЛАЖА — РЕШАЕШЬ ТЫ\n\n"
            "Фото: {n}, ещё не опубликовано. Кто-то из дежурных решил, что "
            "здесь что-то переходит границу — нужен свежий взгляд. Видишь то "
            "же самое?\n\n"
            "Планка та же: обнажённость или секс, узнаваемый человек в личном "
            "моменте, кровь и насилие крупным планом, символика ненависти, "
            "чужие документы или адрес в кадре, кадр ради унижения. Не повод: "
            "некрасиво, скучно, не по заданию, не твой вкус. Сомневаешься — "
            "публикуй."
        ),
        "PROOF_BTN_OK": "👍 Всё хорошо",
        "PROOF_BTN_HOLD": "🚫 Забанить",
        "PROOF_BTN_HOLD_YES": "🚫 Точно забанить",
        "PROOF_BTN_BACK": "✅ Передумал(а), всё хорошо",
        "PROOF_CONFIRM": "Точно? Это остановит сегодняшний коллаж для всех.",
        "PROOF_THANKS_OK": "👍 Спасибо — отправляю всем!",
        "PROOF_THANKS_OK_FLAGGED": (
            "Спасибо, записал. Но кто-то уже остановил этот коллаж, так что "
            "сейчас он никуда не уйдёт — его пересмотрят."
        ),
        "PROOF_THANKS_HOLD": "Понял — остановил. Спасибо, что заметил(а).",
        "PROOF_NOTE_ASK": (
            "Если хочешь — напиши парой слов, что именно не так и на каком "
            "фото. Увидит только организатор. Не хочешь — просто не отвечай."
        ),
        "PROOF_NOTE_THANKS": "Передал организатору 🙏",
        "PROOF_DONE": "Уже решено — спасибо всё равно!",
        "PROOF_NOT_YOURS": "Сегодня эта проверка не за тобой 🙂",
        "PROOF_CLOSED_PUBLISHED": "✅ Опубликовано — спасибо за проверку!",
        "PROOF_CLOSED_HELD": (
            "⏸ Остановлено — дальше решает организатор. Спасибо за проверку!"
        ),
        "PROOF_CLOSED_NOTED": "✔️ Записал — спасибо за проверку!",
        # --- verification (a newcomer waits for the organizer's ✅) ---
        "PENDING": (
            "Ты в списке ✅\n\n"
            "Игра маленькая и почти семейная, поэтому организатор впускает "
            "каждого вручную. Напишу тебе сразу, как только тебя впустят — "
            "тогда и начнём 👋"
        ),
        "VERIFY_IDENTITY_ASK": (
            "Привет! Прежде чем впустить тебя в эту закрытую группу, расскажи, "
            "пожалуйста, кто тебя пригласил и как ты знаешь организатора. "
            "Просто ответь здесь — сообщение увидит только организатор."
        ),
        "ORGANIZER_MESSAGE": "💬 Сообщение от организатора:\n\n{text}",
        "PENDING_REPLY_RELAYED": (
            "Спасибо — передал твоё сообщение организатору. Ты пока остаёшься "
            "в списке ожидания; я напишу, как только тебя впустят 👋"
        ),
        "APPROVED": "✅ Тебя впустили — добро пожаловать!",
        "STOPPED": "Ок, больше не буду присылать задания. Захочешь вернуться — /start 👋",
        "KICKED": "Доступ к игре закрыт. Если это ошибка — напиши организатору.",
        # --- Season 2: anonymous visual correspondence ---
        "CORR_ENROLL_OPEN": (
            "📮 Новый сезон: визуальная переписка\n\n"
            "На две недели я случайно соединю тебя с одним человеком. "
            "Во время переписки имён и ников не будет: вы будете знать "
            "друг друга только по фотографиям.\n\n"
            "В понедельник все пары получат одну и ту же точку старта.\n\n"
            "Вы будете по очереди отвечать фотографией на предыдущую. "
            "Ответ можно прислать сразу, но напарник получит его через 6 часов. "
            "До отправки фотографию можно менять. "
            "Цель — цепочка из 10 фото. Если ответа нет сутки или двое, я напомню.\n\n"
            "Участвуй, только если готов постараться довести цепочку до конца. "
            "Выйти или пожаловаться можно в любой момент."
        ),
        "CORR_ENROLL_REMINDER": (
            "📮 Ещё не вижу твоего решения о двухнедельной анонимной "
            "фотопереписке. Ответь до утра понедельника — да или нет одинаково помогут."
        ),
        "CORR_ENROLL_CLOSED": "Запись на этот сезон уже закрыта.",
        "CORR_JOINED": "Ты в игре 📮 В понедельник я соберу пары.",
        "CORR_DECLINED": "Понял — пропускаешь этот сезон.",
        "CORR_STARTER": (
            "📮 Пара собрана. До конца переписки вы не узнаете имён друг друга — "
            "только фотографии.\n\n"
            "Ваша точка старта:\n«{prompt}»\n\n"
            "Твой ход первый. Пришли одну фотографию; затем цепочка пойдёт по очереди до {target} фото."
        ),
        "CORR_WAITER": (
            "📮 Пара собрана. До конца переписки вы не узнаете имён друг друга — "
            "только фотографии.\n\n"
            "Ваша точка старта:\n«{prompt}»\n\n"
            "Первый ход у твоего неизвестного партнёра. Фото придёт сюда сразу, как только оно будет готово. "
            "Цель — {target} фото."
        ),
        "CORR_ALREADY_COMPLETE": "Ваша цепочка уже завершена ✅",
        "CORR_NO_LONGER_ACTIVE": "Эта фотопереписка больше не активна.",
        "CORR_NOT_YOUR_TURN": "Сейчас ход партнёра — подожди его фото 📮",
        "CORR_TOO_SOON": "Фото уже готово, но ход откроется через {remaining}.",
        "CORR_DRAFT_SAVED": (
            "Фото принято, но я ещё НЕ отправил его напарнику.\n\n"
            "Отправлю автоматически через {remaining} — в {time} по Берлину.\n\n"
            "До этого времени можешь прислать другую фотографию: она заменит эту, "
            "и напарник увидит только последнюю версию."
        ),
        "CORR_DRAFT_REPLACED": (
            "Фотографию заменил. Напарнику пока ничего не отправлено.\n\n"
            "Последнюю версию отправлю через {remaining} — в {time} по Берлину. "
            "До этого момента можно заменить её ещё раз."
        ),
        "CORR_TURN_CHANGED": "Ход уже изменился — это фото не добавилось. Проверь переписку.",
        "CORR_RECEIVED": (
            "📮 Фото {position} из {target} в вашей цепочке.\n\n"
            "Твоё задание сейчас: ответить одной фотографией на фото выше.\n\n"
            "Можешь прислать ответ сразу: я сохраню его как черновик "
            "и отправлю напарнику через {wait}. До отправки фотографию можно заменить."
        ),
        "CORR_RECEIVED_FINAL": (
            "📮 Фото {position} из {target} — ваша цепочка завершена ✅\n\n"
            "В конце двух недель пришлю итог всех фотопереписок."
        ),
        "CORR_DELIVERY_FAILED": "Не смог доставить фото. Цепочка остановлена, организатор получил сообщение.",
        "CORR_DELIVERY_DELAYED": (
            "Не удалось доставить фото с первой попытки, но оно сохранено. "
            "Цепочка остаётся активной — я попробую отправить его снова автоматически."
        ),
        "CORR_RETRY_RESUBMIT": (
            "📮 Переписка снова активна, но сохранённое фото потерялось на сервере. "
            "Пожалуйста, пришли его ещё раз."
        ),
        "CORR_SENT": "Фото {position} из {target} доставлено ✅ Теперь ход партнёра.",
        "CORR_SENT_FINAL": (
            "Фото {position} из {target} доставлено. Цепочка завершена ✅\n\n"
            "В конце двух недель пришлю итог всех фотопереписок."
        ),
        "CORR_FINALE_PENDING": (
            "📮 Ваша цепочка уже завершена ✅\n\n"
            "В конце двух недель пришлю итог всех фотопереписок."
        ),
        "CORR_INTRO_OFFER": (
            "Вы две недели разговаривали фотографиями. Хотите познакомиться "
            "с человеком по ту сторону?\n\n"
            "Если согласие будет взаимным, я обменяю ваши Telegram-ники и задам "
            "пару вопросов."
        ),
        "CORR_INTRO_MEET_BUTTON": "👋 Да, хочу познакомиться",
        "CORR_INTRO_ANONYMOUS_BUTTON": "🔒 Остаться анонимными",
        "CORR_INTRO_WAITING": "Запомнил 👋",
        "CORR_INTRO_STAYED_ANONYMOUS": (
            "Хорошо — ваша фотопереписка останется анонимной."
        ),
        "CORR_INTRO_USERNAME_REQUIRED": (
            "Чтобы познакомиться, сначала добавь публичный Telegram-ник в настройках "
            "профиля, а затем нажми кнопку ещё раз."
        ),
        "CORR_INTRO_MUTUAL": (
            "Вы оба хотите познакомиться 👋\n\n"
            "Перед знакомством задам два коротких вопроса, чтобы начать разговор "
            "было проще. Любой из них можно пропустить — никнеймами я обменяю вас "
            "в любом случае."
        ),
        "CORR_INTRO_PHOTO_CAPTION": "Кадр №{position}",
        "CORR_INTRO_PHOTO_FIRST_CAPTION": (
            "Кадры, которые пришли тебе во время переписки:\n\nКадр №{position}"
        ),
        "CORR_INTRO_FAVORITE_ASK": (
            "1/2. Какой из этих кадров запомнился тебе больше всего?"
        ),
        "CORR_INTRO_SKIP_QUESTION_BUTTON": "Пропустить вопрос",
        "CORR_INTRO_REASON_ASK": (
            "Почему именно кадр №{position}? Одной фразы достаточно."
        ),
        "CORR_INTRO_SKIP_REASON_BUTTON": "Пропустить объяснение",
        "CORR_INTRO_QUESTION_ASK": (
            "2/2. Что тебе хочется спросить у человека по ту сторону?"
        ),
        "CORR_INTRO_READY": (
            "Спасибо — всё готово. Я пришлю знакомство, когда второй человек "
            "закончит отвечать, но в любом случае не позднее чем через 24 часа."
        ),
        "CORR_INTRO_REVEAL": (
            "👋 Пора познакомиться\n\n"
            "Человек по ту сторону — {name} @{username}."
        ),
        "CORR_INTRO_FAVORITE_REASON": (
            "Из твоих фотографий {name} особенно запомнился кадр №{position}:\n"
            "«{answer}»"
        ),
        "CORR_INTRO_FAVORITE_ONLY": (
            "Из твоих фотографий {name} особенно запомнился кадр №{position}."
        ),
        "CORR_INTRO_QUESTION_FROM": "Вопрос от {name}:\n«{answer}»",
        "CORR_INTRO_MESSAGE_BUTTON": "Написать {name} →",
        "CORR_INTRO_ALREADY_DECIDED": "Этот выбор уже сохранён.",
        "CORR_INTRO_ALREADY_SENT": "Вы уже познакомились 👋",
        "CORR_NOT_YOURS": "Эта кнопка не от твоей переписки.",
        "CORR_LEFT": "Переписка завершена. Партнёр увидит только, что цепочка остановлена.",
        "CORR_REPORTED": "Жалоба отправлена. Цепочка заморожена.",
        "CORR_REPORT_NOTE": "Если хочешь, напиши следующим сообщением, что случилось. Это увидит только организатор; можно не отвечать.",
        "CORR_REPORT_THANKS": "Спасибо, передал организатору.",
        "CORR_SAFETY_MOVED": "Эта кнопка больше не используется. Если возникла проблема, напиши /feedback.",
        "CORR_PARTNER_ENDED": "Эта цепочка завершена досрочно. Тебе ничего делать не нужно.",
        "CORR_SEASON_CLOSED": "📮 Две недели прошли — сезон фотопереписок закрыт. Спасибо за цепочку.",
        "CORR_SEASON_CANCELLED": "📮 Эта фотопереписка закрыта организатором.",
        "CORR_SEASON_FINISHED": (
            "📮 Второй сезон завершён организатором. Спасибо за вашу фотопереписку."
        ),
        "CORR_PUBLICATION_NOTICE": (
            "📮 Общая публикация второго сезона\n\n"
            "Я готовлю страничку, где участники этого бота смогут посмотреть все "
            "фотодиалоги, созданные во втором сезоне.\n\n"
            "Я планирую добавить туда и вашу фотопереписку. На странице не будет "
            "имён, ников, ссылок на профили или других указаний на авторов.\n\n"
            "Если ты предпочитаешь оставить вашу линию закрытой, нажми кнопку ниже "
            "до {deadline}. Если хотя бы один человек из пары откажется, вся линия "
            "не будет опубликована. Напарник, конечно, не узнает, кто из пары отказался.\n\n"
            "Если к этому воскресенью в линии будет меньше 10 фотографий, я опубликую "
            "её как есть. У вас останется ещё неделя, чтобы завершить диалог, и к "
            "следующим выходным я обновлю страницу.\n\n"
            "Если ты не против публикации, ничего делать не нужно."
        ),
        "CORR_PUBLICATION_PRIVATE": (
            "🔒 Готово. Ваша фотолиния не будет опубликована. Напарник не узнает, "
            "кто из пары отказался. Решение можно изменить до {deadline}."
        ),
        "CORR_PUBLICATION_INCLUDED": "Понял — ваша линия снова может быть опубликована.",
        "CORR_PUBLICATION_CLOSED": "Срок выбора уже закончился.",
        "CORR_TURN_READY": "📸 Шесть часов прошло — теперь можно ответить своей фотографией.",
        "CORR_REMINDER_24": "📮 Твой ход ждёт уже сутки. Не нужно идеального ответа — просто продолжи линию одной фотографией.",
        "CORR_REMINDER_48": "⏳ Цепочка ждёт твоего ответа уже двое суток. Пришли фото, когда сможешь; если не можешь продолжать, заверши цепочку кнопкой ниже.",
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
            "/reminders — настроить вечерние напоминания\n"
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
            "share that with you. We often forget the magic of everyday life: "
            "colours, objects, light, shadows — and how the same moment can mean "
            "something different to every pair of eyes. Sometimes two photos quietly "
            "click and connect in an unexpected way.\n\n"
            "This game is a small nudge to notice, capture, share, and look.\n\n"
            "Here's how it works: every morning at {prompt_time} Berlin time, I'll "
            "send a prompt — for example, “send me a photo with water”. Send me "
            "your interpretation before {deadline} Berlin time. In the evening, "
            "everyone who took part receives that day's photo collage.\n\n"
            "I'll send one reminder in the evening and another shortly before the "
            "deadline. Want to swap your photo? Just send a new one — it replaces "
            "the previous submission. Both reminders are on by default; if you "
            "prefer only the morning prompt, send /reminders morning. Bring them "
            "back with /reminders all.\n\n"
            "Have an idea for a prompt? Send /suggest_prompt with it. If I choose "
            "it as the prompt of the day, everyone will see it was yours 💡\n\n"
            "Commands: /start — restart · /today — today's prompt · /feedback — "
            "share feedback · /suggest_prompt — suggest a prompt · /lang — change "
            "language · /reminders — choose evening reminders · /stop — unsubscribe\n\n"
            "It's still very much a work in progress, so I'd love your feedback — "
            "just send /feedback with a few words. Enjoy noticing!"
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
        "REMINDERS_ASK": (
            "How many photo notifications would you like?\n\n"
            "The morning prompt always arrives. You can also get an evening "
            "reminder and a final nudge shortly before the deadline, or "
            "keep just the morning prompt."
        ),
        "REMINDERS_ALL_BUTTON": "All 3 notifications",
        "REMINDERS_MORNING_BUTTON": "Morning prompt only",
        "REMINDERS_SET_ALL": "Done — I'll send both evening reminders ⏰",
        "REMINDERS_SET_MORNING": "Done — I'll keep it to the morning prompt only 🌤",
        "REMINDERS_CURRENT_ALL": (
            "Your morning prompt and both evening reminders are on. Pick another "
            "option below if you want to change this."
        ),
        "REMINDERS_CURRENT_MORNING": (
            "You're set to receive only the morning prompt. Pick another option "
            "below if you want to change this."
        ),
        "REMINDERS_USAGE": "Usage: /reminders all or /reminders morning",
        "IDEA_CREDIT": "Idea: {name}",
        "COLLAGE_CAPTION": "🖼 Collage of the day — {n} participants. See you tomorrow!",
        "COLLAGE_CAPTION_SOLO": (
            "🖼 You were the only one today — but the collage is still yours! "
            "See you tomorrow!"
        ),
        "COLLAGE_ZOOM": "📎 Full resolution — open it to look closely at every photo",
        "STREAK": "\n\n🔥 {days}-day streak — keep it going!",
        "TODAY_SUBMITTED": "\n\nYour photo is in ✅ (send another one to replace it)",
        "TODAY_NOT_SUBMITTED": "\n\nNo photo from you yet — you have until {deadline}!",
        "RATE_THANKS": "Thanks for rating! {emoji}",
        "KNOCK_EXPLAIN": (
            "There's someone behind every photo. You get one knock — spend it "
            "on the one you're most curious about, and the author of the photo "
            "with the most knocks steps out and tells its story."
        ),
        "KNOCK_DONE": (
            "🚪 Knocked. If this door gets the most knocks, we'll hear its story."
        ),
        "KNOCK_TOAST": "🚪 Knocked",
        "KNOCK_MOVED": "🚪 Moved your knock to this one",
        "KNOCK_OWN": "That one's yours 🙂 knock on someone else's",
        "KNOCK_CLOSED": "Too late to knock — the doors are closed for that day.",
        "KNOCK_NOT_YOURS": "This is for the people who sent a photo that day.",
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
        "STORY_ASK": (
            "💬 Your photo was picked for the “Story of the day”!\n\n"
            "The challenge back then was:\n{prompt}\n\n"
            "Tell me in a sentence or two why you chose this particular shot. "
            "Just write your answer here — I'll share your story and this photo "
            "with everyone in the game, under your name 🙂 "
            "(no pressure — you can skip it)"
        ),
        "STORY_THANKS": "Thanks for sharing! Passed it on to the organizer 💬",
        "STORY_LIKED": "Your ❤️ is in — the author will see it!",
        "STORY_UNLIKED": "OK, took your ❤️ back",
        "STORY_PUBLISH": (
            "💬 Story of the day\n\n"
            "📅 {date} — the challenge was:\n{prompt}\n\n"
            "{name} on why they chose this photo:\n«{text}»"
        ),
        # --- the weekly card (Sunday) ---
        # Two messages: the streak leader gets congratulated and asked whether to
        # show the group; everyone else with a full-enough week just gets their
        # card, with nothing to decide.
        "WEEK_CARD": (
            "🔥 {n} days in a row — the longest streak in the game right now!\n\n"
            "Nobody is holding one longer: {k} of {of} days this week, and the "
            "run keeps going. Hat off to you 🎩\n\n"
            "Here's your week in one picture — it's yours, you can simply keep "
            "it. Or you can show it to everyone: people see the daily collages, "
            "but almost never one person's week in a row. Shall we?"
        ),
        "WEEK_GIFT": (
            "🗓 Your week — {k} of {of} days.\n\n"
            "Here it is in one picture, to keep. This one is just for you — "
            "nobody else sees it."
        ),
        "WEEK_GIFT_STREAK": "\n\nAnd you're {n} days in a row 🔥",
        "WEEK_BTN_SHARE": "🖼 Show everyone",
        "WEEK_BTN_KEEP": "🤫 Keep it to myself",
        "WEEK_CARD_SHARED": "Your week is out there 🖼 Thank you!",
        "WEEK_CARD_KEPT": "OK — it stays with you 🤫",
        "WEEK_CARD_GONE": "That week is already closed 🙂",
        "WEEK_CARD_LIKED": "Your ❤️ is in — the author will see it!",
        "WEEK_CARD_UNLIKED": "OK, took your ❤️ back",
        "WEEK_CARD_PUBLIC": (
            "🔥 Streak of the week — {name}\n\n"
            "{n} days in a row, the longest run in the game right now. Here is "
            "that whole week, through one pair of eyes.\n\n"
            "Shared with the author's blessing."
        ),
        # --- collage proofing (trusted users check the collage pre-publish) ---
        "PROOF_ASK": (
            "👀 COLLAGE CHECK — YOUR CALL\n\n"
            "Today's collage, {n} photo(s). Nobody has seen it yet — it goes "
            "out to everyone the moment you tap 👍.\n\n"
            "Ban it only if a photo would obviously break the space we share: "
            "nudity or sex, someone recognizable in a private moment they "
            "clearly didn't agree to share, graphic blood or violence, hate "
            "symbols, someone's documents or address in the frame, a shot "
            "meant to humiliate a real person.\n\n"
            "Ugly, boring, badly shot, off-prompt or just not your taste — not "
            "reasons. In doubt, publish."
        ),
        "PROOF_ASK_FLAGGED": (
            "👀 COLLAGE CHECK — YOUR CALL\n\n"
            "{n} photo(s), not published yet. Someone else on tonight's check "
            "thought something here crosses a line — fresh eyes needed. Do you "
            "see it too?\n\n"
            "Same bar: nudity or sex, someone recognizable in a private "
            "moment, graphic violence, hate symbols, exposed documents or an "
            "address, a shot meant to humiliate. Not reasons: ugly, boring, "
            "off-prompt, not your taste. In doubt, publish."
        ),
        "PROOF_BTN_OK": "👍 All good",
        "PROOF_BTN_HOLD": "🚫 Ban",
        "PROOF_BTN_HOLD_YES": "🚫 Really ban",
        "PROOF_BTN_BACK": "✅ Changed my mind, all good",
        "PROOF_CONFIRM": "Sure? This stops tonight's collage for everyone.",
        "PROOF_THANKS_OK": "👍 Thanks — sending it out now!",
        "PROOF_THANKS_OK_FLAGGED": (
            "Thanks, noted. Someone else held this collage, so it isn't going "
            "out on this tap — it's being looked at again."
        ),
        "PROOF_THANKS_HOLD": "Got it — on hold. Thank you for catching it.",
        "PROOF_NOTE_ASK": (
            "If you want: a couple of words on what's wrong and which photo. "
            "Only the organizer sees it — or just ignore this."
        ),
        "PROOF_NOTE_THANKS": "Passed it on to the organizer 🙏",
        "PROOF_DONE": "Already handled — thanks anyway!",
        "PROOF_NOT_YOURS": "This check isn't yours tonight 🙂",
        "PROOF_CLOSED_PUBLISHED": "✅ Published — thanks for checking!",
        "PROOF_CLOSED_HELD": (
            "⏸ On hold — the organizer takes it from here. Thanks for checking!"
        ),
        "PROOF_CLOSED_NOTED": "✔️ Noted — thanks for checking!",
        # --- verification (a newcomer waits for the organizer's ✅) ---
        "PENDING": (
            "You're on the list ✅\n\n"
            "This game is small and almost family-sized, so the organizer lets "
            "everyone in by hand. I'll message you the moment you're in — and "
            "then we start 👋"
        ),
        "VERIFY_IDENTITY_ASK": (
            "Hi! Before I let you into this private group, could you tell me "
            "who invited you and how you know the organizer? Just reply here — "
            "only the organizer will see your message."
        ),
        "ORGANIZER_MESSAGE": "💬 Message from the organizer:\n\n{text}",
        "PENDING_REPLY_RELAYED": (
            "Thanks — I've passed your message to the organizer. You're still "
            "on the waiting list for now; I'll message you as soon as you're in 👋"
        ),
        "APPROVED": "✅ You're in — welcome!",
        "STOPPED": "OK, no more challenges from me. Come back anytime with /start 👋",
        "KICKED": "Access to the game is closed. If this is a mistake, contact the organizer.",
        # --- Season 2: anonymous visual correspondence ---
        "CORR_ENROLL_OPEN": (
            "📮 New season: visual correspondence\n\n"
            "For two weeks, I'll randomly connect you with one other person. During the "
            "correspondence, there will be no names or usernames: you'll know each other "
            "only through photographs.\n\n"
            "On Monday, every pair will receive the same starting point.\n\n"
            "You take turns answering the previous photograph with another photograph. "
            "You may submit a reply immediately, but your partner receives it 6 hours "
            "later; you may replace it until delivery. The goal is one chain of 10 "
            "photographs. If a turn waits for "
            "a day or two, I'll send a reminder.\n\n"
            "Join only if you can make a real attempt to carry the chain to its end. You "
            "can still leave or report at any moment."
        ),
        "CORR_ENROLL_REMINDER": (
            "📮 I still don't have your decision about the two-week anonymous photo "
            "correspondence. Please answer by Monday morning — yes and no are equally helpful."
        ),
        "CORR_ENROLL_CLOSED": "Enrollment for this season is already closed.",
        "CORR_JOINED": "You're in 📮 I'll form the pairs on Monday.",
        "CORR_DECLINED": "Got it — you're sitting this season out.",
        "CORR_STARTER": (
            "📮 Your pair is ready. Until the correspondence ends, you won't see each "
            "other's names — only photographs.\n\n"
            "Your starting point:\n“{prompt}”\n\n"
            "You have the first turn. Send one photograph; after that, the chain alternates "
            "until it reaches {target} images."
        ),
        "CORR_WAITER": (
            "📮 Your pair is ready. Until the correspondence ends, you won't see each "
            "other's names — only photographs.\n\n"
            "Your starting point:\n“{prompt}”\n\n"
            "Your unknown partner has the first turn. Their photograph will arrive here "
            "as soon as it is ready. The goal is {target} images."
        ),
        "CORR_ALREADY_COMPLETE": "Your chain is already complete ✅",
        "CORR_NO_LONGER_ACTIVE": "This photo correspondence is no longer active.",
        "CORR_NOT_YOUR_TURN": "It's your partner's turn now — wait for their photograph 📮",
        "CORR_TOO_SOON": "Your photo is ready, but this turn opens in {remaining}.",
        "CORR_DRAFT_SAVED": (
            "Photo accepted, but I have NOT sent it to your partner yet.\n\n"
            "I will send it automatically in {remaining}, at {time} Berlin time.\n\n"
            "Until then, you can send another photograph to replace it. Your partner "
            "will see only the latest version."
        ),
        "CORR_DRAFT_REPLACED": (
            "Photograph replaced. Nothing has been sent to your partner yet.\n\n"
            "I will send the latest version in {remaining}, at {time} Berlin time. "
            "You can replace it again until then."
        ),
        "CORR_TURN_CHANGED": "The turn changed already, so this photo was not added. Check the correspondence.",
        "CORR_RECEIVED": (
            "📮 Photograph {position} of {target} in your chain.\n\n"
            "Your task now: reply to the photograph above with one photograph of your own.\n\n"
            "You may send your answer immediately: I will keep it as "
            "a draft and deliver it to your partner in {wait}. You may replace the photo "
            "until delivery."
        ),
        "CORR_RECEIVED_FINAL": (
            "📮 Photograph {position} of {target} — your chain is complete ✅\n\n"
            "At the end of the two weeks, I'll send the result of all the photo correspondences."
        ),
        "CORR_DELIVERY_FAILED": "I couldn't deliver the photograph. The chain is paused and the organizer has been told.",
        "CORR_DELIVERY_DELAYED": (
            "I couldn't deliver the photograph on the first attempt, but it is saved. "
            "Your chain remains active and I will retry automatically."
        ),
        "CORR_RETRY_RESUBMIT": (
            "📮 Your correspondence is active again, but the saved photograph was lost "
            "on the server. Please send it once more."
        ),
        "CORR_SENT": "Photograph {position} of {target} delivered ✅ Now it's your partner's turn.",
        "CORR_SENT_FINAL": (
            "Photograph {position} of {target} delivered. The chain is complete ✅\n\n"
            "At the end of the two weeks, I'll send the result of all the photo correspondences."
        ),
        "CORR_FINALE_PENDING": (
            "📮 Your chain is already complete ✅\n\n"
            "At the end of the two weeks, I'll send the result of all the photo correspondences."
        ),
        "CORR_INTRO_OFFER": (
            "For two weeks, you spoke through photographs. Would you like to meet the "
            "person on the other side?\n\n"
            "If you both say yes, I’ll share your Telegram usernames with each other "
            "and ask you a couple of questions."
        ),
        "CORR_INTRO_MEET_BUTTON": "👋 Yes, I’d like to meet",
        "CORR_INTRO_ANONYMOUS_BUTTON": "🔒 Stay anonymous",
        "CORR_INTRO_WAITING": "Got it 👋",
        "CORR_INTRO_STAYED_ANONYMOUS": (
            "All right — your photo correspondence will remain anonymous."
        ),
        "CORR_INTRO_USERNAME_REQUIRED": (
            "To meet, first add a public Telegram username in your profile settings, "
            "then tap the button again."
        ),
        "CORR_INTRO_MUTUAL": (
            "You’d both like to meet 👋\n\n"
            "Before I introduce you, I’ll ask two short questions to make starting the "
            "conversation easier. You can skip either one — I’ll share your usernames "
            "in any case."
        ),
        "CORR_INTRO_PHOTO_CAPTION": "Photograph #{position}",
        "CORR_INTRO_PHOTO_FIRST_CAPTION": (
            "The photographs you received during the correspondence:\n\n"
            "Photograph #{position}"
        ),
        "CORR_INTRO_FAVORITE_ASK": (
            "1/2. Which of these photographs stayed with you most?"
        ),
        "CORR_INTRO_SKIP_QUESTION_BUTTON": "Skip this question",
        "CORR_INTRO_REASON_ASK": (
            "Why photograph #{position}? One sentence is enough."
        ),
        "CORR_INTRO_SKIP_REASON_BUTTON": "Skip the explanation",
        "CORR_INTRO_QUESTION_ASK": (
            "2/2. What would you like to ask the person on the other side?"
        ),
        "CORR_INTRO_READY": (
            "Thank you — you’re all set. I’ll introduce you when the other person "
            "finishes answering, or within 24 hours at the latest."
        ),
        "CORR_INTRO_REVEAL": (
            "👋 Time to meet\n\n"
            "The person on the other side is {name} @{username}."
        ),
        "CORR_INTRO_FAVORITE_REASON": (
            "Of your photographs, #{position} stayed with {name} most:\n"
            "“{answer}”"
        ),
        "CORR_INTRO_FAVORITE_ONLY": (
            "Of your photographs, #{position} stayed with {name} most."
        ),
        "CORR_INTRO_QUESTION_FROM": "A question from {name}:\n“{answer}”",
        "CORR_INTRO_MESSAGE_BUTTON": "Message {name} →",
        "CORR_INTRO_ALREADY_DECIDED": "That choice has already been saved.",
        "CORR_INTRO_ALREADY_SENT": "You’ve already been introduced 👋",
        "CORR_NOT_YOURS": "That button does not belong to your correspondence.",
        "CORR_LEFT": "The correspondence has ended. Your partner will only be told that the chain stopped.",
        "CORR_REPORTED": "Report sent. The chain is frozen.",
        "CORR_REPORT_NOTE": "If you want, send one more message explaining what happened. Only the organizer will see it; you can also ignore this.",
        "CORR_REPORT_THANKS": "Thank you. I've passed it to the organizer.",
        "CORR_SAFETY_MOVED": "This button is no longer used. If there is a problem, send /feedback.",
        "CORR_PARTNER_ENDED": "This chain has ended early. There is nothing you need to do.",
        "CORR_SEASON_CLOSED": "📮 The two weeks are over and the correspondence season is closed. Thank you for your chain.",
        "CORR_SEASON_CANCELLED": "📮 This photo correspondence was closed by the organizer.",
        "CORR_SEASON_FINISHED": (
            "📮 Season 2 has been finished by the organizer. Thank you for your photo correspondence."
        ),
        "CORR_PUBLICATION_NOTICE": (
            "📮 Sharing Season 2\n\n"
            "I'm preparing a page where people who use this bot can see all the photo "
            "dialogues created during Season 2.\n\n"
            "I plan to include your photo correspondence. The page will show no names, "
            "usernames, profile links, or other clues to the authors.\n\n"
            "If you would rather keep your line private, tap the button below by "
            "{deadline}. If either person opts out, the whole line will not be published. "
            "Your partner will not be told who opted out.\n\n"
            "If your line has fewer than 10 photographs this Sunday, I will publish it "
            "as it is. You will have another week to finish the dialogue, and I will "
            "update the page the following weekend.\n\n"
            "If you're comfortable with publication, you don't need to do anything."
        ),
        "CORR_PUBLICATION_PRIVATE": (
            "🔒 Done. Your photo line will not be published. Your partner will not be "
            "told who opted out. You can change this choice until {deadline}."
        ),
        "CORR_PUBLICATION_INCLUDED": "Got it — your line may be included again.",
        "CORR_PUBLICATION_CLOSED": "The choice deadline has passed.",
        "CORR_TURN_READY": "📸 Six hours have passed — you can now answer with your photograph.",
        "CORR_REMINDER_24": "📮 Your turn has been waiting for a day. It doesn't need to be a perfect answer — just continue the line with one photograph.",
        "CORR_REMINDER_48": "⏳ The chain has been waiting for your answer for two days. Send a photo when you can; if you cannot continue, use the button below to end the chain.",
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
            "/reminders — choose evening reminders\n"
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
