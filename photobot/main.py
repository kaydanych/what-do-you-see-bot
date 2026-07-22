import html
import logging
import traceback
from logging.handlers import RotatingFileHandler

from telegram import LinkPreviewOptions, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import config, db, handlers_admin as adm, handlers_user as usr, jobs, version

log = logging.getLogger(__name__)


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_h = RotatingFileHandler(
        config.LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_h)
    root.addHandler(console)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every unhandled exception and DM it to the admins."""
    log.error("Unhandled exception", exc_info=context.error)
    tb = "".join(
        traceback.format_exception(None, context.error, context.error.__traceback__)
    )
    where = ""
    if isinstance(update, Update) and update.effective_user:
        where = f" (update from {update.effective_user.id})"
    text = f"🔥 Error{where}:\n<pre>{html.escape(tb[-3000:])}</pre>"
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            log.exception("failed to report error to admin %s", admin_id)


async def notify_deploy(app: Application) -> None:
    """DM the admins once when new code starts running.

    update.sh stamps data/deploy_info on every deploy; the last announced
    commit is kept in the DB, so plain restarts and NAS reboots stay silent.
    """
    info = version.read_deploy_info()
    commit = info.get("commit")
    if not commit or commit == db.get_setting("deployed_commit"):
        return
    text = f"🚀 Deployed {version.describe(info)}"
    for admin_id in config.ADMIN_IDS:
        try:
            await app.bot.send_message(admin_id, text)
        except Exception:
            log.exception("failed to send deploy notice to admin %s", admin_id)
    db.set_setting("deployed_commit", commit)


async def access_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """First thing every update hits (group -3). When ALLOWED_USER_IDS is set
    (private/test bot), silently drop anyone not on the list and stop all further
    handlers. Empty allowlist = open bot, so production is unaffected."""
    if not config.ALLOWED_USER_IDS:
        return
    user = update.effective_user
    if user and user.id in config.ALLOWED_USER_IDS:
        return
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                "🔒 This is a private test bot."
            )
        except Exception:
            pass
    raise ApplicationHandlerStop


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route documents: admin .txt = prompt import, images = submission."""
    doc = update.message.document
    mime = doc.mime_type or ""
    if (
        update.effective_user.id in config.ADMIN_IDS
        and (mime.startswith("text/") or doc.file_name.lower().endswith(".txt"))
    ):
        await adm.import_prompts_file(update, context)
    elif mime.startswith("image/"):
        await usr.on_photo(update, context)
    else:
        await usr.on_other(update, context)


def build_app() -> Application:
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .defaults(Defaults(link_preview_options=LinkPreviewOptions(is_disabled=True)))
        # Defaults are 5s each; the NAS network hiccups, so give it more room to
        # open the connection and pull photo bytes before giving up.
        .connect_timeout(20.0)
        .read_timeout(20.0)
        .write_timeout(20.0)
        .pool_timeout(5.0)
        .post_init(notify_deploy)
        .build()
    )

    # Access gate: runs before everything (group -3). On a private/test bot it
    # blocks non-allowlisted users; on prod (empty allowlist) it's a no-op.
    app.add_handler(TypeHandler(Update, access_gate), group=-3)

    # Any command cancels a pending /feedback or /suggest_prompt text capture.
    # Group -1 runs before the command handlers below, without consuming them.
    app.add_handler(MessageHandler(filters.COMMAND, usr.clear_awaiting), group=-1)

    # user commands
    app.add_handler(CommandHandler("start", usr.cmd_start))
    app.add_handler(CommandHandler("stop", usr.cmd_stop))
    app.add_handler(CommandHandler("help", usr.cmd_help))
    app.add_handler(CommandHandler("today", usr.cmd_today))
    app.add_handler(CommandHandler("lang", usr.cmd_lang))
    app.add_handler(CommandHandler("feedback", usr.cmd_feedback))
    app.add_handler(CommandHandler("suggest_prompt", usr.cmd_suggest))
    app.add_handler(CallbackQueryHandler(usr.on_lang_choice, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(usr.on_rate, pattern=r"^rate:"))
    app.add_handler(CallbackQueryHandler(usr.on_poll_vote, pattern=r"^poll"))

    # admin commands
    app.add_handler(CommandHandler("admin", adm.cmd_admin))
    app.add_handler(CommandHandler("status", adm.cmd_status))
    app.add_handler(CommandHandler("users", adm.cmd_users))
    app.add_handler(CommandHandler("addprompt", adm.cmd_addprompt))
    app.add_handler(CommandHandler("setru", adm.cmd_setru))
    app.add_handler(CommandHandler("prompts", adm.cmd_prompts))
    app.add_handler(CommandHandler("delprompt", adm.cmd_delprompt))
    app.add_handler(CommandHandler("exportprompts", adm.cmd_exportprompts))
    app.add_handler(CommandHandler("times", adm.cmd_times))
    app.add_handler(CommandHandler("settimes", adm.cmd_settimes))
    app.add_handler(CommandHandler("exclude", adm.cmd_exclude))
    app.add_handler(CommandHandler("include", adm.cmd_include))
    app.add_handler(CommandHandler("ban", adm.cmd_ban))
    app.add_handler(CommandHandler("forceprompt", adm.cmd_forceprompt))
    app.add_handler(CommandHandler("forcecollage", adm.cmd_forcecollage))
    app.add_handler(CommandHandler("delcollage", adm.cmd_delcollage))
    app.add_handler(CommandHandler("preview", adm.cmd_preview))
    app.add_handler(CommandHandler("skipday", adm.cmd_skipday))
    app.add_handler(CommandHandler("broadcast", adm.cmd_broadcast))
    app.add_handler(CommandHandler("kick", adm.cmd_kick))
    app.add_handler(CommandHandler("unkick", adm.cmd_unkick))
    app.add_handler(CommandHandler("stats", adm.cmd_stats))
    app.add_handler(CommandHandler("suggestions", adm.cmd_suggestions))
    app.add_handler(CommandHandler("feedback_all", adm.cmd_feedback_all))
    app.add_handler(CommandHandler("poll", adm.cmd_poll))
    app.add_handler(CommandHandler("polls", adm.cmd_polls))
    app.add_handler(CommandHandler("pollresults", adm.cmd_pollresults))
    app.add_handler(CommandHandler("polledit", adm.cmd_polledit))
    app.add_handler(CommandHandler("pollclose", adm.cmd_pollclose))
    app.add_handler(CommandHandler("approve", adm.cmd_approve))
    app.add_handler(CommandHandler("dismiss", adm.cmd_dismiss))
    app.add_handler(CommandHandler("errors", adm.cmd_errors))
    app.add_handler(CommandHandler("version", adm.cmd_version))

    # content
    app.add_handler(MessageHandler(filters.PHOTO, usr.on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(~filters.COMMAND, usr.on_other))

    app.add_error_handler(on_error)
    app.job_queue.run_repeating(jobs.tick, interval=60, first=5)
    return app


def main() -> None:
    config.validate()
    setup_logging()
    db.init()
    log.info("photobot starting (tz=%s, data=%s)", config.TZ, config.DATA_DIR)
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
