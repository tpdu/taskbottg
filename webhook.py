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
    filters,
)
from telegram import ReplyKeyboardMarkup

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

    user_id: int
    task: str


class CustomContext(CallbackContext[ExtBot, dict, dict, dict]):

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
    reply_keyboard = [['/start', '/assigntask'],
                      ['/completetask']]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=False)

    task_url = html.escape(f"{URL}/submittask")
    text = (
        f"Чтобы проверить ,что бот работает стабильно, откройте в браузере ссылку: <code>{URL}/healthcheck</code>.\n\n"
        f"Чтобы назначить задачу пользователю используйте команду /assigntask \n"
        f"Затем введите ID пользователя и нажмите Enter. Введите задачу."
    )
    await update.message.reply_html(text=text, reply_markup=markup)


async def assign_task_command(update: Update, context: CustomContext) -> None:
    message = update.message
    await message.reply_text("Введите ID пользователя, которому вы хотите назначить задачу")

    context.user_data['waiting_for_user_id'] = True
    context.user_data['completing_task'] = False


async def assign_task_input(update: Update, context: CustomContext) -> None:
    message = update.message
    user_data = context.user_data

    if 'waiting_for_user_id' in user_data:
        user_id_or_username = message.text.strip()

        if user_id_or_username.startswith('@'):
            try:
                user = await context.bot.get_chat(user_id_or_username)
                user_id = user.id
            except Exception as e:
                logger.error(f"Error resolving username {user_id_or_username}: {e}")
                await message.reply_text("Ошибка обработки юзернейма. Пожалуйста, проверть правильность ID или юзернейма.")
                return
        else:
            try:
                user_id = int(user_id_or_username)
            except ValueError:
                await message.reply_text("Неверный формат ID. Проверьте, пожалуйста, правильность ввода ID.")
                return

        user_data['assigning_task_to'] = user_id
        await message.reply_text("Пожалуйста, введите задачу, которую вы хотите назначить этому пользователю.")

        del user_data['waiting_for_user_id']

    else:
        task = message.text.strip()
        user_id = user_data.get('assigning_task_to')
        if user_id is None:
            await message.reply_text("Вы не указали пользователя, которому необходимо назначить задачу")
            return
        await handle_assigned_task(update, context, task, user_id)



async def handle_assigned_task(update: Update, context: CustomContext, task: str, user_id: int) -> None:
    tasks = context.user_data.setdefault("tasks", [])
    tasks.append(task)

    combined_tasks = "\n• " + "\n• ".join(tasks)
    text = f"Пользователь с ID {user_id} назначил Вам новую задачу. На Вас назначены следующие задачи: \n{combined_tasks}"


    # await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode=ParseMode.HTML)


    try:
        await context.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.error(f"Ошибка назначения задачи пользователю с ID {user_id}: {e}")
    return


async def complete_task(update: Update, context: CustomContext) -> None:

    tasks = context.user_data.get("tasks", [])

    if not tasks:
        await update.message.reply_text("На Вас не назначена ни одна задача")
        return

    task_to_complete = update.message.text.split(maxsplit=1)[1].strip()

    if task_to_complete not in tasks:
        await update.message.reply_text("Этой задаче нет в списке Ваших задач")
        return

    tasks.remove(task_to_complete)
    context.user_data["tasks"] = tasks

    await update.message.reply_text(f"Задача '{task_to_complete}' отмечена как выполненная.")
    combined_tasks = "\n• " + "\n• ".join(tasks)
    if tasks:
        text = f"На Вас все еще назачены следующие задачи: \n{combined_tasks}"
        print(tasks)
    else:
        text = "Вы выполнили все назначенные на Вас задачи!"
    await update.message.reply_text(text)


    await context.bot.process_updates(update_queue=context.update_queue)




async def webhook_update(update: WebhookUpdate, context: CustomContext) -> None:
    tasks = context.user_data.setdefault("tasks", [])
    tasks.append(update.task)
    combined_tasks = "\n• " + "\n• ".join(tasks)
    text = f"The user with ID {update.user_id} has sent you a new task. So far they have sent the following tasks: \n{combined_tasks}"

    # await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode=ParseMode.HTML)

    try:
        user_chat_id = update.user_id
        await context.bot.send_message(chat_id=user_chat_id, text=text)
    except Exception as e:
        logger.error(f"Error sending message to user with ID {update.user_id}: {e}")



async def main() -> None:
    context_types = ContextTypes(context=CustomContext)
    application = (
        Application.builder().token(TOKEN).updater(None).context_types(context_types).build()
    )


    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("assigntask", assign_task_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, assign_task_input))
    application.add_handler(MessageHandler(~filters.TEXT & filters.COMMAND, handle_assigned_task))
    application.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, complete_task))
    application.add_handler(TypeHandler(type=WebhookUpdate, callback=webhook_update))

    await application.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)

    flask_app = Flask(__name__)

    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=WsgiToAsgi(flask_app),
            port=PORT,
            use_colors=False,
            host="127.0.0.1",
        )
    )

    @flask_app.post("/telegram")
    async def telegram() -> Response:
        await application.update_queue.put(Update.de_json(data=request.json, bot=application.bot))
        return Response(status=HTTPStatus.OK)


    async with application:
        await application.start()
        await webserver.serve()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())



