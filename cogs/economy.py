from __future__ import annotations

import asyncio
import datetime  # noqa: F401  (используется в шаблонах текста)
import json

import aiosqlite
import disnake
from disnake.ext import commands, tasks

# ==========================================
# ⚙️ ГЛАВНЫЕ НАСТРОЙКИ ЭКОНОМИКИ
# ==========================================
COIN_NAME = "Spartan Coin"
COIN_SYMBOL = "SC"
FAMILY_NAME = "Spartan Famq"
OWNER_ID = 458335355477950464

# ==========================================
# 💰 УПРАВЛЕНИЕ ЦЕНАМИ И НАГРАДАМИ
# ==========================================
RP_REWARDS = {
    "Цеха": 10, "Дилеры": 10, "Дроп": 10, "Капт": 10,
    "Остров": 10, "ФЗ": 10, "Поставка": 20, "Спек поставки": 375,
}

WEAPON_REWARDS = {
    "Спешик": 12, "Сайга": 8, "Тяга": 11, "Пулик": 35,
    "Адрики": 5, "Эпики": 7, "Глушитель": 2, "Рукоятка": 2, "Увел.магазин": 2,
}

SHOP_PRICES = {
    "WARN": 100,
    "MONEY_RATE": 500,
}

# ==========================================
# ТЕХНИЧЕСКИЕ НАСТРОЙКИ
# ==========================================
MAIN_COLOR = disnake.Colour(0x2B2D31)   # Тёмно-серый, ближе к скрину
ACCENT_COLOR = disnake.Colour(0x87CEEB)  # Голубой акцент
SUCCESS_COLOR = disnake.Colour(0x2E8B57)  # Зелёный для одобрения
ERROR_COLOR = disnake.Colour(0xED4245)   # Красный для отказа

CHANNELS = {
    "EARN_LOGS": 1497527331089158335,
    "SHOP_LOGS": 1497527148821614702,
    "LEADERBOARD": 1477407418286739670,
    "ECO_PANEL": 1477407363404140576,
    "TICKET_CATEGORY": 1463910681244991640,
}

EMOJIS = {
    "RP": "<:rp_emoji:1497559216179904604>",
    "WEAPON": "<:weapon_emoji:1497559218423857262>",
    "CART": "<:cart_emoji:1497559213990215812>",
    "MONEY": "<:money_emoji:1497559212044193913>",
    "CARD": "<:card_emoji:1497559210509205635>",
    "REPORT": "<:report_emoji:1497559208936210523>",
    "SUCCESS": "✅",
    "REJECT": "❌",
    "ERROR": "⚠️",
    "TRASH": "🗑️",
    "WIN": "🏆",
    "TIER": "🛡️",
    "DOT": "🔹",
    "TREASURY": "🏦",
    "WITHDRAW": "📤",
    "DEPOSIT": "📥",
    "ATTACH": "📎",
    "EDIT": "📝",
}

try:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception:
    config = {}

FAM_NAME = config.get("FAMILY_NAME", FAMILY_NAME)

# Применяем переопределения каналов из config.json, если они есть
for _ch_key, _ch_val in (config.get("CHANNELS", {}) or {}).items():
    if _ch_key in CHANNELS and isinstance(_ch_val, int):
        CHANNELS[_ch_key] = _ch_val

ACTIVE_CARTS: dict[int, dict] = {}
ACTIVE_TICKETS: dict[int, dict] = {}
ACTIVE_ORDERS: dict[int, dict] = {}
ACTIVE_TREASURY: dict[int, dict] = {}

# Действия для отчёта казны
TREASURY_ACTIONS = ("Снятие", "Пополнение")
MAX_TREASURY_FILES = 10


def e(key: str) -> str:
    val = EMOJIS.get(key, "")
    return f"{val} " if val else ""


def e_btn(key: str):
    """Эмодзи без пробела для кнопок и опций селекта (или None)."""
    val = EMOJIS.get(key, "")
    return val if val else None


def simple_container(text: str, color=ACCENT_COLOR) -> list[disnake.ui.Container]:
    return [disnake.ui.Container(disnake.ui.TextDisplay(text), accent_colour=color)]


def get_safe_eco_banner():
    return (
        config.get("IMAGES", {}).get("ECONOMY_BANNER", "").strip().replace("Https", "https")
    )


async def get_user_balance(user_id: int) -> int:
    async with aiosqlite.connect("data/database.sqlite") as db:
        async with db.execute(
            "SELECT balance FROM user_coins WHERE user_id = ?", (str(user_id),)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def auto_delete_ticket(channel: disnake.TextChannel, delay: int) -> None:
    """Авто-удаление временного канала через заданное число секунд."""
    try:
        await asyncio.sleep(delay)
        await channel.delete()
    except Exception:
        pass


def is_moderator(member: disnake.Member) -> bool:
    """Проверка, что пользователь — модератор согласно config.json (ROLES.MODERATOR)."""
    mod_roles = config.get("ROLES", {}).get("MODERATOR", []) or []
    if not mod_roles:
        # Если роли не настроены — модератором считается только владелец
        return getattr(member, "id", 0) == OWNER_ID
    return any(r.id in mod_roles for r in getattr(member, "roles", []))


def format_amount(amount: int) -> str:
    """Форматирует целое число с разделителями (1 234 567)."""
    return f"{amount:,}".replace(",", " ")


def resolve_report_status(
    container: disnake.ui.Container,
    is_approved: bool,
    mod_id: int,
    reason: str | None = None,
    mod_name: str | None = None,
    keep_status_buttons: bool = False,
) -> list[disnake.ui.Container]:
    """Возвращает контейнер с обновлённым статусом проверки.

    - Добавляет блок «Статус / Проверил / Причина отказа» в текст.
    - Если ``keep_status_buttons=True`` — заменяет рабочие кнопки на
      «Одобрено / Проверил: X / Заполнить отчёт» (как на скрине модератора).
    - Иначе просто убирает все кнопки, оставляя медиа и текст.
    """
    status_emoji = "✅" if is_approved else "❌"
    status_text = "Одобрено" if is_approved else "Отклонено"
    color = SUCCESS_COLOR if is_approved else ERROR_COLOR

    new_children: list = []
    for child in container.children:
        if isinstance(child, disnake.ui.TextDisplay):
            append_text = (
                f"\n\n**Статус:** {status_emoji} {status_text}\n"
                f"**Проверил:** <@{mod_id}>"
            )
            if reason:
                append_text += f"\n**Причина отказа:** {reason}"
            new_children.append(disnake.ui.TextDisplay(child.content + append_text))
        elif not isinstance(child, disnake.ui.ActionRow):
            new_children.append(child)

    if keep_status_buttons:
        mod_label = (mod_name or str(mod_id))[:60]
        status_btn_style = (
            disnake.ButtonStyle.success if is_approved else disnake.ButtonStyle.danger
        )
        new_children.append(
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    label=status_text,
                    style=status_btn_style,
                    custom_id=f"_t_status:{mod_id}",
                    disabled=True,
                ),
                disnake.ui.Button(
                    label=f"Проверил: {mod_label}",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"_t_mod:{mod_id}",
                    disabled=True,
                ),
                disnake.ui.Button(
                    label="Заполнить отчёт",
                    style=disnake.ButtonStyle.secondary,
                    emoji=e_btn("EDIT"),
                    custom_id="_t_fill_report",
                    disabled=True,
                ),
            )
        )

    return [disnake.ui.Container(*new_children, accent_colour=color)]


