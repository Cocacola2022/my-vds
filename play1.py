import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from flask import Flask, request
from openai import OpenAI
from dotenv import load_dotenv
import time
import logging

# Загрузка переменных окружения из файла .env
load_dotenv()

# Инициализация OpenAI клиента с использованием API ключа из окружения
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
model = "gpt-4o"
assistant_id = "asst_ea3YSuPL4zyr6f2f66200khe"
thread_id = "thread_0iXAjModp4JJN4a1a59qrkjJ"
app = Flask(__name__)

# Настройка логирования для записи в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),  # Запись логов в файл
        logging.StreamHandler()          # Одновременный вывод логов в консоль
    ]
)

def wait_for_run_completion(client, thread_id, run_id, sleep_interval=5, timeout=60):
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            logging.error("Timeout waiting for run to complete.")
            return None
        try:
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
            if run.completed_at:
                elapsed_time = run.completed_at - run.created_at
                formatted_elapsed_time = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))
                logging.info(f"Run completed in {formatted_elapsed_time}")
                messages = client.beta.threads.messages.list(thread_id=thread_id)
                last_message = messages.data[0]
                return last_message.content[0].text.value
        except Exception as e:
            logging.error(f"An error occurred while retrieving the run: {e}")
            break
        time.sleep(sleep_interval)

def get_thread_messages(client, thread_id):
    try:
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        for message in messages.data:
            logging.info(f"Message: {message.content[0].text.value}")
    except Exception as e:
        logging.error(f"An error occurred while retrieving messages: {e}")

def handle_message_new(data):
    message = data['object']['message']['text']
    user_id = data['object']['message']['from_id']

    # Генерация ответа с помощью OpenAI
    run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
    run_id = run.id
    response_text = wait_for_run_completion(client, thread_id, run_id)

    # Логирование истории сообщений
    get_thread_messages(client, thread_id)

    if response_text:
        try:
            vk_session = vk_api.VkApi(token=os.getenv('VK_API_TOKEN'))
            vk = vk_session.get_api()
            vk.messages.send(user_id=user_id, message=response_text, random_id=0)
        except vk_api.VkApiError as e:
            logging.error(f"Ошибка VK API: {e}")
            return f"Ошибка VK API: {e}", 500
    return 'ok'

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
