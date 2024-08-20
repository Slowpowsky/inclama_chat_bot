import sqlite3
import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.callback_data import CallbackData
from database import create_tables, add_user, get_user_by_telegram_id, add_order, get_free_orders, update_order_status, add_response, get_responses_by_order_id, update_response_status

# Инициализация бота
API_TOKEN = '7264705176:AAFma9XWk3Xcc2rXUKGYSQX_Pz3xI5pfd8w'

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# CallbackData для управления различными этапами
role_callback = CallbackData('role', 'type')
order_callback = CallbackData('order', 'action', 'order_id')
response_callback = CallbackData('response', 'action', 'response_id', 'order_id', 'executor_id')
completion_callback = CallbackData('completion', 'action', 'order_id', 'executor_id')

# Память в рамках сессии
user_data = {}
orders = []
order_responses = {}

# Определяем состояния
class OrderForm(StatesGroup):
    details = State()  # Состояние для ввода деталей заказа

class CompletionForm(StatesGroup):
    video = State()  # Состояние для получения видео от исполнителя
    feedback = State()  # Состояние для получения комментариев от заказчика

# Стартовая команда
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    create_tables()  # Создаем таблицы в базе данных, если они еще не существуют
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🛠 Исполнитель", callback_data=role_callback.new(type='executor')),
        InlineKeyboardButton("💼 Заказчик", callback_data=role_callback.new(type='customer'))
    )
    await message.answer("Привет! Пожалуйста, выберите свою роль:", reply_markup=keyboard)

# Обработчик выбора роли
@dp.callback_query_handler(role_callback.filter())
async def process_role(callback_query: CallbackQuery, callback_data: dict):
    role = callback_data['type']
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username

    user = get_user_by_telegram_id(user_id)
    if not user:
        user_data[user_id] = {'role': role, 'username': username}
        await callback_query.message.answer("Введите ваше ФИО:")
        await callback_query.answer(f"Вы выбрали роль {'Исполнителя' if role == 'executor' else 'Заказчика'}")
    else:
        if role == 'executor':
            await executor_menu(callback_query.message)
        else:
            await customer_menu(callback_query.message)

@dp.message_handler(lambda message: message.from_user.id in user_data and 'name' not in user_data[message.from_user.id])
async def process_name(message: types.Message):
    user_id = message.from_user.id
    name = message.text.strip()

    if not name or len(name.split()) < 2 or not all(part.isalpha() for part in name.split()):
        await message.answer("Пожалуйста, введите корректное ФИО (например, Иван Иванов).")
        return

    user_data[user_id]['name'] = name

    if user_data[user_id]['role'] == 'executor':
        await message.answer("Введите ваш опыт работы в годах:")
    else:
        add_user(user_id, user_data[user_id]['role'], user_data[user_id]['name'], None, None, user_data[user_id]['username'])
        await message.answer("Отлично! Вы зарегистрированы как Заказчик 💼")
        await customer_menu(message)


@dp.message_handler(lambda message: message.from_user.id in user_data and 'experience' not in user_data[message.from_user.id] and user_data[message.from_user.id]['role'] == 'executor')
async def process_experience(message: types.Message):
    user_id = message.from_user.id
    experience = message.text.strip()

    if not experience.isdigit() or int(experience) < 0:
        await message.answer("Пожалуйста, введите корректный опыт работы в годах (например, 5).")
        return

    user_data[user_id]['experience'] = experience
    await message.answer("Пожалуйста, отправьте пример ваших работ (ссылка или видео):")

# Главное меню для Заказчика
async def customer_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("➕ Создать новый заказ", callback_data=order_callback.new(action='create', order_id='0'))
    )
    await message.answer("Главное меню Заказчика:", reply_markup=keyboard)

# Главное меню для Исполнителя
async def executor_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🔍 Просмотреть заказы", callback_data=order_callback.new(action='view', order_id='0'))
    )
    await message.answer("Главное меню Исполнителя:", reply_markup=keyboard)

# Создание нового заказа
@dp.callback_query_handler(order_callback.filter(action='create'))
async def create_order(callback_query: CallbackQuery):
    await callback_query.message.answer(
        "Пожалуйста, заполните бриф: (укажите сроки, стоимость, локацию, особенности съемки и т.д.)")
    await OrderForm.details.set()
    await callback_query.answer()

# Обработка ввода деталей заказа
@dp.message_handler(state=OrderForm.details)
async def order_details(message: types.Message, state: FSMContext):
    details = message.text.strip()

    if len(details) < 10:
        await message.answer("Пожалуйста, введите более подробное описание заказа (минимум 10 символов).")
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("➕ Создать новый заказ", callback_data=order_callback.new(action='create', order_id='0'))
    )
    user = get_user_by_telegram_id(message.from_user.id)
    add_order(user[0], details)  # Используем ID пользователя из базы данных
    await message.answer("Ваш заказ создан! Исполнители смогут его увидеть.", reply_markup=keyboard)
    await state.finish()

# Просмотр заказов исполнителем
@dp.callback_query_handler(order_callback.filter(action='view'))
async def view_orders(callback_query: CallbackQuery, callback_data: dict):
    current_order_id = int(callback_data['order_id'])
    free_orders = get_free_orders()

    if current_order_id >= len(free_orders):
        await callback_query.answer("Больше заказов нет.")
        return

    order = free_orders[current_order_id]
    keyboard = InlineKeyboardMarkup(row_width=2)
    if current_order_id > 0:
        keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data=order_callback.new(action='view', order_id=str(current_order_id - 1))))
    if current_order_id < len(free_orders) - 1:
        keyboard.add(InlineKeyboardButton("➡️ Вперед", callback_data=order_callback.new(action='view', order_id=str(current_order_id + 1))))

    # Обратите внимание на передачу только 5 аргументов, как было указано в response_callback
    keyboard.add(InlineKeyboardButton("📩 Откликнуться", callback_data=response_callback.new(
        action='respond',
        response_id='0',
        order_id=str(order[0]),
        executor_id=str(callback_query.from_user.id)
    )))

    await callback_query.message.edit_text(
        f"Заказ {current_order_id + 1}:\n\n"
        f"📋 Описание: {order[2]}\n",
        reply_markup=keyboard
    )
    await callback_query.answer()