# ==========================================
# ГЕНЕРАТОРЫ ИНТЕРФЕЙСОВ (Components V2)
# ==========================================
def build_economy_panel() -> list[disnake.ui.Container]:
    children: list = []
    banner_url = get_safe_eco_banner()
    if banner_url:
        children.append(disnake.ui.MediaGallery(disnake.MediaGalleryItem(banner_url)))

    children.append(
        disnake.ui.TextDisplay(
            f"## 🛡️ ФИНАНСОВАЯ ПАНЕЛЬ СЕМЬИ\n**{FAM_NAME}** • Управление экономикой"
        )
    )
    children.append(
        disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small)
    )

    rp_text = wp_text = ""
    for v in sorted(set(RP_REWARDS.values())):
        rp_text += (
            f"> ` {v:3} {COIN_SYMBOL} ` {e('DOT')}"
            f" {', '.join([k for k, val in RP_REWARDS.items() if val == v])}\n"
        )
    for v in sorted(set(WEAPON_REWARDS.values())):
        wp_text += (
            f"> ` {v:3} {COIN_SYMBOL} ` {e('DOT')}"
            f" {', '.join([k for k, val in WEAPON_REWARDS.items() if val == v])}\n"
        )
    rate_str = f"{SHOP_PRICES['MONEY_RATE']:,}".replace(",", ".")

    desc = (
        f"Добро пожаловать в финансовую панель **{FAM_NAME}**.\n"
        f"Проявляйте активность, зарабатывайте **{COIN_NAME} [ {COIN_SYMBOL} ]** "
        f"и обменивайте их на награды.\n\n"
        f"### {e('RP')} Система заработка\n"
        f"*Организация и участие в РП-мероприятиях:*\n{rp_text}\n"
        f"*Сдача вооружения на склад (оформляется через меню ниже):*\n{wp_text}\n\n"
        f"### {e('CART')} Ассортимент магазина\n"
        f"> ` {SHOP_PRICES['WARN']:3} {COIN_SYMBOL} ` {e('DOT')} Снятие выговора\n"
        f"> `   1 {COIN_SYMBOL} ` {e('DOT')} {rate_str}$ (Игровая валюта)\n"
        f"> `   ? {COIN_SYMBOL} ` {e('DOT')} Спец. предметы (Индивидуально)\n"
    )
    children.append(disnake.ui.TextDisplay(desc))
    children.append(
        disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small)
    )

    children.append(
        disnake.ui.ActionRow(
            disnake.ui.Button(
                label="Мой баланс",
                style=disnake.ButtonStyle.secondary,
                custom_id="eco_balance",
                emoji=EMOJIS.get("CARD"),
            ),
            disnake.ui.Button(
                label="Получить TC",
                style=disnake.ButtonStyle.secondary,
                custom_id="eco_earn",
                emoji=EMOJIS.get("REPORT"),
            ),
            disnake.ui.Button(
                label="Магазин",
                style=disnake.ButtonStyle.secondary,
                custom_id="eco_shop",
                emoji=EMOJIS.get("CART"),
            ),
        )
    )
    return [disnake.ui.Container(*children, accent_colour=ACCENT_COLOR)]


def build_cart_container(user_id: int) -> list[disnake.ui.Container]:
    data = ACTIVE_CARTS.get(
        user_id,
        {"cart": {k: 0 for k in WEAPON_REWARDS.keys()}, "mult": 1},
    )
    cart, mult = data["cart"], data["mult"]

    desc = (
        "> Нажимайте на кнопки ниже, чтобы добавить предметы.\n"
        "> *Используйте «Множитель», чтобы добавлять по 2, 3, 5 или 10 шт. "
        "за один клик!*\n\n**Список к сдаче:**\n"
    )
    has_items = False
    total_lc = sum(v * WEAPON_REWARDS[k] for k, v in cart.items())

    for k, v in cart.items():
        if v > 0:
            desc += (
                f"{e('DOT')} {k}: **{v} шт.** "
                f"`(+{v * WEAPON_REWARDS[k]} {COIN_SYMBOL})`\n"
            )
            has_items = True

    if not has_items:
        desc += "*Корзина пока пуста.*\n"
    desc += f"\n**Итоговая награда:** `{total_lc} {COIN_SYMBOL}`"

    children = [
        disnake.ui.TextDisplay(f"## {e('WEAPON')} Корзина: Сдача Оружия\n" + desc),
        disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
    ]

    current_row: list = []
    for name in WEAPON_REWARDS.keys():
        current_row.append(
            disnake.ui.Button(
                label=f"{name} x{cart[name]}",
                style=(
                    disnake.ButtonStyle.primary
                    if cart[name] > 0
                    else disnake.ButtonStyle.secondary
                ),
                custom_id=f"cart_add:{name}",
            )
        )
        if len(current_row) == 4:
            children.append(disnake.ui.ActionRow(*current_row))
            current_row = []
    if current_row:
        children.append(disnake.ui.ActionRow(*current_row))

    children.append(
        disnake.ui.ActionRow(
            disnake.ui.Button(
                label=f"Множитель: x{mult}",
                style=disnake.ButtonStyle.secondary,
                custom_id="cart_mult",
            ),
            disnake.ui.Button(
                label="Очистить",
                style=disnake.ButtonStyle.danger,
                emoji=EMOJIS.get("TRASH"),
                custom_id="cart_clear",
            ),
            disnake.ui.Button(
                label="Далее (Оформить)",
                style=disnake.ButtonStyle.success,
                emoji=EMOJIS.get("SUCCESS"),
                custom_id="cart_submit",
            ),
        )
    )
    return [disnake.ui.Container(*children, accent_colour=ACCENT_COLOR)]


def build_treasury_action_container() -> list[disnake.ui.Container]:
    """Контейнер с селектом для выбора типа операции казны (Снятие/Пополнение)."""
    options = [
        disnake.SelectOption(
            label="Снятие",
            description="Списание из кассы семьи",
            value="Снятие",
            emoji=e_btn("WITHDRAW"),
        ),
        disnake.SelectOption(
            label="Пополнение",
            description="Внесение средств в кассу семьи",
            value="Пополнение",
            emoji=e_btn("DEPOSIT"),
        ),
    ]
    return [
        disnake.ui.Container(
            disnake.ui.TextDisplay(
                f"## {e('TREASURY')} Отчёт казны\n"
                f"{e('DOT')} **Шаг 1:** Выберите тип операции ниже.\n"
                f"{e('DOT')} **Шаг 2:** Заполните форму (паспорт, сумма, причина).\n"
                f"{e('DOT')} **Шаг 3:** Прикрепите до **{MAX_TREASURY_FILES}** "
                f"скриншотов/видео в этот канал и нажмите «Отправить отчёт».\n\n"
                f"-# Канал авто-удалится через 5 минут."
            ),
            disnake.ui.ActionRow(
                disnake.ui.StringSelect(
                    placeholder="Выберите тип операции…",
                    options=options,
                    custom_id="treasury_action_select",
                )
            ),
            accent_colour=ACCENT_COLOR,
        )
    ]


def build_treasury_upload_container(action: str, static_id: str, amount: int, reason: str) -> list[disnake.ui.Container]:
    """Контейнер, в котором пользователь видит сохранённые данные и кнопку отправки."""
    formatted_amount = format_amount(amount)
    return [
        disnake.ui.Container(
            disnake.ui.TextDisplay(
                f"## {e('TREASURY')} Загрузка доказательств\n"
                f"**Действие:** {action}\n"
                f"**Паспорт:** `{static_id}`\n"
                f"**Сумма:** `{formatted_amount}`\n"
                f"**Причина:** {reason}\n\n"
                f"{e('ATTACH')} Прикрепите до **{MAX_TREASURY_FILES}** файлов "
                f"(скриншоты/видео) в этот канал и нажмите «Отправить отчёт».\n"
                f"-# Размер каждого файла ограничен лимитами Discord."
            ),
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    label="Изменить данные",
                    style=disnake.ButtonStyle.secondary,
                    emoji=e_btn("EDIT"),
                    custom_id="treasury_edit",
                ),
                disnake.ui.Button(
                    label="Отправить отчёт",
                    style=disnake.ButtonStyle.success,
                    emoji=EMOJIS.get("SUCCESS"),
                    custom_id="treasury_submit",
                ),
                disnake.ui.Button(
                    label="Отменить",
                    style=disnake.ButtonStyle.danger,
                    emoji=EMOJIS.get("REJECT"),
                    custom_id="treasury_cancel",
                ),
            ),
            accent_colour=ACCENT_COLOR,
        )
    ]


