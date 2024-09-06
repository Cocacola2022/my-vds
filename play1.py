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

# Настройки для отправки уведомлений в Telegram
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
telegram_bot = telegram.Bot(token=telegram_bot_token)

# Создание помощника (Assistant) с новым подходом
assistant = client.beta.assistants.create(
    name="Кузовной ремонт",
    instructions="""
    Ты консультант по кузовному ремонту авто. Твоя цель:
    1. Помочь клиенту с консультацией по кузовным работам.
    2. Предложить услуги автосервиса, включая замену порогов и арок, покраску элементов авто.
    3. Всегда спрашивай у клиента фото повреждений.
    4. Запрашивай контактные данные для записи на осмотр.
    5. Если клиент хочет купить отвельно ремонтные элементы можешь предложить купить ремонтный порог за 1800 рублей за один, ремонтную арку за 2500 за одну.
    6. Покраска одного элемента авто от 10000 рублей.
    7. Замена порога под ключ от 20000 рублей ( входит ремонтный порог, снятие дверей и элементов кузова, покраска в цвет ).
    8. Замена арки под ключ от 25000 рублей ( входит ремонтная арка, снятие элементов кузова, покраска в цвет крыла).
    """,
    tools=[{"type": "code_interpreter"}],
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
    await telegram_bot.send_message(chat_id=telegram_chat_id, text=f"Новый клиент отправил фото. User ID: {user_id}")

# Функция для обработки получения фото и завершения диалога
def handle_photo_submission(user_id, data):
    asyncio.run(send_telegram_notification(user_id))
    return "Мне нужно до 30 минут чтобы ответить вам."

# Функция для создания нового потока и отправки сообщения пользователю
def handle_message_new(data):
    message = data['object']['message']['text']
    user_id = data['object']['message']['from_id']
    attachments = data['object']['message'].get('attachments', [])

    if attachments and any(attachment['type'] == 'photo' for attachment in attachments):
        return handle_photo_submission(user_id, {"photo_info": str(attachments), "contact_info": ""})

    # Создание нового потока для каждого пользователя
    thread = client.beta.threads.create()

    # Создание нового сообщения в потоке
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=message
    )

    # Создание экземпляра EventHandler для захвата ответа
    event_handler = EventHandler()

    # Использование потоковой передачи для выполнения команды
    with client.beta.threads.runs.stream(
        thread_id=thread.id,
        assistant_id=assistant.id,
        instructions="Ты консультант по кузовному ремонту авто. Твоя цель — помочь клиенту и предложить услуги автосервиса, включая замену порогов и арок, покраску элементов авто. Всегда спрашивай у клиента фото повреждений и контактные данные для записи на осмотр.",
        event_handler=event_handler,
    ) as stream:
        stream.until_done()

    # Логирование истории сообщений
    get_thread_messages(client, thread.id)

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