# Обработка отклика на заказ
@dp.callback_query_handler(response_callback.filter(action='respond'))
async def respond_to_order(callback_query: CallbackQuery, callback_data: dict):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])

    add_response(order_id, executor_id)

    order = get_responses_by_order_id(order_id)
    customer_id = order[0][2]
    executor = get_user_by_telegram_id(executor_id)

    await bot.send_message(customer_id,
        f"Новый отклик на ваш заказ!\n\n"
        f"👤 Имя: {executor[3]}\n"
        f"🔗 Портфолио: {executor[5]}\n"
        f"Связаться: @{executor[6]}\n\n"
        f"Принять исполнителя?",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ Принять", callback_data=response_callback.new(action='accept', response_id='0', order_id=str(order_id), executor_id=str(executor_id))),
            InlineKeyboardButton("❌ Отклонить", callback_data=response_callback.new(action='reject', response_id='0', order_id=str(order_id), executor_id=str(executor_id)))
        )
    )
    await callback_query.answer("Отклик отправлен заказчику.")

# Обработка выбора заказчика (принять или отклонить исполнителя)
@dp.callback_query_handler(response_callback.filter(action=['accept', 'reject']))
async def process_customer_choice(callback_query: CallbackQuery, callback_data: dict):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])
    action = callback_data['action']

    if action == 'accept':
        update_order_status(order_id, 'occupied')  # Обновление статуса заказа
        await bot.send_message(executor_id, "Поздравляем! Вас выбрали для выполнения заказа. Свяжитесь с заказчиком для дальнейших действий.", reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ Завершить заказ", callback_data=completion_callback.new(action='complete', order_id=str(order_id), executor_id=str(executor_id)))
        ))
        await callback_query.message.edit_text("Вы приняли исполнителя на заказ.")
    elif action == 'reject':
        await bot.send_message(executor_id, "К сожалению, заказчик выбрал другого исполнителя.")
        await callback_query.message.edit_text("Вы отклонили исполнителя на заказ.")

    await callback_query.answer()

# Завершение заказа исполнителем
@dp.callback_query_handler(completion_callback.filter(action='complete'))
async def complete_order(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])

    await callback_query.message.answer("Пожалуйста, загрузите видео для завершения заказа.")
    await CompletionForm.video.set()  # Устанавливаем состояние для получения видео
    await state.update_data(order_id=order_id, executor_id=executor_id)
    await callback_query.answer()

@dp.message_handler(content_types=types.ContentTypes.ANY, state=CompletionForm.video)
async def receive_video(message: types.Message, state: FSMContext):
    if message.content_type != 'video':
        await message.answer("Пожалуйста, отправьте видеофайл.")
        return

    data = await state.get_data()
    order_id = data['order_id']
    executor_id = data['executor_id']
    video_file_id = message.video.file_id

    # Получаем список ответов для заказа
    responses = get_responses_by_order_id(order_id)

    if responses:
        response = responses[0]
        customer_id = response[2]  # Предполагается, что это поле customer_id

        # Создаем клавиатуру для подтверждения или отклонения заказа
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Принять", callback_data=completion_callback.new(action='approve', order_id=str(order_id), executor_id=str(executor_id))),
            InlineKeyboardButton("❌ Отклонить", callback_data=completion_callback.new(action='reject', order_id=str(order_id), executor_id=str(executor_id)))
        )

        # Отправляем видео заказчику
        await bot.send_video(customer_id, video=video_file_id, caption="Исполнитель завершил заказ. Пожалуйста, проверьте результат.", reply_markup=keyboard)
        await message.answer("Видео отправлено заказчику на проверку.")
    else:
        await message.answer("Ошибка: не удалось найти заказчика.")
        print(f"Debug info: responses = {responses}")

    await state.finish()

# Обработка принятия или отклонения заказа заказчиком
@dp.callback_query_handler(completion_callback.filter(action=['approve', 'reject']))
async def handle_customer_feedback(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])
    action = callback_data['action']

    if action == 'approve':
        update_order_status(order_id, 'completed')
        await bot.send_message(executor_id, "Заказчик принял ваш заказ. Работа завершена.")
        await callback_query.message.edit_text("Вы приняли результат. Заказ завершен.")
    elif action == 'reject':
        await callback_query.message.answer("Пожалуйста, напишите замечания к работе.")
        await CompletionForm.feedback.set()
        await state.update_data(order_id=order_id, executor_id=executor_id)
        await callback_query.answer()

@dp.message_handler(state=CompletionForm.feedback)
async def handle_feedback(message: types.Message, state: FSMContext):
    feedback = message.text.strip()

    if len(feedback) < 5:
        await message.answer("Пожалуйста, введите более подробные замечания (минимум 5 символов).")
        return

    data = await state.get_data()
    executor_id = data['executor_id']

    await bot.send_message(executor_id, f"Заказчик отклонил ваш заказ с замечаниями: {feedback}")
    await message.answer("Замечания отправлены исполнителю.")
    await state.finish()



if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