async def update_economy_leaderboard(bot):
    channel_id = CHANNELS["LEADERBOARD"]
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    async with aiosqlite.connect("data/database.sqlite") as db:
        async with db.execute(
            "SELECT user_id, balance FROM user_coins ORDER BY balance DESC LIMIT 10"
        ) as cursor:
            top_users = await cursor.fetchall()

    desc = ""
    if top_users:
        for idx, row in enumerate(top_users):
            desc += f"> **{idx + 1}.** <@{row[0]}> — `{row[1]} {COIN_SYMBOL}`\n"
    else:
        desc = "> Пока нет данных."

    cont = [
        disnake.ui.Container(
            disnake.ui.TextDisplay(
                f"## {e('WIN')} Топ богачей ({COIN_NAME})\n{desc}\n"
                f"-# Авто-обновление каждую минуту"
            ),
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    label="Мой баланс",
                    style=disnake.ButtonStyle.secondary,
                    custom_id="check_my_balance",
                    emoji=EMOJIS.get("CARD"),
                )
            ),
            accent_colour=ACCENT_COLOR,
        )
    ]

    bot_msg = None
    async for msg in channel.history(limit=20):
        if (
            msg.author == bot.user
            and getattr(msg.flags, "is_components_v2", False)
            and msg.components
            and "Топ богачей" in msg.components[0].children[0].content
        ):
            bot_msg = msg
            break

    if bot_msg:
        try:
            await bot_msg.edit(components=cont)
        except Exception:
            pass
    else:
        try:
            await channel.send(components=cont)
        except Exception:
            pass


