import sqlite3
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.callback_data import CallbackData
from aiogram.types import LabeledPrice, PreCheckoutQuery, ContentType
from aiogram.dispatcher.filters import Text
from database import create_tables, add_user, get_user_by_telegram_id, add_order, get_free_orders, update_order_status, add_response, get_responses_by_order_id, update_subscription_status

# Инициализация бота
API_TOKEN = '7264705176:AAFma9XWk3Xcc2rXUKGYSQX_Pz3xI5pfd8w'

PAYMENT_PROVIDER_TOKEN = "381764678:TEST:93594"

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

# Определяем клавиатуру для покупки подписки или ввода промокода
subscription_keyboard = InlineKeyboardMarkup(row_width=1).add(
    InlineKeyboardButton("🛒 Купить подписку", callback_data="buy_subscription"),
    InlineKeyboardButton("🎟 Ввести промокод", callback_data="enter_promo")
)

# Определяем состояния
class OrderForm(StatesGroup):
    details = State()  # Состояние для ввода деталей заказа

class CompletionForm(StatesGroup):
    video = State()  # Состояние для получения видео от исполнителя
    feedback = State()  # Состояние для получения комментариев от заказчика

# ID канала, на который нужно подписаться
CHANNEL_ID = '@inclama234'  # Замените на ваше имя канала

async def check_subscription(user_id):
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    return member.is_chat_member() or member.status == 'administrator' or member.status == 'creator'

@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    if await check_subscription(message.from_user.id):
        create_tables()  # Создаем таблицы в базе данных, если они еще не существуют
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🛠 Исполнитель", callback_data=role_callback.new(type='executor')),
            InlineKeyboardButton("💼 Заказчик", callback_data=role_callback.new(type='customer'))
        )
        await message.answer(
            "👋 Привет! Добро пожаловать в бота Инкламер, который связывает заказчиков и исполнителей для создания видео контента! 📹\n\n"
            "Выберите свою роль:\n\n"
            "🛠 Если вы хотите предлагать свои услуги как исполнитель.\n"
            "💼 Если вы хотите разместить заказ как заказчик.",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "Для использования этого бота, пожалуйста, подпишитесь на наш канал.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.strip('@')}")
            )
        )


@dp.callback_query_handler(role_callback.filter())
async def process_role(callback_query: CallbackQuery, callback_data: dict):
    if await check_subscription(callback_query.from_user.id):
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
    else:
        await bot.send_message(
            callback_query.from_user.id,
            "Для использования этого бота, пожалуйста, подпишитесь на наш канал.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.strip('@')}")
            )
        )
        await callback_query.answer()

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


# Добавляем кнопку "Пропустить" в процесс отправки портфолио
@dp.message_handler(
    lambda message: message.from_user.id in user_data and 'experience' in user_data[message.from_user.id] and
                    'portfolio' not in user_data[message.from_user.id] and
                    user_data[message.from_user.id]['role'] == 'executor',
    content_types=[types.ContentType.TEXT, types.ContentType.VIDEO])
async def process_portfolio(message: types.Message):
    user_id = message.from_user.id

    # Обработка видео
    if message.content_type == types.ContentType.VIDEO:
        video_file_id = message.video.file_id
        user_data[user_id]['portfolio'] = video_file_id
        await message.answer("🎥 Видео получено. Спасибо!")

    # Обработка ссылки
    elif message.content_type == types.ContentType.TEXT:
        link = message.text.strip()
        if link.startswith("http://") or link.startswith("https://"):
            user_data[user_id]['portfolio'] = link
            await message.answer("🔗 Ссылка на портфолио получена. Спасибо!")
        else:
            await message.answer("❗ Пожалуйста, отправьте корректную ссылку (начинающуюся с http:// или https://).")

    # Сохранение данных в базу данных, если портфолио было отправлено
    if 'portfolio' in user_data[user_id]:
        add_user(
            message.from_user.id,
            user_data[user_id]['role'],
            user_data[user_id]['name'],
            user_data[user_id]['experience'],
            user_data[user_id]['portfolio'],
            user_data[user_id]['username']
        )
        await message.answer("✅ Отлично! Вы зарегистрированы как Исполнитель 🛠")
        await executor_menu(message)


# Обновляем обработчик, который предлагает пользователю отправить портфолио, добавляя кнопку "Пропустить"
@dp.message_handler(
    lambda message: message.from_user.id in user_data and 'experience' not in user_data[message.from_user.id] and
                    user_data[message.from_user.id]['role'] == 'executor')
