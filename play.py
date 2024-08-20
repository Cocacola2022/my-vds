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

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Установите ваш API-ключ OpenAI

# Функция для получения информации о продукте из базы данных
def get_product_info(product_name):
    try:
        conn = sqlite3.connect('products.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name, price, description FROM products WHERE name LIKE ?", (f"%{product_name}%",))
        product = cursor.fetchone()
        conn.close()
        if product:
            return f"Название: {product[0]}\nЦена: {product[1]} руб.\nОписание: {product[2]}"
        else:
            return "Извините, такой товар не найден."
    except sqlite3.Error as e:
        logging.error(f"Ошибка базы данных: {e}")
        return f"Ошибка базы данных: {e}"

# Функция для генерации ответа с помощью OpenAI GPT-4
def generate_openai_response(message):
    try:
        response = client.chat.completions.create(model="gpt-4o",
                                messages=[
            {"role": "system", "content": "Обращаться всегда на вы.Вы консультант по кузовному ремонту порогов и арок автомобилей,замена/покраска делатей авто в цвет.Вам нужно узнать что ремонтировать по кузову, добиться фото битых делатей. Если человеку нужны ремонтные пороги либо арки, то предложить купить у нас. Порог 1600 за один, арка 2500"},
            {"role": "user", "content": message}],
        temperature=1,
        max_tokens=256,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0)
        return response.choices[0].message.content
    except openai.OpenAIError as e:
        logging.error(f"Ошибка OpenAI: {e}")
        return f"Ошибка OpenAI: {e}"

# Обработка входящих запросов
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # Подтверждение адреса сервера для получения уведомлений от VK
        return '5efebf00'
    elif request.method == 'POST':
        # Проверка, что данные в формате JSON
        if request.is_json:
            data = request.get_json()
            if 'type' in data:
                if data['type'] == 'confirmation':
                    return '5efebf00'
                if data['type'] == 'message_new':
                    message = data['object']['message']['text']
                    user_id = data['object']['message']['from_id']

                    # Используем OpenAI для генерации ответа
                    response_text = generate_openai_response(message)

                    try:
                        vk_session = vk_api.VkApi(token=os.getenv('VK_API_TOKEN'))
                        vk = vk_session.get_api()
                        vk.messages.send(
                            user_id=user_id,
                            message=response_text,
                            random_id=0
                        )
                    except vk_api.VkApiError as e:
                        logging.error(f"Ошибка VK API: {e}")
                        return f"Ошибка VK API: {e}", 500

                    return 'ok'
            return 'Unsupported Media Type: Content is not application/json', 415
        else:
            return 'Unsupported Media Type: Content is not application/json', 415

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
