import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from flask import Flask, request
from openai import OpenAI, AssistantEventHandler
from dotenv import load_dotenv
import logging
import telegram
import asyncio

# Загрузка переменных окружения из файла .env
load_dotenv()

# Инициализация OpenAI клиента с использованием API ключа из окружения
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
model = "gpt-4o"

# Путь к файлу porogi_arki.xlsx
data_file_path = os.path.join(os.path.dirname(__file__), "porogi_arki.xlsx")

# Настройки для отправки уведомлений в Telegram
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
telegram_bot = telegram.Bot(token=telegram_bot_token)

# Создание помощника (Assistant) с добавленным файлом
assistant = client.beta.assistants.create(
    name="Кузовной ремонт",
    instructions="""
    Ты консультант по кузовному ремонту авто. Твоя цель:
    1. Помочь клиенту с консультацией по кузовным работам.
    2. Предложить услуги автосервиса, включая замену порогов и арок, покраску элементов авто.
    3. Всегда спрашивай у клиента фото повреждений.
    4. Запрашивай контактные данные для записи на осмотр.
    5. Если клиент хочет купить отдельно ремонтные элементы, можешь предложить купить ремонтный порог за 1800 рублей за один, ремонтную арку за 2500 за одну.
    6. Покраска одного элемента авто от 10000 рублей.
    7. Замена порога под ключ от 20000 рублей (входит ремонтный порог, снятие дверей и элементов кузова, покраска в цвет).
    8. Замена арки под ключ от 25000 рублей (входит ремонтная арка, снятие элементов кузова, покраска в цвет крыла).
    """,
    tools=[
        {"type": "code_interpreter"},
        {"type": "file", "name": "porogi_arki.xlsx", "path": data_file_path}
    ],
    model=model,
)

app = Flask(__name__)

# Настройка логирования для записи в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

# Словарь для хранения thread_id для каждого пользователя
user_threads = {}

# Класс обработчика событий для работы с потоковой передачей ответов от Assistant
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

# Асинхронная функция для отправки сообщения в Telegram
async def send_telegram_notification(user_id):
    await telegram_bot.send_message(chat_id=telegram_chat_id, text=f"Пользователь отправил файл. User ID: {user_id}")

# Функция для обработки получения файла и завершения диалога
def handle_file_submission(user_id):
    # Завершение потока пользователя, если он существует
    if user_id in user_threads:
        try:
            client.beta.threads.delete(thread_id=user_threads[user_id])  # Завершаем поток
            del user_threads[user_id]  # Удаляем информацию о потоке из словаря
            logging.info(f"Поток для пользователя {user_id} завершен из-за отправки файла.")
        except Exception as e:
            logging.error(f"Ошибка при завершении потока для пользователя {user_id}: {e}")

    # Отправка уведомления в Telegram
    asyncio.run(send_telegram_notification(user_id))

    # Отправка сообщения в VK
    try:
        vk_session = vk_api.VkApi(token=os.getenv('VK_API_TOKEN'))
        vk = vk_session.get_api()
        vk.messages.send(user_id=user_id, message="Мне нужно до 30 минут чтобы ответить вам.", random_id=0)
    except vk_api.VkApiError as e:
        logging.error(f"Ошибка VK API при отправке сообщения: {e}")

    return "Мне нужно до 30 минут чтобы ответить вам."

# Функция для создания нового потока и отправки сообщения пользователю
def handle_message_new(data):
    message = data['object']['message']['text']
    user_id = data['object']['message']['from_id']
    attachments = data['object']['message'].get('attachments', [])

    # Проверка наличия файла в сообщении (фото или другой файл)
    if attachments and any(attachment['type'] in ['photo', 'doc'] for attachment in attachments):
        return handle_file_submission(user_id)

    # Проверка, существует ли поток для данного пользователя
    if user_id not in user_threads:
        # Создание нового потока для каждого пользователя
        try:
            thread = client.beta.threads.create()
            user_threads[user_id] = thread.id
            logging.info(f"Создан новый поток для пользователя {user_id}")
        except Exception as e:
            logging.error(f"Ошибка при создании нового потока: {e}")
            return "Ошибка при создании нового потока.", 500
    else:
        logging.info(f"Используется существующий поток для пользователя {user_id}")

    # Создание нового сообщения в потоке
    try:
        client.beta.threads.messages.create(
            thread_id=user_threads[user_id],
            role="user",
            content=message
        )
    except Exception as e:
        logging.error(f"Ошибка при создании сообщения в OpenAI: {e}")
        return "Ошибка при создании сообщения в OpenAI.", 500

    # Создание экземпляра EventHandler для захвата ответа
    event_handler = EventHandler()

    # Использование потоковой передачи для выполнения команды
    try:
        with client.beta.threads.runs.stream(
            thread_id=user_threads[user_id],
            assistant_id=assistant.id,
            instructions="""
    Ты консультант по кузовному ремонту авто. Твоя цель:
    1. Помочь клиенту с консультацией по кузовным работам.
    2. Предложить услуги автосервиса, включая замену порогов и арок, покраску элементов авто.
    3. Всегда спрашивай у клиента фото повреждений.
    4. Запрашивай контактные данные для записи на осмотр.
    5. Если клиент хочет купить отдельно ремонтные элементы, можешь предложить купить ремонтный порог за 1800 рублей за один, ремонтную арку за 2500 за одну.
    6. Покраска одного элемента авто от 10000 рублей.
    7. Замена порога под ключ от 20000 рублей (входит ремонтный порог, снятие дверей и элементов кузова, покраска в цвет).
    8. Замена арки под ключ от 25000 рублей (входит ремонтная арка, снятие элементов кузова, покраска в цвет крыла).
    """,
            event_handler=event_handler,
        ) as stream:
            stream.until_done()
    except Exception as e:
        logging.error(f"Ошибка при выполнении команды с помощником: {e}")
        return "Ошибка при выполнении команды с помощником.", 500

    # Логирование истории сообщений
    get_thread_messages(client, user_threads[user_id])

    response_text = event_handler.response_text.strip()

    if response_text:
        try:
            vk_session = vk_api.VkApi(token=os.getenv('VK_API_TOKEN'))
            vk = vk_session.get_api()
            vk.messages.send(user_id=user_id, message=response_text, random_id=0)
        except vk_api.VkApiError as e:
            logging.error(f"Ошибка VK API: {e}")
            return f"Ошибка VK API: {e}", 500
    else:
        logging.error("Ответ от OpenAI не был получен.")
        return "Ответ от OpenAI не был получен.", 500

    return 'ok'

# Функция получения сообщений из потока OpenAI
def get_thread_messages(client, thread_id):
    try:
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        for message in messages.data:
            logging.info(f"Message: {message.content[0].text.value}")
    except Exception as e:
        logging.error(f"An error occurred while retrieving messages: {e}")

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return '5efebf00'
    elif request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            if 'type' in data and data['type'] == 'message_new':
                return handle_message_new(data)
        return 'Unsupported Media Type: Content is not application/json', 415

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)

