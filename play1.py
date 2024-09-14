import os
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from flask import Flask
from openai import OpenAI, AssistantEventHandler
from dotenv import load_dotenv
import logging
import telegram
import asyncio

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
assistant_id = os.getenv('ASSISTANT_KUZOVNOI_REMONT')

data_file_path = os.path.join(os.path.dirname(__file__), "porogi_arki.xlsx")

telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
telegram_bot = telegram.Bot(token=telegram_bot_token)

vk_session = vk_api.VkApi(token=os.getenv('VK_API_TOKEN'))
vk = vk_session.get_api()

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

user_threads = {}

class EventHandler(AssistantEventHandler):
    def __init__(self):
        super().__init__()
        self.response_text = ""
        self.photo_received = False

    def on_text_created(self, text) -> None:
        pass

    def on_text_delta(self, delta, snapshot):
        self.response_text += delta.value

    def on_tool_call_created(self, tool_call):
        print(f"\nassistant > {tool_call.type}\n", flush=True)

    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            if delta.code_interpreter.input:
                print(delta.code_interpreter.input, end="", flush=True)
            if delta.code_interpreter.outputs:
                print(f"\n\noutput >", flush=True)
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        print(f"\n{output.logs}", flush=True)

async def send_telegram_notification(user_id):
    await telegram_bot.send_message(chat_id=telegram_chat_id, text=f"Пользователь отправил файл или фото. User ID: {user_id}")

def write_dialog_to_file(user_question, assistant_response):
    with open("istoria_dialogov.txt", "a", encoding="utf-8") as file:
        file.write(f"Вопрос: {user_question}\nОтвет: {assistant_response}\n\n")

def handle_file_submission(user_id):
    if user_id in user_threads:
        try:
            client.beta.threads.delete(thread_id=user_threads[user_id])
            del user_threads[user_id]
            logging.info(f"Поток для пользователя {user_id} завершен из-за отправки файла.")
        except Exception as e:
            logging.error(f"Ошибка при завершении потока для пользователя {user_id}: {e}")

    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(send_telegram_notification(user_id))

    try:
        vk.messages.send(user_id=user_id, message="Мне нужно до 30 минут чтобы ответить вам.", random_id=0)
    except vk_api.VkApiError as e:
        logging.error(f"Ошибка VK API при отправке сообщения: {e}")

    return "Мне нужно до 30 минут чтобы ответить вам."

def handle_message_new(message, user_id, attachments):
    logging.info(f"Пришло сообщение от {user_id}: {message}")
    logging.info(f"Вложения: {attachments}")

    if attachments:
        return handle_file_submission(user_id)

    if not message:
        logging.error("Получено пустое сообщение. Пропускаем отправку в OpenAI.")
        return "Сообщение без текста пропущено."

    if user_id not in user_threads:
        try:
            thread = client.beta.threads.create()
            user_threads[user_id] = thread.id
            logging.info(f"Создан новый поток для пользователя {user_id}")
        except Exception as e:
            logging.error(f"Ошибка при создании нового потока: {e}")
            return "Ошибка при создании нового потока.", 500
    else:
        logging.info(f"Используется существующий поток для пользователя {user_id}")

    try:
        client.beta.threads.messages.create(
            thread_id=user_threads[user_id],
            role="user",
            content=message
        )
    except Exception as e:
        logging.error(f"Ошибка при создании сообщения в OpenAI: {e}")
        return "Ошибка при создании сообщения в OpenAI.", 500

    event_handler = EventHandler()

    try:
        with client.beta.threads.runs.stream(
            thread_id=user_threads[user_id],
            assistant_id=assistant_id,
            instructions="""Ты консультант по кузовному ремонту авто. Твоя цель:
    1. Помочь клиенту с консультацией по кузовным работам.
    2. Предложить услуги автосервиса, включая замену порогов и арок, покраску элементов авто.
    3. Всегда спрашивай у клиента фото повреждений.
    4. Запрашивай контактные данные для записи на осмотр.
    5. Если клиент хочет купить отдельно ремонтные элементы, можешь предложить купить ремонтный порог за 1800 рублей за один, ремонтную арку за 2500 за одну.
    6. Покраска одного элемента авто от 10000 рублей.
    7. Замена порога под ключ от 20000 рублей (входит ремонтный порог, снятие дверей и элементов кузова, покраска в цвет).
    8. Замена арки под ключ от 25000 рублей (входит ремонтная арка, снятие элементов кузова, покраска в цвет крыла).""",
            event_handler=event_handler,
        ) as stream:
            stream.until_done()
    except Exception as e:
        logging.error(f"Ошибка при выполнении команды с помощником: {e}")
        return "Ошибка при выполнении команды с помощником.", 500

    get_thread_messages(client, user_threads[user_id])

    response_text = event_handler.response_text.strip()

    if response_text:
        try:
            vk.messages.send(user_id=user_id, message=response_text, random_id=0)
            write_dialog_to_file(message, response_text)
        except vk_api.VkApiError as e:
            logging.error(f"Ошибка VK API: {e}")
            return f"Ошибка VK API: {e}", 500
    else:
        logging.error("Ответ от OpenAI не был получен.")
        return "Ответ от OpenAI не был получен.", 500

    return 'ok'

def get_thread_messages(client, thread_id):
    try:
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        for message in messages.data:
            logging.info(f"Message: {message.content[0].text.value}")
    except Exception as e:
        logging.error(f"An error occurred while retrieving messages: {e}")

def start_vk_longpoll():
    longpoll = VkLongPoll(vk_session)

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            user_id = event.user_id
            message = event.text
            attachments = event.attachments
            handle_message_new(message, user_id, attachments)

if __name__ == '__main__':
    start_vk_longpoll()
