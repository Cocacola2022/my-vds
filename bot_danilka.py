import os
from flask import Flask
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

# Используем существующего помощника
assistant_id = os.getenv('OPENAI_assistant_danilka')
# Настройки для отправки уведомлений в Telegram
telegram_bot_token = os.getenv('telegram_bot_token_danilka')
telegram_bot = telegram.Bot(token=telegram_bot_token)

app = Flask(__name__)

# Настройка логирования для записи в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app_tg_danilka.log"),
    ]
)

# Словарь для хранения thread_id для каждого пользователя
user_threads = {}

# Класс обработчика событий для работы с потоковой передачей ответов от Assistant
class EventHandler(AssistantEventHandler):
    def __init__(self):
        super().__init__()
        self.response_text = ""

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
async def send_telegram_message(chat_id, text):
    await telegram_bot.send_message(chat_id=chat_id, text=text)

# Асинхронная функция для обработки сообщений из Telegram
async def handle_telegram_message(update):
    chat_id = update.message.chat.id

    # Проверка, если сообщение содержит фото
    if update.message.photo:
        # Завершение потока пользователя, если он существует
        if chat_id in user_threads:
            try:
                client.beta.threads.delete(thread_id=user_threads[chat_id])  # Завершаем поток
                del user_threads[chat_id]  # Удаляем информацию о потоке из словаря
                logging.info(f"Поток для пользователя {chat_id} завершен из-за отправки фото.")
            except Exception as e:
                logging.error(f"Ошибка при завершении потока для пользователя {chat_id}: {e}")

        # Отправка сообщения в чат о том, что пользователь отправил фото
        await send_telegram_message(chat_id, "Пользователь отправил фото.")
        return  # Завершаем выполнение функции

    # Обработка текстовых сообщений
    message = update.message.text

    if not message:
        logging.error("Получено пустое сообщение из Telegram.")
        await send_telegram_message(chat_id, "Пустое сообщение.")
        return

    # Проверка, существует ли поток для данного пользователя
    if chat_id not in user_threads:
        # Создание нового потока для каждого пользователя
        try:
            thread = client.beta.threads.create()
            user_threads[chat_id] = thread.id
            logging.info(f"Создан новый поток для пользователя {chat_id}")
        except Exception as e:
            logging.error(f"Ошибка при создании нового потока: {e}")
            await send_telegram_message(chat_id, "Ошибка при создании нового потока.")
            return
    else:
        logging.info(f"Используется существующий поток для пользователя {chat_id}")

    # Создание нового сообщения в потоке
    try:
        client.beta.threads.messages.create(
            thread_id=user_threads[chat_id],
            role="user",
            content=message
        )
    except Exception as e:
        logging.error(f"Ошибка при создании сообщения в OpenAI: {e}")
        await send_telegram_message(chat_id, "Ошибка при создании сообщения в OpenAI.")
        return

    # Создание экземпляра EventHandler для захвата ответа
    event_handler = EventHandler()

    # Использование потоковой передачи для выполнения команды с существующим помощником
    try:
        with client.beta.threads.runs.stream(
            thread_id=user_threads[chat_id],
            assistant_id=assistant_id,
            instructions="ты самый крутой помощник и консультант Можешь отвечать на любые вопросы. Ты api, код python3, линукс команды",
            event_handler=event_handler,
        ) as stream:
            stream.until_done()
    except Exception as e:
        logging.error(f"Ошибка при выполнении команды с помощником: {e}")
        await send_telegram_message(chat_id, "Ошибка при выполнении команды с помощником.")
        return

    response_text = event_handler.response_text.strip()

    if response_text:
        await send_telegram_message(chat_id, response_text)
    else:
        logging.error("Ответ от OpenAI не был получен.")
        await send_telegram_message(chat_id, "Ответ от OpenAI не был получен.")

# Асинхронная функция для запуска long polling и получения сообщений
async def start_telegram_bot():
    update_id = None

    while True:
        try:
            # Получаем обновления от Telegram
            updates = await telegram_bot.get_updates(offset=update_id, timeout=10)
            for update in updates:
                if update.message:
                    await handle_telegram_message(update)
                    update_id = update.update_id + 1

        except Exception as e:
            logging.error(f"Ошибка при получении обновлений от Telegram: {e}")

# Запуск сервера Flask
@app.route('/')
def index():
    return "Сервер работает!"

if __name__ == '__main__':
    # Запускаем сервер Flask в фоновом режиме
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=8081)).start()

    # Запуск Telegram бота с использованием long polling
    asyncio.run(start_telegram_bot())