async def process_experience(message: types.Message):
    user_id = message.from_user.id
    experience = message.text.strip()

    if not experience.isdigit() or int(experience) < 0:
        await message.answer("❗ Пожалуйста, введите корректный опыт работы в годах (например, 5).")
        return

    user_data[user_id]['experience'] = experience

    # Клавиатура с кнопкой "Пропустить"
    skip_button = InlineKeyboardButton("⏭ Пропустить", callback_data="skip_portfolio")
    markup = InlineKeyboardMarkup().add(skip_button)

    await message.answer("Пожалуйста, отправьте пример ваших работ (ссылка или видео) или нажмите 'Пропустить':",
                         reply_markup=markup)


# Обработка нажатия на кнопку "Пропустить"
@dp.callback_query_handler(text="skip_portfolio")
async def skip_portfolio(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Сохраняем пользователя без портфолио
    user_data[user_id]['portfolio'] = None
    add_user(
        user_id,
        user_data[user_id]['role'],
        user_data[user_id]['name'],
        user_data[user_id]['experience'],
        user_data[user_id]['portfolio'],
        user_data[user_id]['username']
    )

    # Кнопка для прикрепления ссылки на портфолио
    attach_button = InlineKeyboardButton("🔗 Прикрепить ссылку на портфолио", callback_data="attach_portfolio")
    attach_markup = InlineKeyboardMarkup().add(attach_button)

    await bot.send_message(user_id, "Вы пропустили отправку портфолио. Вы зарегистрированы как Исполнитель 🛠",
                           reply_markup=attach_markup)
    await executor_menu(callback_query.message)

    await callback_query.answer()


# Обработка нажатия на кнопку "Прикрепить ссылку на портфолио"
@dp.callback_query_handler(text="attach_portfolio")
async def attach_portfolio(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    await bot.send_message(user_id,
                           "📎 Пожалуйста, отправьте ссылку на ваше портфолио (начинающуюся с http:// или https://) или видео.")

    # Ожидание нового ввода портфолио
    @dp.message_handler(content_types=[types.ContentType.TEXT, types.ContentType.VIDEO])
    async def process_new_portfolio(message: types.Message):
        if message.from_user.id == user_id:
            # Обработка видео
            if message.content_type == types.ContentType.VIDEO:
                video_file_id = message.video.file_id
                user_data[user_id]['portfolio'] = video_file_id
                await message.answer("🎥 Видео получено. Спасибо!")

            # Обработка ссылки
            elif message.content_type == types.ContentType.TEXT:
                link = message.text.strip()
                if link.startswith("http://") or link.startswith("https://"):
                    user_data[user_id]['portfolio'] = link
                    await message.answer("🔗 Ссылка на портфолио получена. Спасибо!")
                else:
                    await message.answer(
                        "❗ Пожалуйста, отправьте корректную ссылку (начинающуюся с http:// или https://).")

            # Обновление данных в базе данных
            if 'portfolio' in user_data[user_id]:
                add_user(
                    message.from_user.id,
                    user_data[user_id]['role'],
                    user_data[user_id]['name'],
                    user_data[user_id]['experience'],
                    user_data[user_id]['portfolio'],
                    user_data[user_id]['username']
                )
                await message.answer("✅ Ваше портфолио обновлено!")
                await executor_menu(message)


# Главное меню для Исполнителя
async def executor_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🔍 Просмотреть заказы", callback_data=order_callback.new(action='view', order_id='0')),
        InlineKeyboardButton("🔗 Прикрепить ссылку на портфолио", callback_data="attach_portfolio")  # Новая кнопка
    )
    await message.answer("Главное меню Исполнителя:", reply_markup=keyboard)

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
    # Получаем telegram_id пользователя напрямую из message.from_user.id
    telegram_id = message.from_user.id
    add_order(telegram_id, details)  # Используем telegram_id заказчика
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

    # Проверка подписки пользователя
    user = get_user_by_telegram_id(executor_id)
    if user and user[7] != 'active':  # Индекс 7, если subscription_status - это 8-е поле в таблице
        await callback_query.message.answer("Для отклика на заказы необходима активная подписка.", reply_markup=subscription_keyboard)
    else:
        add_response(order_id, executor_id)
        await bot.send_message(callback_query.from_user.id, "Вы успешно откликнулись на заказ.")

        # Извлекаем информацию о заказе
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT customer_id FROM orders WHERE id = ?', (order_id,))
        customer_id = cursor.fetchone()[0]
        conn.close()

        # Проверка, что customer_id - это telegram_id заказчика
        customer = get_user_by_telegram_id(customer_id)
        if not customer:
            await bot.send_message(callback_query.from_user.id, "Ошибка: не удалось найти заказчика.")
            return

        executor = get_user_by_telegram_id(executor_id)

        # Отправка сообщения заказчику
        await bot.send_message(customer[1],  # customer[1] содержит telegram_id заказчика
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

        # Проверка успешности отправки сообщения заказчику
        await bot.send_message(callback_query.from_user.id, "Сообщение заказчику отправлено.")

    await callback_query.answer("Отклик обработан.")


@dp.callback_query_handler(text="buy_subscription")
async def handle_buy_subscription(callback_query: CallbackQuery):
    prices = [
        LabeledPrice(label='💳 Месячная подписка', amount=50000),  # Цена в копейках (500 рублей)
    ]

    await bot.send_invoice(
        chat_id=callback_query.from_user.id,
        title="📅 Подписка на сервис",
        description="🔓 Подписка активируется на месяц.",
        payload="subscription-monthly",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        photo_url="https://example.com/photo.png",  # Замените на URL изображения товара
        photo_height=512,  # Необязательно
        photo_width=512,  # Необязательно
        photo_size=512,  # Необязательно
    )

@dp.pre_checkout_query_handler(lambda query: True)
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message):
    # Обновление статуса подписки в базе данных
    update_subscription_status(message.from_user.id, 'active')
    await message.answer("✅ Оплата успешно завершена! Ваша подписка активирована.")




@dp.callback_query_handler(text="enter_promo")
async def handle_enter_promo(callback_query: CallbackQuery):
    await bot.send_message(callback_query.from_user.id, "Пожалуйста, введите ваш промокод:")

    @dp.message_handler()
    async def process_promo_code(message: types.Message):
        promo_code = message.text.strip()
        # Проверка промокода
        if promo_code == "VALID_CODE":  # Пример проверки
            # Обновление статуса подписки в базе данных
            update_subscription_status(message.from_user.id, 'active')
            await message.answer("Промокод принят! Подписка активирована.")
        else:
            await message.answer("Неверный промокод. Попробуйте еще раз.")


# Обработка выбора заказчика (принять или отклонить исполнителя)
@dp.callback_query_handler(response_callback.filter(action=['accept', 'reject']))
async def process_customer_choice(callback_query: CallbackQuery, callback_data: dict):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])
    action = callback_data['action']
    customer_id = callback_query.from_user.id  # Telegram ID заказчика

    # Проверка подписки заказчика
    customer = get_user_by_telegram_id(customer_id)
    if action == 'accept':
        if customer and customer[7] != 'active':  # Индекс 7, если subscription_status - это 8-е поле в таблице
            await callback_query.message.answer("🛒 Для принятия исполнителя необходимо активировать подписку.", reply_markup=subscription_keyboard)
        else:
            update_order_status(order_id, 'occupied')  # Обновление статуса заказа
            customer_username = callback_query.from_user.username  # Получаем username заказчика
            await bot.send_message(
                executor_id,
                f"🎉 Поздравляем! Вас выбрали для выполнения заказа. Свяжитесь с заказчиком (@{customer_username}) для дальнейших действий.",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("✅ Завершить заказ", callback_data=completion_callback.new(action='complete', order_id=str(order_id), executor_id=str(executor_id)))
                )
            )
            await callback_query.message.edit_text("🎯 Вы приняли исполнителя на заказ.")
    elif action == 'reject':
        await bot.send_message(executor_id, "😔 К сожалению, заказчик выбрал другого исполнителя.")
        await callback_query.message.edit_text("❌ Вы отклонили исполнителя на заказ.")

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
    await message.answer(
        "Замечания отправлены исполнителю.",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("📝 Добавить изменения", callback_data=completion_callback.new(action='request_changes',
                                                                                               order_id=str(
                                                                                                   data['order_id']),
                                                                                               executor_id=str(
                                                                                                   executor_id)))
        )
    )
    await state.finish()


@dp.callback_query_handler(completion_callback.filter(action='request_changes'))
async def request_changes(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    order_id = int(callback_data['order_id'])
    executor_id = int(callback_data['executor_id'])

    await bot.send_message(executor_id, "Заказчик запросил изменения. Пожалуйста, отправьте новое видео.")
    await callback_query.message.answer("Пожалуйста, загрузите новое видео для завершения заказа.")

    # Сохраняем данные в состояние
    await state.update_data(order_id=order_id, executor_id=executor_id)
    await CompletionForm.video.set()  # Устанавливаем состояние для получения нового видео
    await callback_query.answer()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)