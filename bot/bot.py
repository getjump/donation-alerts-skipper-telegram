import os
from telegram import (
    Update,
    User,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    CallbackQuery,
)
from telegram.ext import (
    Dispatcher,
    Updater,
    CommandHandler,
    CallbackContext,
    DictPersistence,
    CallbackQueryHandler,
)
from telegram.utils.helpers import escape_markdown, mention_markdown
import random
import string
import json
import requests
import socketio
import re
import time
from tempfile import NamedTemporaryFile
import subprocess

import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DA_SOCKET_URL = os.getenv("DA_SOCKET_URL")
DA_SOCKET_TOKEN = os.getenv("DA_SOCKET_TOKEN")

logging.info(TELEGRAM_CHAT_ID)

DA_SKIP_DONATION_URL = (
    "https://www.donationalerts.com/api/skipalert?alert={}&alert_type={}&token={}&_={}"
)

EVIL_CHARACTERS_REGEXP = r"[^\u0400-\u052Fa-zA-Z0-9\.\:\,\-\@\/\\\;\'\^\)\(\s\?\!\=\&\*\%\#\№\"\$\_\+\-\`\~\|]"

ALERT_TYPE_DONATION = "1"

updater = Updater(
    token=TELEGRAM_BOT_TOKEN, use_context=True, persistence=DictPersistence()
)
dispatcher: Dispatcher = updater.dispatcher

ws_client: socketio.Client

dispatcher.bot_data["validationMessageToTokenDonation"] = {}

bot_data: User = updater.bot.getMe()

alertToMessage = {}
alertToBeSkipped = {}
alertToDonation = {}

logging.info(bot_data)


def reboot(update: Update, context: CallbackContext):
    global ws_client

    if update.effective_chat is None:
        return

    if ws_client is None:
        return
    else:
        ws_client.disconnect()

    ws_client = wsConnect(DA_SOCKET_URL, DA_SOCKET_TOKEN)

    context.bot.send_message(
        chat_id=str(update.effective_chat.id), text="Подключение к DA перезапущено"
    )


def da_skip_donation(donation):
    millis = int(round(time.time() * 1000))
    url = DA_SKIP_DONATION_URL.format(donation["id"], 1, DA_SOCKET_TOKEN, millis)
    r = requests.get(url)

    response = r.text.strip("()")

    skip_data = json.loads(response)
    logging.info(skip_data)

    ws_client.emit(
        "alert-show",
        {
            "token": DA_SOCKET_TOKEN,
            "message_data": {
                "action": "skip",
                "alert_id": donation["id"],
                "alert_type": "1",
            },
        },
    )

    return skip_data


def make_user_shortcut(user):
    shortcut = user.username

    if not shortcut:
        shortcut = ""
        if user.first_name:
            shortcut = user.first_name
        if user.last_name:
            shortcut = shortcut + " " + user.last_name

    return shortcut


def callback_query_donation_handler(update: Update, context: CallbackContext):
    if "validationMessageToTokenDonation" not in dispatcher.bot_data:
        return

    callback_query: CallbackQuery = update.callback_query

    if not callback_query:
        return

    if (
        callback_query.data
        not in dispatcher.bot_data["validationMessageToTokenDonation"]
    ):
        return

    donation = dispatcher.bot_data["validationMessageToTokenDonation"][
        callback_query.data
    ]

    if update.effective_chat is None:
        return

    dispatcher.bot_data["validationMessageToTokenDonation"].pop(
        callback_query.data, None
    )
    alertToDonation.pop(str(donation["id"]), None)

    alertToBeSkipped[str(donation["id"])] = True

    skip_data = da_skip_donation(donation)

    if skip_data["status"] != "success":
        context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=skip_data["message"])
        return

    message: Message = callback_query.message

    if not message:
        return

    user: User = callback_query.from_user

    shortcut = make_user_shortcut(user)

    suffix = "скипнуто"

    text = (
        "~"
        + escape_markdown(message.text, 2)
        + "~\n"
        + "Сообщение {} {}".format(suffix, mention_markdown(user.id, shortcut, 2))
    )

    logging.info(text)

    message.edit_text(
        text=text, parse_mode=ParseMode.MARKDOWN_V2, entities=message.entities
    )