# ==========================================
# МОДАЛКИ (ТИКЕТЫ И МАГАЗИН)
# ==========================================
class EarnSubmitModal(disnake.ui.Modal):
    def __init__(
        self,
        user_id: int,
        detail_text: str,
        reward: int,
        origin_message: disnake.Message,
        is_weapon: bool = False,
    ):
        self.user_id = user_id
        self.detail_text = detail_text
        self.reward = reward
        self.origin_message = origin_message
        components = [
            disnake.ui.TextInput(
                label="Номер паспорта (Статик)",
                placeholder="Например: 82520",
                custom_id="static_id",
                style=disnake.TextInputStyle.short,
                max_length=20,
                required=True,
            ),
            disnake.ui.TextInput(
                label="Причина / Описание",
                placeholder="Опишите причину...",
                custom_id="comment",
                style=disnake.TextInputStyle.paragraph,
                required=False,
            ),
        ]
        super().__init__(
            title=("Сдача Оружия" if is_weapon else "Отчёт за РП"),
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        ACTIVE_TICKETS[self.user_id] = {
            "detail_text": self.detail_text,
            "reward": self.reward,
            "static_id": inter.text_values["static_id"].strip(),
            "comment": inter.text_values.get("comment", "").strip(),
        }

        cont = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    f"## {e('REPORT')} Загрузка доказательств\n"
                    f"**Действие:** {self.detail_text}\n"
                    f"**Сумма к получению:** `{self.reward} {COIN_SYMBOL}`\n\n"
                    f"{e('DOT')} **Шаг 1:** Прикрепите до 10 скриншотов в этот канал.\n"
                    f"{e('DOT')} **Шаг 2:** Нажмите кнопку **«Отправить отчёт»**.\n\n"
                    f"-# Для отмены нажмите «Отменить»."
                ),
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label="Отправить отчёт",
                        style=disnake.ButtonStyle.success,
                        emoji=EMOJIS.get("SUCCESS"),
                        custom_id="ticket_submit",
                    ),
                    disnake.ui.Button(
                        label="Отменить",
                        style=disnake.ButtonStyle.danger,
                        emoji=EMOJIS.get("REJECT"),
                        custom_id="ticket_cancel",
                    ),
                ),
                accent_colour=ACCENT_COLOR,
            )
        ]
        await self.origin_message.edit(components=cont)
        await inter.response.send_message(
            components=simple_container(
                f"{e('SUCCESS')} Данные сохранены! Теперь скиньте скриншоты в этот чат.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )


class TreasurySubmitModal(disnake.ui.Modal):
    """Модалка отчёта казны: паспорт, сумма, причина."""

    def __init__(self, user_id: int, action: str, origin_message: disnake.Message):
        self.user_id = user_id
        self.action = action
        self.origin_message = origin_message
        prefilled = ACTIVE_TREASURY.get(user_id, {})
        components = [
            disnake.ui.TextInput(
                label="Номер паспорта",
                placeholder="Введите номер (например: 82520)",
                custom_id="static_id",
                style=disnake.TextInputStyle.short,
                max_length=20,
                required=True,
                value=prefilled.get("static_id", ""),
            ),
            disnake.ui.TextInput(
                label="Сумма",
                placeholder="Введите сумму",
                custom_id="amount",
                style=disnake.TextInputStyle.short,
                max_length=15,
                required=True,
                value=str(prefilled.get("amount", "")) if prefilled.get("amount") else "",
            ),
            disnake.ui.TextInput(
                label="Причина",
                placeholder="Опишите причину…",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                required=True,
                max_length=1000,
                value=prefilled.get("reason", ""),
            ),
        ]
        super().__init__(title=f"Отчёт казны: {action}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        amount_raw = inter.text_values["amount"].strip().replace(" ", "").replace(",", "")
        if not amount_raw.isdigit() or int(amount_raw) <= 0:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('ERROR')} Сумма должна быть положительным числом.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )

        amount = int(amount_raw)
        static_id = inter.text_values["static_id"].strip()
        reason = inter.text_values["reason"].strip()

        ACTIVE_TREASURY[self.user_id] = {
            "action": self.action,
            "static_id": static_id,
            "amount": amount,
            "reason": reason,
        }

        try:
            await self.origin_message.edit(
                components=build_treasury_upload_container(
                    self.action, static_id, amount, reason
                )
            )
        except Exception:
            # Сообщение могло быть удалено — отправим новое
            try:
                await inter.channel.send(
                    components=build_treasury_upload_container(
                        self.action, static_id, amount, reason
                    )
                )
            except Exception:
                pass

        await inter.response.send_message(
            components=simple_container(
                f"{e('SUCCESS')} Данные сохранены! Прикрепите до "
                f"{MAX_TREASURY_FILES} файлов и нажмите «Отправить отчёт».",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )


class RejectEarnModal(disnake.ui.Modal):
    def __init__(
        self,
        target_user_id: int,
        message: disnake.Message,
        container: disnake.ui.Container,
    ):
        self.target_user_id = target_user_id
        self.message = message
        self.container = container
        super().__init__(
            title="Отклонение отчёта",
            components=[
                disnake.ui.TextInput(
                    label="Причина отказа",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        reason = inter.text_values["reason"]

        target_member = inter.guild.get_member(self.target_user_id)
        if target_member:
            try:
                await target_member.send(
                    components=simple_container(
                        f"## {e('REPORT')} Отчёт отклонён\n"
                        f"Ваш отчёт на заработок был отклонён.\n\n"
                        f"**Причина:**\n> {reason}",
                        ERROR_COLOR,
                    )
                )
            except Exception:
                pass

        mod_name = getattr(inter.author, "display_name", None) or inter.author.name
        new_cont = resolve_report_status(
            self.container,
            is_approved=False,
            mod_id=inter.author.id,
            reason=reason,
            mod_name=mod_name,
            keep_status_buttons=True,
        )
        await self.message.edit(components=new_cont)
        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')} Отчёт успешно отклонён.", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


class RejectTreasuryModal(disnake.ui.Modal):
    """Отклонение отчёта казны с причиной (показывается на эмбеде модератора)."""

    def __init__(
        self,
        target_user_id: int,
        message: disnake.Message,
        container: disnake.ui.Container,
    ):
        self.target_user_id = target_user_id
        self.message = message
        self.container = container
        super().__init__(
            title="Отклонение отчёта казны",
            components=[
                disnake.ui.TextInput(
                    label="Причина отказа",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        reason = inter.text_values["reason"]

        target_member = inter.guild.get_member(self.target_user_id) if inter.guild else None
        if target_member:
            try:
                await target_member.send(
                    components=simple_container(
                        f"## {e('TREASURY')} Отчёт казны отклонён\n"
                        f"Ваш отчёт по операции казны был отклонён.\n\n"
                        f"**Причина:**\n> {reason}",
                        ERROR_COLOR,
                    )
                )
            except Exception:
                pass

        mod_name = getattr(inter.author, "display_name", None) or inter.author.name
        new_cont = resolve_report_status(
            self.container,
            is_approved=False,
            mod_id=inter.author.id,
            reason=reason,
            mod_name=mod_name,
            keep_status_buttons=True,
        )
        await self.message.edit(components=new_cont)
        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')} Отчёт казны отклонён.", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


class WarnModal(disnake.ui.Modal):
    def __init__(self):
        super().__init__(
            title=f"Снятие выговора ({SHOP_PRICES['WARN']} SC)",
            components=[
                disnake.ui.TextInput(
                    label="Ваш статический ID",
                    custom_id="static_id",
                    style=disnake.TextInputStyle.short,
                    required=True,
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        static_id = inter.text_values["static_id"]

        desc = (
            f"**Отправил:** <@{inter.author.id}>\n"
            f"**Паспорт:** `{static_id}`\n"
            f"**Действие:** Покупка (Снятие выговора)\n"
            f"**Сумма:** `{SHOP_PRICES['WARN']} {COIN_SYMBOL}`\n"
        )
        cont = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    f"## {e('CART')} Новый заказ в магазине\n" + desc
                ),
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label="Одобрить",
                        style=disnake.ButtonStyle.success,
                        emoji="✅",
                        custom_id=(
                            f"shop_acc:{inter.author.id}:{SHOP_PRICES['WARN']}"
                        ),
                    ),
                    disnake.ui.Button(
                        label="Отклонить",
                        style=disnake.ButtonStyle.danger,
                        emoji="❌",
                        custom_id=f"shop_rej:{inter.author.id}",
                    ),
                ),
                accent_colour=ACCENT_COLOR,
            )
        ]
        log_channel = inter.bot.get_channel(int(CHANNELS["SHOP_LOGS"]))
        if log_channel:
            await log_channel.send(components=cont)
        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')} Заявка отправлена!", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


class BuyMoneyModal(disnake.ui.Modal):
    def __init__(self, current_balance: int):
        self.current_balance = current_balance
        super().__init__(
            title=f"Обмен: 1 SC = {SHOP_PRICES['MONEY_RATE']}$",
            components=[
                disnake.ui.TextInput(
                    label=f"Сумма в {COIN_SYMBOL}",
                    placeholder=f"Максимум: {current_balance}",
                    custom_id="coin_amount",
                    style=disnake.TextInputStyle.short,
                    required=True,
                ),
                disnake.ui.TextInput(
                    label="Ваш статический ID",
                    custom_id="static_id",
                    style=disnake.TextInputStyle.short,
                    required=True,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        amount_str = inter.text_values["coin_amount"].strip()
        if not amount_str.isdigit() or int(amount_str) <= 0:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('ERROR')} Некорректное число.", ERROR_COLOR
                ),
                ephemeral=True,
            )
        coins_to_spend = int(amount_str)
        if coins_to_spend > self.current_balance:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('ERROR')} Недостаточно средств.", ERROR_COLOR
                ),
                ephemeral=True,
            )

        money_amount = coins_to_spend * SHOP_PRICES["MONEY_RATE"]
        formatted_money = f"{money_amount:,}".replace(",", ".")
        static_id = inter.text_values["static_id"]

        ACTIVE_ORDERS[inter.author.id] = {
            "coins": coins_to_spend,
            "money": money_amount,
            "static": static_id,
        }

        cont = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    f"## 🧾 Предварительный расчёт обмена\n"
                    f"Пожалуйста, проверьте данные перед отправкой:\n\n"
                    f"**К списанию:** `{coins_to_spend} {COIN_SYMBOL}`\n"
                    f"**К получению:** `{formatted_money}$`\n"
                    f"**Статик:** `{static_id}`"
                ),
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label="Подтвердить",
                        style=disnake.ButtonStyle.success,
                        emoji=EMOJIS.get("SUCCESS"),
                        custom_id="shop_confirm",
                    ),
                    disnake.ui.Button(
                        label="Отменить",
                        style=disnake.ButtonStyle.danger,
                        emoji=EMOJIS.get("REJECT"),
                        custom_id="shop_cancel",
                    ),
                ),
                accent_colour=ACCENT_COLOR,
            )
        ]
        await inter.response.send_message(components=cont, ephemeral=True)


class BuySpecialModal(disnake.ui.Modal):
    def __init__(self, current_balance: int):
        super().__init__(
            title=f"Спецзаказ (Баланс: {current_balance} SC)",
            components=[
                disnake.ui.TextInput(
                    label="Название предмета",
                    custom_id="item_name",
                    style=disnake.TextInputStyle.short,
                    required=True,
                ),
                disnake.ui.TextInput(
                    label="Ваш статический ID",
                    custom_id="static_id",
                    style=disnake.TextInputStyle.short,
                    required=True,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        static_id = inter.text_values["static_id"]
        item_name = inter.text_values["item_name"]

        desc = (
            f"**Отправил:** <@{inter.author.id}>\n"
            f"**Паспорт:** `{static_id}`\n"
            f"**Действие:** Спецзаказ ({item_name})\n"
            f"**Сумма:** `? {COIN_SYMBOL}`\n"
        )
        cont = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    f"## {e('CART')} Новый заказ в магазине\n" + desc
                ),
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label="Назначить цену и Одобрить",
                        style=disnake.ButtonStyle.success,
                        emoji="✅",
                        custom_id=f"shop_acc_spec:{inter.author.id}",
                    ),
                    disnake.ui.Button(
                        label="Отклонить",
                        style=disnake.ButtonStyle.danger,
                        emoji="❌",
                        custom_id=f"shop_rej:{inter.author.id}",
                    ),
                ),
                accent_colour=ACCENT_COLOR,
            )
        ]
        log_channel = inter.bot.get_channel(int(CHANNELS["SHOP_LOGS"]))
        if log_channel:
            await log_channel.send(components=cont)
        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')} Заявка оформлена!", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


