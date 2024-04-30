#!/usr/bin/env python

import asyncio
import html
import logging
from dataclasses import dataclass
from http import HTTPStatus

import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, abort, make_response, request

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    ExtBot,
    MessageHandler,
    TypeHandler,
    filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

URL = "https://9d51-146-241-37-203.ngrok-free.app"
ADMIN_CHAT_ID = 1095963853
PORT = 5000
TOKEN = "7186535198:AAFrZchf9bYw_jVs3GqSbHmJ54bSNy5Xcq8"

@dataclass
class WebhookUpdate:
    """Simple dataclass to wrap a custom update type"""
    user_id: int
    task: str

class CustomContext(CallbackContext[ExtBot, dict, dict, dict]):
    """
    Custom CallbackContext class that makes `user_data` available for updates of type
    `WebhookUpdate`.
    """
    @classmethod
    def from_update(
        cls,
        update: object,
        application: "Application",
    ) -> "CustomContext":
        if isinstance(update, WebhookUpdate):
            return cls(application=application, user_id=update.user_id)
        return super().from_update(update, application)

async def start(update: Update, context: CustomContext) -> None:
    """Display a message with instructions on how to use this bot."""
    task_url = html.escape(f"{URL}/submittask")
    text = (
        f"To check if the bot is still running, call <code>{URL}/healthcheck</code>.\n\n"
        f"To post a custom update, send a POST request to <code>{task_url}</code> "
        "with the user ID and task separated by a comma."
    )
    await update.message.reply_html(text=text)

async def webhook_update(update: WebhookUpdate, context: CustomContext) -> None:
    """Handle custom updates."""
    chat_member = await context.bot.get_chat_member(chat_id=update.user_id, user_id=update.user_id)
    tasks = context.user_data.setdefault("tasks", [])
    tasks.append(update.task)
    combined_tasks = "</code>\n• <code>".join(tasks)
    text = (
        f"The user {chat_member.user.mention_html()} has sent a new task. "
        f"So far they have sent the following tasks: \n\n• <code>{combined_tasks}</code>"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode=ParseMode.HTML)

async def handle_custom_update_command(update: Update, context: CustomContext) -> None:
    """Handle the /customupdate command to prompt users for their user ID and task."""
    message = update.message
    await message.reply_text("Please send your user ID and task separated by a comma.")

async def handle_custom_update_input(update: Update, context: CustomContext) -> None:
    """Handle user input for custom update."""
    message = update.message
    input_text = message.text.strip()
    try:
        user_id, task = input_text.split(",")
        user_id = int(user_id.strip())
        task = task.strip()
    except ValueError:
        await message.reply_text("Invalid input format. Please provide user ID and task separated by a comma.")
        return

    await context.update_queue.put(WebhookUpdate(user_id=user_id, task=task))
    await message.reply_text("Custom update has been added successfully.")

async def main() -> None:
    """Set up PTB application and a web application for handling the incoming requests."""
    context_types = ContextTypes(context=CustomContext)
    application = (
        Application.builder().token(TOKEN).updater(None).context_types(context_types).build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(TypeHandler(type=WebhookUpdate, callback=webhook_update))
    application.add_handler(CommandHandler("customupdate", handle_custom_update_command))
    application.add_handler(MessageHandler(~filters.Command(), handle_custom_update_input))

    await application.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)

    flask_app = Flask(__name__)

    @flask_app.post("/telegram")
    async def telegram() -> Response:
        """Handle incoming Telegram updates by putting them into the `update_queue`"""
        await application.update_queue.put(Update.de_json(data=request.json, bot=application.bot))
        return Response(status=HTTPStatus.OK)

    @flask_app.route("/submittask", methods=["POST"])
    async def custom_updates() -> Response:
        """
        Handle incoming webhook updates by also putting them into the `update_queue` if
        the required parameters were passed correctly.
        """
        try:
            user_id, task = request.data.decode("utf-8").split(",")
            user_id = int(user_id.strip())
            task = task.strip()
        except (ValueError, AttributeError) as e:
            abort(HTTPStatus.BAD_REQUEST, f"Invalid request format: {e}")

        await application.update_queue.put(WebhookUpdate(user_id=user_id, task=task))
        return Response(status=HTTPStatus.OK)

    @flask_app.get("/healthcheck")
    async def health() -> Response:
        """For the health endpoint, reply with a simple plain text message."""
        response = make_response("The bot is still running fine :)", HTTPStatus.OK)
        response.mimetype = "text/plain"
        return response

    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=WsgiToAsgi(flask_app),
            port=PORT,
            use_colors=False,
            host="127.0.0.1",
        )
    )

    async with application:
        await application.start()
        await webserver.serve()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())