def on_alert_show(data):
    data = json.loads(data)
    logging.info(data)

    if str(data["alert_id"]) in alertToMessage:
        message: Message = alertToMessage[str(data["alert_id"])]
        logging.info(message)
        if data["action"] == "end":
            text = message.text + "\n" + "Сообщение показано"
            logging.info(text)
            message.edit_text(text=text, entities=message.entities)
            if str(data["alert_id"]) in alertToDonation:
                dispatcher.bot_data["validationMessageToTokenDonation"].pop(
                    alertToDonation[str(data["alert_id"])], None
                )
            alertToMessage.pop(str(data["alert_id"]), None)
            alertToDonation.pop(str(data["alert_id"]), None)
        if data["action"] == "skip":
            text = (
                "~"
                + escape_markdown(message.text, 2)
                + "~"
                + "\n"
                + "Сообщение скипнуто стримером"
            )
            if str(data["alert_id"]) in alertToBeSkipped:
                alertToBeSkipped.pop(str(data["alert_id"]), None)
            else:
                message.edit_text(
                    text=text,
                    entities=message.entities,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            if str(data["alert_id"]) in alertToDonation:
                dispatcher.bot_data["validationMessageToTokenDonation"].pop(
                    alertToDonation[str(data["alert_id"])], None
                )
            alertToMessage.pop(str(data["alert_id"]), None)
            alertToDonation.pop(str(data["alert_id"]), None)
    return


def wsConnect(wsUri, token):
    global ws_client

    ws_client = socketio.Client(
        reconnection=True, reconnection_delay=1, reconnection_delay_max=5
    )

    @ws_client.on("donation")  # type: ignore
    def donation(data):
        data = json.loads(data)
        if data["alert_type"] != "1":
            return
        logging.info(data)
        subscription_callback(data)

    @ws_client.on("update-alert_widget")  # type: ignore
    def updateAlertWidget(data):
        logging.info(data)

    @ws_client.on("update-user_general_widget_settings")  # type: ignore
    def updateUserGeneralWidgetSettings(data):
        logging.info(data)

    @ws_client.on("alert-show")  # type: ignore
    def alertShow(data):
        on_alert_show(data)

    @ws_client.on("connect")  # type: ignore
    def client_connect():
        ws_client.emit("add-user", {"token": token, "type": "alert_widget"})

    ws_client.connect(wsUri)

    return ws_client


def process_audio(data, chat_id):
    response = requests.get(data["message"], stream=True)

    suffix = ".wav"

    with NamedTemporaryFile(suffix=suffix) as tmp_voice:
        tmp_voice.write(response.content)

        tmp_voice_filename_ogg = tmp_voice.name[: -len(suffix)] + ".ogg"

        subprocess.call(["ffmpeg", "-i", tmp_voice.name, tmp_voice_filename_ogg])

        with open(tmp_voice_filename_ogg, "rb") as converted_ogg:
            dispatcher.bot.send_voice(chat_id, converted_ogg.read())


def subscription_callback(data):
    logging.info(data)

    chat_id = TELEGRAM_CHAT_ID

    text = """
{}    {} {} {}
Сообщение: {}
{}
    """

    if "validationMessageToTokenDonation" not in dispatcher.bot_data:
        dispatcher.bot_data["validationMessageToTokenDonation"] = {}

    cb_data = "DNT" + "".join(
        random.SystemRandom().choice(string.ascii_uppercase + string.digits)
        for _ in range(24)
    )

    dispatcher.bot_data["validationMessageToTokenDonation"][cb_data] = data

    valid_button = InlineKeyboardButton("Скипнуть", callback_data=cb_data)
    reply_markup = InlineKeyboardMarkup([[valid_button]])

    if data["message_type"] == "audio":
        message_str = ""
        process_audio(data, chat_id)
    elif data["message_type"] == "text":
        message_str = data["message"]
    else:
        return

    username = f"*{escape_markdown(data['username'], 2)}*"
    username_additional = ""

    if "additional_data" in data:
        additional_data = json.loads(data["additional_data"])

        if "payer_data" in additional_data:
            username_additional = (
                f"{escape_markdown(additional_data['payer_data']['url'], 2)}"
            )

        if "media_data" in additional_data:
            message_str += " " + escape_markdown(
                additional_data["media_data"]["url"], 2
            )

    billing_system = (
        (escape_markdown(data["billing_system"], 2) if "billing_system" in data else "")
        + " "
        + (
            escape_markdown(data["billing_system_type"], 2)
            if data["billing_system_type"] is not None
            else "None"
            if "billing_system_type" in data
            else ""
        )
    )

    message_str = re.sub(EVIL_CHARACTERS_REGEXP, "", message_str)
    message_str = escape_markdown(message_str, 2)

    formatted_str = text.format(
        username,
        data["amount_formatted"],
        data["currency"],
        billing_system,
        message_str,
        username_additional,
    )

    logging.info(formatted_str)

    logging.info(chat_id)

    msg = dispatcher.bot.send_message(
        chat_id,
        formatted_str,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    alertToMessage[str(data["id"])] = msg
    alertToDonation[str(data["id"])] = cb_data


dispatcher.add_handler(CommandHandler("reboot", reboot))
dispatcher.add_handler(
    CallbackQueryHandler(callback_query_donation_handler, pattern=r"DNT\S+")
)

ws_client = wsConnect(DA_SOCKET_URL, DA_SOCKET_TOKEN)

updater.start_polling()
updater.idle()