class AcceptSpecialModal(disnake.ui.Modal):
    def __init__(
        self,
        target_user_id: int,
        message: disnake.Message,
        container: disnake.ui.Container,
    ):
        self.target_user_id = target_user_id
        self.message = message
        self.container = container
        super().__init__(
            title="Обработка спецзаказа",
            components=[
                disnake.ui.TextInput(
                    label=f"Цена в {COIN_SYMBOL}",
                    custom_id="price",
                    style=disnake.TextInputStyle.short,
                    required=True,
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        price = inter.text_values["price"].strip()
        if not price.isdigit() or int(price) <= 0:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('ERROR')} Ошибка в числе.", ERROR_COLOR
                ),
                ephemeral=True,
            )
        price = int(price)

        await inter.response.defer(ephemeral=True)
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT balance FROM user_coins WHERE user_id = ?",
                (str(self.target_user_id),),
            ) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] < price:
                    return await inter.followup.send(
                        components=simple_container(
                            f"{e('ERROR')} У игрока недостаточно средств.",
                            ERROR_COLOR,
                        ),
                        ephemeral=True,
                    )
            await db.execute(
                "UPDATE user_coins SET balance = balance - ? WHERE user_id = ?",
                (price, str(self.target_user_id)),
            )
            await db.commit()

        mod_label = (
            getattr(inter.author, "display_name", None) or inter.author.name
        )[:60]
        new_children: list = []
        for child in self.container.children:
            if isinstance(child, disnake.ui.TextDisplay):
                text = child.content.replace(
                    f"`? {COIN_SYMBOL}`", f"`{price} {COIN_SYMBOL}`"
                )
                text += (
                    f"\n\n**Статус:** ✅ Выполнено\n"
                    f"**Списано:** `{price} {COIN_SYMBOL}`\n"
                    f"**Исполнитель:** <@{inter.author.id}>"
                )
                new_children.append(disnake.ui.TextDisplay(text))
            elif not isinstance(child, disnake.ui.ActionRow):
                new_children.append(child)

        new_children.append(
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    label="Одобрено",
                    style=disnake.ButtonStyle.success,
                    custom_id=f"_s_status:{inter.author.id}",
                    disabled=True,
                ),
                disnake.ui.Button(
                    label=f"Проверил: {mod_label}",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"_s_mod:{inter.author.id}",
                    disabled=True,
                ),
                disnake.ui.Button(
                    label="Заполнить отчёт",
                    style=disnake.ButtonStyle.secondary,
                    emoji=e_btn("EDIT"),
                    custom_id="_s_fill_report",
                    disabled=True,
                ),
            )
        )
        await self.message.edit(
            components=[disnake.ui.Container(*new_children, accent_colour=SUCCESS_COLOR)]
        )
        await inter.followup.send(
            components=simple_container(f"{e('SUCCESS')} Выполнено.", SUCCESS_COLOR),
            ephemeral=True,
        )


class RejectOrderModal(disnake.ui.Modal):
    def __init__(
        self,
        target_user_id: int,
        message: disnake.Message,
        container: disnake.ui.Container,
    ):
        self.target_user_id = target_user_id
        self.message = message
        self.container = container
        super().__init__(
            title="Отклонение заказа",
            components=[
                disnake.ui.TextInput(
                    label="Причина отклонения",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        reason = inter.text_values["reason"]
        mod_name = getattr(inter.author, "display_name", None) or inter.author.name
        new_cont = resolve_report_status(
            self.container,
            is_approved=False,
            mod_id=inter.author.id,
            reason=reason,
            mod_name=mod_name,
            keep_status_buttons=True,
        )
        await self.message.edit(components=new_cont)
        await inter.followup.send(
            components=simple_container(
                f"{e('SUCCESS')} Заказ отменён.", SUCCESS_COLOR
            ),
            ephemeral=True,
        )


# ==========================================
# ОСНОВНОЙ COG
# ==========================================
class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_coins "
                "(user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)"
            )
            await db.commit()

        if not self.auto_update_economy.is_running():
            self.auto_update_economy.start()

        channel_id = CHANNELS["ECO_PANEL"]
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                async for msg in channel.history(limit=10):
                    if msg.author == self.bot.user:
                        is_old_panel = (
                            msg.embeds
                            and msg.embeds[-1].author
                            and "ФИНАНСОВАЯ ПАНЕЛЬ СЕМЬИ"
                            in str(msg.embeds[-1].author.name)
                        )
                        is_new_panel = getattr(msg.flags, "is_components_v2", False)
                        if is_old_panel or is_new_panel:
                            try:
                                await msg.edit(
                                    content=None,
                                    embeds=[],
                                    components=build_economy_panel(),
                                )
                                return
                            except Exception:
                                pass
                try:
                    await channel.send(components=build_economy_panel())
                except Exception:
                    pass

    @tasks.loop(minutes=1)
    async def auto_update_economy(self):
        await update_economy_leaderboard(self.bot)

    # -----------------------------------------
    # SELECT MENUS
    # -----------------------------------------
    @commands.Cog.listener()
    async def on_dropdown(self, inter: disnake.MessageInteraction):
        custom_id = inter.component.custom_id
        if not inter.values:
            return

        if custom_id == "earn_rp_select":
            event_type = inter.values[0]
            await inter.response.send_modal(
                EarnSubmitModal(
                    inter.author.id,
                    event_type,
                    RP_REWARDS[event_type],
                    inter.message,
                    is_weapon=False,
                )
            )

        elif custom_id == "shop_select_menu":
            action = inter.values[0]
            balance = await get_user_balance(inter.author.id)

            if action == "buy_warn":
                if balance < SHOP_PRICES["WARN"]:
                    return await inter.response.send_message(
                        components=simple_container(
                            f"{e('ERROR')}Нужно `{SHOP_PRICES['WARN']} {COIN_SYMBOL}`.",
                            ERROR_COLOR,
                        ),
                        ephemeral=True,
                    )
                await inter.response.send_modal(WarnModal())
            elif action == "buy_money":
                if balance < 1:
                    return await inter.response.send_message(
                        components=simple_container(
                            f"{e('ERROR')}Нет {COIN_SYMBOL} для обмена.", ERROR_COLOR
                        ),
                        ephemeral=True,
                    )
                await inter.response.send_modal(BuyMoneyModal(balance))
            elif action == "buy_special":
                await inter.response.send_modal(BuySpecialModal(balance))

        elif custom_id == "treasury_action_select":
            action = inter.values[0]
            if action not in TREASURY_ACTIONS:
                return await inter.response.send_message(
                    components=simple_container(
                        f"{e('ERROR')} Неизвестное действие.", ERROR_COLOR
                    ),
                    ephemeral=True,
                )
            ACTIVE_TREASURY.setdefault(inter.author.id, {})["action"] = action
            await inter.response.send_modal(
                TreasurySubmitModal(inter.author.id, action, inter.message)
            )

    # -----------------------------------------
    # BUTTONS
    # -----------------------------------------
    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        custom_id = inter.component.custom_id

        if custom_id in ("eco_balance", "check_my_balance"):
            balance = await get_user_balance(inter.author.id)

            rank = 1
            async with aiosqlite.connect("data/database.sqlite") as db:
                if balance > 0:
                    async with db.execute(
                        "SELECT COUNT(*) FROM user_coins WHERE balance > ?",
                        (balance,),
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            rank = row[0] + 1
                else:
                    async with db.execute(
                        "SELECT COUNT(*) FROM user_coins WHERE balance > 0"
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            rank = row[0] + 1

            cont = simple_container(
                f"## {e('CARD')} Ваш баланс\n"
                f"На счету: **{balance} {COIN_SYMBOL}**\nМесто в топе: **#{rank}**",
                ACCENT_COLOR,
            )
            await inter.response.send_message(components=cont, ephemeral=True)
            return

        if custom_id == "eco_earn":
            await inter.response.defer(ephemeral=True)
            guild = inter.guild
            category = guild.get_channel(CHANNELS.get("TICKET_CATEGORY"))

            overwrites = {
                guild.default_role: disnake.PermissionOverwrite(read_messages=False),
                inter.author: disnake.PermissionOverwrite(
                    read_messages=True, send_messages=True, attach_files=True
                ),
                guild.me: disnake.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_channels=True
                ),
            }
            temp_channel = await guild.create_text_channel(
                name=f"отчёт-{inter.author.name}",
                category=category,
                overwrites=overwrites,
            )

            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"{inter.author.mention}\n"
                        f"## {e('REPORT')} Заработок {COIN_NAME}\n"
                        f"У вас есть 5 минут на оформление отчёта."
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="РП Мероприятия",
                            style=disnake.ButtonStyle.secondary,
                            emoji=EMOJIS.get("RP"),
                            custom_id="type_rp",
                        ),
                        disnake.ui.Button(
                            label="Сдача оружия",
                            style=disnake.ButtonStyle.secondary,
                            emoji=EMOJIS.get("WEAPON"),
                            custom_id="type_weapons",
                        ),
                        disnake.ui.Button(
                            label="Казна",
                            style=disnake.ButtonStyle.secondary,
                            emoji=EMOJIS.get("TREASURY"),
                            custom_id="type_treasury",
                        ),
                    ),
                    accent_colour=ACCENT_COLOR,
                )
            ]
            await temp_channel.send(components=cont)
            inter.bot.loop.create_task(auto_delete_ticket(temp_channel, 300))
            await inter.followup.send(
                components=simple_container(
                    f"{e('SUCCESS')} Перейдите в {temp_channel.mention}",
                    SUCCESS_COLOR,
                ),
                ephemeral=True,
            )
            return

        if custom_id == "eco_shop":
            options = [
                disnake.SelectOption(
                    label="Снять выговор",
                    description=f"Стоимость: {SHOP_PRICES['WARN']} {COIN_SYMBOL}",
                    value="buy_warn",
                    emoji=e_btn("TIER"),
                ),
                disnake.SelectOption(
                    label="Игровая валюта",
                    description=f"Курс: 1 {COIN_SYMBOL} = {SHOP_PRICES['MONEY_RATE']}$",
                    value="buy_money",
                    emoji=e_btn("MONEY"),
                ),
                disnake.SelectOption(
                    label="Спец. предметы",
                    description="Индивидуальный заказ товаров",
                    value="buy_special",
                    emoji=e_btn("CART"),
                ),
            ]
            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"## {e('CART')} Магазин\n"
                        f"Укажите интересующий вас товар:"
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.StringSelect(
                            placeholder="Ознакомиться с ассортиментом…",
                            options=options,
                            custom_id="shop_select_menu",
                        )
                    ),
                    accent_colour=ACCENT_COLOR,
                )
            ]
            await inter.response.send_message(components=cont, ephemeral=True)
            return

        if custom_id == "type_rp":
            options = [
                disnake.SelectOption(
                    label=f"{k} (+{v} {COIN_SYMBOL})",
                    value=k,
                    emoji=e_btn("DOT"),
                )
                for k, v in RP_REWARDS.items()
            ]
            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"## {e('RP')} РП Мероприятия\n"
                        f"Укажите в меню ниже, в каком мероприятии вы участвовали:"
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.StringSelect(
                            placeholder="Сделайте выбор…",
                            options=options,
                            custom_id="earn_rp_select",
                        )
                    ),
                    accent_colour=ACCENT_COLOR,
                )
            ]
            await inter.response.edit_message(components=cont)
            return

        if custom_id == "type_weapons":
            ACTIVE_CARTS[inter.author.id] = {
                "cart": {k: 0 for k in WEAPON_REWARDS.keys()},
                "mult": 1,
            }
            await inter.response.edit_message(
                components=build_cart_container(inter.author.id)
            )
            return

        if custom_id == "type_treasury":
            ACTIVE_TREASURY[inter.author.id] = {
                "channel_id": inter.channel.id,
            }
            await inter.response.edit_message(
                components=build_treasury_action_container()
            )
            return

        if custom_id.startswith("cart_"):
            data = ACTIVE_CARTS.get(inter.author.id)
            if not data:
                return await inter.response.send_message(
                    components=simple_container(
                        f"{e('ERROR')} Сессия устарела. Начните заново.", ERROR_COLOR
                    ),
                    ephemeral=True,
                )
            action = custom_id.split(":")[0]

            if action == "cart_add":
                data["cart"][custom_id.split(":")[1]] += data["mult"]
                await inter.response.edit_message(
                    components=build_cart_container(inter.author.id)
                )
            elif action == "cart_mult":
                m = data["mult"]
                data["mult"] = (
                    2 if m == 1 else 3 if m == 2 else 5 if m == 3 else 10 if m == 5 else 1
                )
                await inter.response.edit_message(
                    components=build_cart_container(inter.author.id)
                )
            elif action == "cart_clear":
                data["cart"] = {k: 0 for k in WEAPON_REWARDS.keys()}
                await inter.response.edit_message(
                    components=build_cart_container(inter.author.id)
                )
            elif action == "cart_submit":
                total_lc = sum(
                    data["cart"][k] * WEAPON_REWARDS[k] for k in data["cart"]
                )
                if total_lc == 0:
                    return await inter.response.send_message(
                        components=simple_container(
                            f"{e('ERROR')} Корзина пуста!", ERROR_COLOR
                        ),
                        ephemeral=True,
                    )
                summary = ", ".join(
                    [f"{k} x{v}" for k, v in data["cart"].items() if v > 0]
                )
                await inter.response.send_modal(
                    EarnSubmitModal(
                        inter.author.id,
                        summary,
                        total_lc,
                        inter.message,
                        is_weapon=True,
                    )
                )
            return

        if custom_id == "ticket_submit":
            data = ACTIVE_TICKETS.get(inter.author.id)
            if not data:
                return await inter.response.send_message(
                    components=simple_container(
                        f"{e('ERROR')} Сессия истекла.", ERROR_COLOR
                    ),
                    ephemeral=True,
                )

            await inter.response.defer()
            files_to_upload: list[disnake.File] = []
            async for msg in inter.channel.history(limit=50):
                if msg.author.id == inter.author.id and msg.attachments:
                    for att in msg.attachments:
                        files_to_upload.append(await att.to_file())

            if not files_to_upload:
                return await inter.followup.send(
                    components=simple_container(
                        f"{e('ERROR')} Скриншоты не найдены. Сначала загрузите их в канал!",
                        ERROR_COLOR,
                    ),
                    ephemeral=True,
                )
            log_channel = inter.bot.get_channel(int(CHANNELS["EARN_LOGS"]))
            if not log_channel:
                return await inter.followup.send(
                    "Ошибка: Канал логов не найден.", ephemeral=True
                )

            desc = (
                f"**Отправил:** <@{inter.author.id}>\n"
                f"**Паспорт:** `{data['static_id']}`\n"
                f"**Действие:** Заработок ({data['detail_text']})\n"
                f"**Сумма:** `{data['reward']} {COIN_SYMBOL}`\n"
            )
            if data["comment"]:
                desc += f"**Причина:** {data['comment']}\n"

            btn_acc = f"earn_acc:{inter.author.id}:{data['reward']}"
            btn_rej = f"earn_rej:{inter.author.id}"

            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"## {e('REPORT')} Отчёт о транзакции\n" + desc
                    ),
                    disnake.ui.Separator(
                        divider=True, spacing=disnake.SeparatorSpacing.small
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="Одобрить",
                            style=disnake.ButtonStyle.success,
                            emoji="✅",
                            custom_id=btn_acc,
                        ),
                        disnake.ui.Button(
                            label="Отклонить",
                            style=disnake.ButtonStyle.danger,
                            emoji="❌",
                            custom_id=btn_rej,
                        ),
                    ),
                    accent_colour=MAIN_COLOR,
                )
            ]

            await log_channel.send(
                components=cont, files=files_to_upload[:MAX_TREASURY_FILES]
            )
            try:
                await inter.channel.delete()
            except Exception:
                pass
            if inter.author.id in ACTIVE_TICKETS:
                del ACTIVE_TICKETS[inter.author.id]
            return

        if custom_id == "ticket_cancel":
            try:
                await inter.channel.delete()
            except Exception:
                pass
            if inter.author.id in ACTIVE_TICKETS:
                del ACTIVE_TICKETS[inter.author.id]
            return

        # ----------- TREASURY: edit / cancel / submit -----------
        if custom_id == "treasury_edit":
            data = ACTIVE_TREASURY.get(inter.author.id)
            if not data or "action" not in data:
                return await inter.response.send_message(
                    components=simple_container(
                        f"{e('ERROR')} Сессия устарела. Начните заново.", ERROR_COLOR
                    ),
                    ephemeral=True,
                )
            await inter.response.send_modal(
                TreasurySubmitModal(inter.author.id, data["action"], inter.message)
            )
            return

        if custom_id == "treasury_cancel":
            try:
                await inter.channel.delete()
            except Exception:
                pass
            if inter.author.id in ACTIVE_TREASURY:
                del ACTIVE_TREASURY[inter.author.id]
            return

        if custom_id == "treasury_submit":
            data = ACTIVE_TREASURY.get(inter.author.id)
            if not data or "action" not in data or "amount" not in data:
                return await inter.response.send_message(
                    components=simple_container(
                        f"{e('ERROR')} Сначала выберите тип операции и заполните форму.",
                        ERROR_COLOR,
                    ),
                    ephemeral=True,
                )

            await inter.response.defer()
            files_to_upload: list[disnake.File] = []
            async for msg in inter.channel.history(limit=50):
                if msg.author.id == inter.author.id and msg.attachments:
                    for att in msg.attachments:
                        files_to_upload.append(await att.to_file())
                        if len(files_to_upload) >= MAX_TREASURY_FILES:
                            break
                if len(files_to_upload) >= MAX_TREASURY_FILES:
                    break

            if not files_to_upload:
                return await inter.followup.send(
                    components=simple_container(
                        f"{e('ERROR')} Доказательства не найдены. Прикрепите файлы и попробуйте снова.",
                        ERROR_COLOR,
                    ),
                    ephemeral=True,
                )

            log_channel = inter.bot.get_channel(int(CHANNELS["EARN_LOGS"]))
            if not log_channel:
                return await inter.followup.send(
                    "Ошибка: Канал логов не найден.", ephemeral=True
                )

            formatted_amount = format_amount(data["amount"])
            desc = (
                f"**Отправил:** <@{inter.author.id}>\n"
                f"**Паспорт:** `{data['static_id']}`\n"
                f"**Действие:** {data['action']}\n"
                f"**Сумма:** `{formatted_amount}`\n"
                f"**Причина:** {data['reason']}\n"
            )

            btn_acc = f"treasury_acc:{inter.author.id}:{data['amount']}"
            btn_rej = f"treasury_rej:{inter.author.id}"

            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"## {e('REPORT')} Отчёт о транзакции\n" + desc
                    ),
                    disnake.ui.Separator(
                        divider=True, spacing=disnake.SeparatorSpacing.small
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="Одобрить",
                            style=disnake.ButtonStyle.success,
                            emoji="✅",
                            custom_id=btn_acc,
                        ),
                        disnake.ui.Button(
                            label="Отклонить",
                            style=disnake.ButtonStyle.danger,
                            emoji="❌",
                            custom_id=btn_rej,
                        ),
                    ),
                    accent_colour=ACCENT_COLOR,
                )
            ]
            await log_channel.send(
                components=cont, files=files_to_upload[:MAX_TREASURY_FILES]
            )
            try:
                await inter.channel.delete()
            except Exception:
                pass
            if inter.author.id in ACTIVE_TREASURY:
                del ACTIVE_TREASURY[inter.author.id]
            return

        # ----------- SHOP confirm / cancel -----------
        if custom_id == "shop_confirm":
            data = ACTIVE_ORDERS.get(inter.author.id)
            if not data:
                return await inter.response.edit_message(
                    components=simple_container(
                        f"{e('ERROR')} Сессия истекла.", ERROR_COLOR
                    )
                )

            formatted_money = f"{data['money']:,}".replace(",", ".")
            desc = (
                f"**Отправил:** <@{inter.author.id}>\n"
                f"**Паспорт:** `{data['static']}`\n"
                f"**Действие:** Обмен на игровую валюту\n"
                f"**Сумма:** `{data['coins']} {COIN_SYMBOL}` "
                f"(К выдаче: {formatted_money}$)\n"
            )

            cont = [
                disnake.ui.Container(
                    disnake.ui.TextDisplay(
                        f"## {e('CART')} Отчёт о транзакции\n" + desc
                    ),
                    disnake.ui.Separator(
                        divider=True, spacing=disnake.SeparatorSpacing.small
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="Одобрить",
                            style=disnake.ButtonStyle.success,
                            emoji="✅",
                            custom_id=f"shop_acc:{inter.author.id}:{data['coins']}",
                        ),
                        disnake.ui.Button(
                            label="Отклонить",
                            style=disnake.ButtonStyle.danger,
                            emoji="❌",
                            custom_id=f"shop_rej:{inter.author.id}",
                        ),
                    ),
                    accent_colour=MAIN_COLOR,
                )
            ]
            log_channel = inter.bot.get_channel(int(CHANNELS["SHOP_LOGS"]))
            if log_channel:
                await log_channel.send(components=cont)

            await inter.response.edit_message(
                components=simple_container(
                    f"{e('SUCCESS')} Заявка отправлена! "
                    f"Ожидайте `{formatted_money}$`.",
                    SUCCESS_COLOR,
                )
            )
            if inter.author.id in ACTIVE_ORDERS:
                del ACTIVE_ORDERS[inter.author.id]
            return

        if custom_id == "shop_cancel":
            await inter.response.edit_message(
                components=simple_container(
                    f"{e('REJECT')} Обмен отменён.", ERROR_COLOR
                )
            )
            if inter.author.id in ACTIVE_ORDERS:
                del ACTIVE_ORDERS[inter.author.id]
            return

        # ----------- MODERATION (earn / shop / treasury) -----------
        if custom_id.startswith("earn_acc:"):
            if not is_moderator(inter.author):
                return
            parts = custom_id.split(":")
            user_id, reward = int(parts[1]), int(parts[2])

            await inter.response.defer(ephemeral=True)
            async with aiosqlite.connect("data/database.sqlite") as db:
                await db.execute(
                    "INSERT INTO user_coins (user_id, balance) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
                    (str(user_id), reward, reward),
                )
                await db.commit()

            mod_name = (
                getattr(inter.author, "display_name", None) or inter.author.name
            )
            new_cont = resolve_report_status(
                inter.message.components[0],
                is_approved=True,
                mod_id=inter.author.id,
                mod_name=mod_name,
                keep_status_buttons=True,
            )
            await inter.message.edit(components=new_cont)
            await inter.followup.send(
                components=simple_container(
                    f"{e('SUCCESS')} Средства успешно начислены.", SUCCESS_COLOR
                ),
                ephemeral=True,
            )
            return

        if custom_id.startswith("earn_rej:"):
            if not is_moderator(inter.author):
                return
            user_id = int(custom_id.split(":")[1])
            await inter.response.send_modal(
                RejectEarnModal(user_id, inter.message, inter.message.components[0])
            )
            return

        if custom_id.startswith("treasury_acc:"):
            if not is_moderator(inter.author):
                return
            parts = custom_id.split(":")
            user_id = int(parts[1])
            await inter.response.defer(ephemeral=True)

            mod_name = (
                getattr(inter.author, "display_name", None) or inter.author.name
            )
            new_cont = resolve_report_status(
                inter.message.components[0],
                is_approved=True,
                mod_id=inter.author.id,
                mod_name=mod_name,
                keep_status_buttons=True,
            )
            await inter.message.edit(components=new_cont)

            target_member = (
                inter.guild.get_member(user_id) if inter.guild else None
            )
            if target_member:
                try:
                    await target_member.send(
                        components=simple_container(
                            f"## {e('TREASURY')} Отчёт казны одобрен\n"
                            f"Ваш отчёт по операции казны был одобрен модератором "
                            f"{inter.author.mention}.",
                            SUCCESS_COLOR,
                        )
                    )
                except Exception:
                    pass

            await inter.followup.send(
                components=simple_container(
                    f"{e('SUCCESS')} Отчёт казны одобрен.", SUCCESS_COLOR
                ),
                ephemeral=True,
            )
            return

        if custom_id.startswith("treasury_rej:"):
            if not is_moderator(inter.author):
                return
            user_id = int(custom_id.split(":")[1])
            await inter.response.send_modal(
                RejectTreasuryModal(
                    user_id, inter.message, inter.message.components[0]
                )
            )
            return

        if custom_id.startswith("shop_acc:"):
            if not is_moderator(inter.author):
                return
            parts = custom_id.split(":")
            user_id, price = int(parts[1]), int(parts[2])

            await inter.response.defer(ephemeral=True)
            async with aiosqlite.connect("data/database.sqlite") as db:
                async with db.execute(
                    "SELECT balance FROM user_coins WHERE user_id = ?",
                    (str(user_id),),
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row or row[0] < price:
                        return await inter.followup.send(
                            components=simple_container(
                                f"{e('ERROR')} Недостаточно средств у пользователя!",
                                ERROR_COLOR,
                            ),
                            ephemeral=True,
                        )
                await db.execute(
                    "UPDATE user_coins SET balance = balance - ? WHERE user_id = ?",
                    (price, str(user_id)),
                )
                await db.commit()

            mod_name = (
                getattr(inter.author, "display_name", None) or inter.author.name
            )
            new_cont = resolve_report_status(
                inter.message.components[0],
                is_approved=True,
                mod_id=inter.author.id,
                mod_name=mod_name,
                keep_status_buttons=True,
            )
            await inter.message.edit(components=new_cont)
            await inter.followup.send(
                components=simple_container(
                    f"{e('SUCCESS')} Заказ закрыт и оплачен.", SUCCESS_COLOR
                ),
                ephemeral=True,
            )
            return

        if custom_id.startswith("shop_acc_spec:"):
            if not is_moderator(inter.author):
                return
            user_id = int(custom_id.split(":")[1])
            await inter.response.send_modal(
                AcceptSpecialModal(
                    user_id, inter.message, inter.message.components[0]
                )
            )
            return

        if custom_id.startswith("shop_rej:"):
            if not is_moderator(inter.author):
                return
            user_id = int(custom_id.split(":")[1])
            await inter.response.send_modal(
                RejectOrderModal(
                    user_id, inter.message, inter.message.components[0]
                )
            )
            return

    @commands.command(name="setup_economy")
    @commands.has_permissions(administrator=True)
    async def setup_eco_panel(self, ctx):
        await ctx.send(components=build_economy_panel())
        try:
            await ctx.message.delete()
        except Exception:
            pass

    @commands.slash_command(name="coins")
    async def coins_base(self, inter):
        pass

    @coins_base.sub_command(
        name="add", description=f"[АДМИН] Выдать {COIN_SYMBOL} игроку"
    )
    async def coins_add(self, inter, user: disnake.Member, amount: int):
        if not is_moderator(inter.author):
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('REJECT')} Доступ закрыт.", ERROR_COLOR
                ),
                ephemeral=True,
            )
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "INSERT INTO user_coins (user_id, balance) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?",
                (str(user.id), amount, amount),
            )
            await db.commit()
        await inter.response.send_message(
            components=simple_container(
                f"## {e('MONEY')} Пополнение\n"
                f"Баланс {user.mention} пополнен на `{amount} {COIN_SYMBOL}`.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @coins_base.sub_command(
        name="remove", description=f"[АДМИН] Списать {COIN_SYMBOL} у игрока"
    )
    async def coins_remove(self, inter, user: disnake.Member, amount: int):
        if not is_moderator(inter.author):
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('REJECT')} Доступ закрыт.", ERROR_COLOR
                ),
                ephemeral=True,
            )
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "UPDATE user_coins SET balance = MAX(0, balance - ?) WHERE user_id = ?",
                (amount, str(user.id)),
            )
            await db.commit()
        await inter.response.send_message(
            components=simple_container(
                f"## {e('TRASH')} Списание\n"
                f"У {user.mention} списано `{amount} {COIN_SYMBOL}`.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @coins_base.sub_command(
        name="mass_remove",
        description=f"[ВЛАДЕЛЕЦ] Отнять процент {COIN_SYMBOL} у всех",
    )
    async def coins_mass_remove(self, inter, percent: int):
        if inter.author.id != OWNER_ID:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('REJECT')} Доступ запрещён.", ERROR_COLOR
                ),
                ephemeral=True,
            )
        if percent <= 0 or percent > 100:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('ERROR')} Укажите от 1 до 100.", ERROR_COLOR
                ),
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)
        multiplier = (100 - percent) / 100.0
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "UPDATE user_coins SET balance = CAST(balance * ? AS INTEGER)",
                (multiplier,),
            )
            await db.commit()
        await inter.followup.send(
            components=simple_container(
                f"## {e('SUCCESS')} Массовое списание\n"
                f"Экономика порезана: у всех списано **{percent}%**.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @coins_base.sub_command(
        name="mass_boost",
        description=f"[ВЛАДЕЛЕЦ] Умножить {COIN_SYMBOL} всех игроков",
    )
    async def coins_mass_boost(
        self,
        inter: disnake.ApplicationCommandInteraction,
        multiplier: str = commands.Param(
            choices={
                "+50% (x1.5)": "1.5",
                "Удвоить (x2)": "2.0",
                "Утроить (x3)": "3.0",
                "Умножить на 5 (x5)": "5.0",
                "Умножить на 10 (x10)": "10.0",
            }
        ),
    ):
        if inter.author.id != OWNER_ID:
            return await inter.response.send_message(
                components=simple_container(
                    f"{e('REJECT')} Доступ запрещён.", ERROR_COLOR
                ),
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)
        mult_float = float(multiplier)
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "UPDATE user_coins SET balance = CAST(balance * ? AS INTEGER)",
                (mult_float,),
            )
            await db.commit()
        await inter.followup.send(
            components=simple_container(
                f"## {e('SUCCESS')} Буст экономики\n"
                f"Баланс всех умножен на **x{mult_float}**!",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @coins_base.sub_command(name="balance", description="Посмотреть баланс")
    async def coins_balance(self, inter, user: disnake.Member = None):
        target = user or inter.author
        balance = await get_user_balance(target.id)
        await inter.response.send_message(
            components=simple_container(
                f"## {e('CARD')} Текущий баланс\n"
                f"Счёт {target.mention}: **{balance} {COIN_SYMBOL}**",
                ACCENT_COLOR,
            ),
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(EconomyCog(bot))
