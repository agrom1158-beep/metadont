from __future__ import annotations

import datetime
import json

import aiosqlite
import disnake
from disnake.ext import commands

# Подгружаем настройки
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# Константы для дизайна
INVISIBLE_COLOR = 0x2B2D31
SKY_BLUE = 0x87CEEB  # «небесно-голубой» акцент Container'а панели заявок

# Persistent custom ids
APPLICATION_SELECT_CID = "application_action_select"
APPLICATION_OPTION_CREATE = "create_app"


# ==========================================
# ПОМОЩНИКИ ДЛЯ ЭМОДЗИ
# ==========================================
def e(key: str) -> str:
    """Для текста: возвращает эмодзи с пробелом или пустоту, если эмодзи нет."""
    val = config.get("EMOJIS", {}).get(key, "")
    return f"{val} " if val else ""


def e_btn(key: str):
    """Для кнопок/меню: возвращает эмодзи или None, если эмодзи нет."""
    val = config.get("EMOJIS", {}).get(key, "")
    return val if val else None


def get_safe_logo() -> str:
    logo = config.get("IMAGES", {}).get("LOGO", "").strip()
    if logo.startswith("Https"):
        logo = logo.replace("Https", "https")
    return logo


def get_safe_banner() -> str:
    banner = config.get("IMAGES", {}).get("APPLICATIONS_BANNER", "").strip()
    if banner.startswith("Https"):
        banner = banner.replace("Https", "https")
    return banner


# ==========================================
# COMPONENTS V2: ПАНЕЛЬ "ЗАЯВКИ В СЕМЬЮ"
# ==========================================
def build_application_panel() -> list[disnake.ui.Container]:
    """Сборка стартовой панели заявок одним Container'ом (Components V2).

    Содержит баннер, описание, разделители, подсказки и встроенный
    StringSelect — рендерится единым блоком, как на новом UI Discord.
    """
    banner_url = get_safe_banner()
    children: list = []

    if banner_url:
        children.append(
            disnake.ui.MediaGallery(disnake.MediaGalleryItem(banner_url))
        )

    title_icon = e("SHIELD") or e("WAVE") or ""
    children.append(
        disnake.ui.TextDisplay(
            f"## {title_icon}Оформление заявки в семью.\n"
            "Уведомление о приглашении на обзвон отправляется в личные сообщения.\n"
            "Заявки открыты только на 16 сервер Denver"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "> В среднем заявки обрабатываются в течение 1-2 дней"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "Следите за статусом набора.\n"
            "**Если возможности заполнить заявку нет – набор закрыт.**\n"
            "**Каждое открытие набора сопровождается тегами в этом канале.**"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "> В случае отказа можете подать заявку повторно через 7 дней"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(disnake.ui.TextDisplay("**Подать заявку:**"))

    select = disnake.ui.StringSelect(
        custom_id=APPLICATION_SELECT_CID,
        placeholder="Подать заявку в семью",
        min_values=1,
        max_values=1,
        options=[
            disnake.SelectOption(
                label="Подать заявку в семью",
                description="Откроет форму для заполнения",
                value=APPLICATION_OPTION_CREATE,
                emoji=e_btn("FORM"),
            )
        ],
    )
    children.append(disnake.ui.ActionRow(select))

    return [
        disnake.ui.Container(
            *children, accent_colour=disnake.Colour(SKY_BLUE)
        )
    ]


# ==========================================
# МОДАЛКИ ЗАЯВКИ / ПРИНЯТИЯ / ОТКЛОНЕНИЯ
# ==========================================
class ApplicationModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Ник в игре, Ваш возраст",
                placeholder="Андрей, 20 лет",
                custom_id="name_age",
                style=disnake.TextInputStyle.short,
                max_length=50,
            ),
            disnake.ui.TextInput(
                label="Ваш статический ID",
                placeholder="1488",
                custom_id="static_id",
                style=disnake.TextInputStyle.short,
                max_length=20,
            ),
            disnake.ui.TextInput(
                label="Откаты стрельбы гг/mcl/vzz/capt",
                placeholder="Откат с сайги/тяжки",
                custom_id="reels",
                style=disnake.TextInputStyle.paragraph,
            ),
            disnake.ui.TextInput(
                label="В каких семьях Вы состояли, почему покинули?",
                placeholder="Семья: River, дисбанд",
                custom_id="history",
                style=disnake.TextInputStyle.paragraph,
            ),
            disnake.ui.TextInput(
                label="Как давно на проекте и какой средний онлайн?",
                placeholder="На проекте с 24 года, начинал с Houston...",
                custom_id="online",
                style=disnake.TextInputStyle.paragraph,
            ),
        ]
        super().__init__(title="Подать заявку в семью", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        category = inter.guild.get_channel(
            int(config["CHANNELS"]["APPLICATION_REVIEW"])
        )
        ticket_channel = await inter.guild.create_text_channel(
            name=f"заявка-{inter.author.name}",
            category=category,
            topic=str(inter.author.id),
        )

        await ticket_channel.set_permissions(
            inter.guild.default_role, read_messages=False
        )
        await ticket_channel.set_permissions(
            inter.author,
            read_messages=True,
            send_messages=True,
            attach_files=True,
        )

        for r_id in config["ROLES"]["MODERATOR"]:
            mod_role = inter.guild.get_role(int(r_id))
            if mod_role:
                await ticket_channel.set_permissions(
                    mod_role, read_messages=True, send_messages=True
                )

        desc = "**Новая заявка**\n\n"
        desc += f"**От:**\n{inter.author.mention}\n\n"
        desc += f"**Ник и Возраст**\n{inter.text_values['name_age']}\n\n"
        desc += f"**Статический ID**\n{inter.text_values['static_id']}\n\n"
        desc += f"**Откаты стрельбы**\n{inter.text_values['reels']}\n\n"
        desc += f"**История семей**\n{inter.text_values['history']}\n\n"
        desc += f"**Опыт и онлайн**\n{inter.text_values['online']}"

        embed = disnake.Embed(description=desc, color=disnake.Color.orange())

        view = disnake.ui.View(timeout=None)
        view.add_item(
            disnake.ui.Button(
                label="Принять",
                emoji=e_btn("SUCCESS"),
                style=disnake.ButtonStyle.success,
                custom_id=f"accept_{inter.author.id}",
            )
        )
        view.add_item(
            disnake.ui.Button(
                label="Отклонить",
                emoji=e_btn("REJECT"),
                style=disnake.ButtonStyle.danger,
                custom_id=f"reject_{inter.author.id}",
            )
        )
        view.add_item(
            disnake.ui.Button(
                label="Обзвон",
                emoji=e_btn("CALL"),
                style=disnake.ButtonStyle.secondary,
                custom_id=f"call_{inter.author.id}",
            )
        )

        mentions = " ".join(
            [f"<@&{r}>" for r in config["ROLES"]["MODERATOR"]]
        )
        msg = await ticket_channel.send(
            content=f"{mentions}\nНовая заявка от {inter.author.mention}",
            embed=embed,
            view=view,
        )

        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "INSERT INTO applications (user_id, message_id, status) VALUES (?, ?, ?)",
                (str(inter.author.id), str(msg.id), "pending"),
            )
            await db.commit()

        await inter.followup.send(
            f"{e('SUCCESS')}Ваша заявка успешно отправлена: {ticket_channel.mention}",
            ephemeral=True,
        )


class AcceptModal(disnake.ui.Modal):
    def __init__(self, target_user_id: str, message_id: str):
        self.target_user_id = target_user_id
        self.message_id = message_id
        components = [
            disnake.ui.TextInput(
                label="Введите новый ник",
                custom_id="new_nickname",
                style=disnake.TextInputStyle.short,
            )
        ]
        super().__init__(title="Смена никнейма", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        target_id = int(self.target_user_id)

        member = inter.guild.get_member(target_id)
        if not member:
            try:
                member = await inter.guild.fetch_member(target_id)
            except Exception:
                pass

        new_nickname = inter.text_values["new_nickname"]
        nick_status = f"{e('WARNING')}Игрок не найден"
        role_status = f"{e('WARNING')}Игрок не найден"

        if member:
            try:
                await member.edit(nick=new_nickname)
                nick_status = f"{e('SUCCESS')}Изменен на `{new_nickname}`"
            except disnake.Forbidden:
                nick_status = (
                    f"{e('WARNING')}Не хватает прав (роль бота ниже игрока)"
                )
            except Exception:
                nick_status = f"{e('WARNING')}Ошибка"

            try:
                roles_to_add = []

                for specific_role_id in config.get("ROLES", {}).get(
                    "FAMILY_ROLES", []
                ):
                    role = inter.guild.get_role(int(specific_role_id))
                    if role:
                        roles_to_add.append(role)

                for r_id in config.get("ROLES", {}).get("STAFF", []):
                    role = inter.guild.get_role(int(r_id))
                    if role and role not in roles_to_add:
                        roles_to_add.append(role)

                academy_role_id = config.get("ACADEMY", {}).get(
                    "RANK_ACADEMY"
                )
                if academy_role_id:
                    acad_role = inter.guild.get_role(int(academy_role_id))
                    if acad_role and acad_role not in roles_to_add:
                        roles_to_add.append(acad_role)

                if roles_to_add:
                    await member.add_roles(*roles_to_add)
                    role_status = f"{e('SUCCESS')}Выданы успешно"
                else:
                    role_status = (
                        f"{e('WARNING')}Роли не найдены на сервере/конфиге"
                    )
            except disnake.Forbidden:
                role_status = (
                    f"{e('WARNING')}Нет прав (поднимите роль бота выше)"
                )
            except Exception:
                role_status = f"{e('WARNING')}Неизвестная ошибка"

            try:
                academy_panel_id = config.get("ACADEMY", {}).get(
                    "PANEL_CHANNEL"
                )
                desc_text = (
                    f"Добро пожаловать в семью **Trappa Famq**!\n"
                    f"Вам выдана роль Академии.\n\n"
                    f"**{e('FIRE')}Что делать дальше?**\n"
                    f"Обязательно перейдите в канал <#{academy_panel_id}> "
                    f"и нажмите кнопку **«Начать прохождение»**, чтобы бот "
                    f"создал вам личную ветку и выдал список заданий для повышения."
                )

                dm_embed = disnake.Embed(
                    title=f"{e('PARTY')}Ваша заявка ОДОБРЕНА!",
                    description=desc_text,
                    color=disnake.Color.green(),
                )
                logo = get_safe_logo()
                if logo:
                    dm_embed.set_thumbnail(url=logo)
                await member.send(embed=dm_embed)
            except Exception:
                pass

        is_farm = False
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT candidate_id FROM rewarded_candidates WHERE candidate_id = ?",
                (str(self.target_user_id),),
            ) as cursor:
                if await cursor.fetchone():
                    is_farm = True

            if not is_farm:
                await db.execute(
                    "INSERT INTO user_coins (user_id, balance) VALUES (?, 5) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + 5",
                    (str(inter.author.id),),
                )
                await db.execute(
                    "INSERT INTO rewarded_candidates (candidate_id) VALUES (?)",
                    (str(self.target_user_id),),
                )

            await db.execute(
                "UPDATE applications SET status = ? WHERE message_id = ?",
                ("accepted", self.message_id),
            )
            await db.commit()

        app_embed = None
        try:
            msg = await inter.channel.fetch_message(int(self.message_id))
            if msg.embeds:
                app_embed = msg.embeds[0]
        except Exception:
            pass

        global_logs_channel_id = int(
            config.get("CHANNELS", {}).get(
                "GLOBAL_LOGS_CHANNEL", 1482857963428516010
            )
        )
        global_channel = inter.bot.get_channel(global_logs_channel_id)
        if not global_channel:
            try:
                global_channel = await inter.bot.fetch_channel(
                    global_logs_channel_id
                )
            except Exception:
                pass

        if global_channel:
            global_embed = disnake.Embed(
                title=f"{e('LOGS')}Глобальный лог: Одобрение",
                color=disnake.Color.green(),
                timestamp=datetime.datetime.now(),
            )
            global_embed.add_field(
                name="Кандидат",
                value=f"<@{self.target_user_id}>",
                inline=True,
            )
            global_embed.add_field(
                name="Проверил", value=inter.author.mention, inline=True
            )

            reward_amount = 0 if is_farm else 10
            global_embed.add_field(
                name="Награда модератора",
                value=f"`{reward_amount} TC`",
                inline=True,
            )

            global_embed.add_field(
                name="Смена ника", value=nick_status, inline=True
            )
            global_embed.add_field(
                name="Выдача ролей", value=role_status, inline=True
            )
            global_embed.add_field(
                name="Был в семье?",
                value=f"{e('SUCCESS')}Да (Анти-Абуз)"
                if is_farm
                else f"{e('ERROR')}Нет",
                inline=True,
            )

            join_date = (
                f"<t:{int(member.joined_at.timestamp())}:D>"
                if member and member.joined_at
                else "Неизвестно"
            )
            global_embed.add_field(
                name="Зашел на сервер", value=join_date, inline=True
            )

            if app_embed and app_embed.description:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_embed.description}"
                )

            await global_channel.send(embed=global_embed)

        await inter.channel.delete(reason="Заявка принята")


class RejectModal(disnake.ui.Modal):
    def __init__(self, target_user_id: str, message_id: str):
        self.target_user_id = target_user_id
        self.message_id = message_id
        components = [
            disnake.ui.TextInput(
                label="Причина отказа",
                placeholder="Слабые откаты, не подходит по возрасту...",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
            )
        ]
        super().__init__(title="Отклонение заявки", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        reason = inter.text_values["reason"]

        formatted_reason = "\n".join(
            [f"> {line}" for line in reason.split("\n")]
        )

        target_id = int(self.target_user_id)
        member = inter.guild.get_member(target_id)
        if not member:
            try:
                member = await inter.guild.fetch_member(target_id)
            except Exception:
                pass

        if member:
            try:
                dm_embed = disnake.Embed(
                    description="К сожалению, ваша заявка была **отклонена**.",
                    color=INVISIBLE_COLOR,
                )
                dm_embed.add_field(name="Причина:", value=formatted_reason)
                logo = get_safe_logo()
                if logo:
                    dm_embed.set_thumbnail(url=logo)
                await member.send(embed=dm_embed)
            except Exception:
                pass

        is_farm = False
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT candidate_id FROM rewarded_candidates WHERE candidate_id = ?",
                (str(self.target_user_id),),
            ) as cursor:
                if await cursor.fetchone():
                    is_farm = True

            if not is_farm:
                await db.execute(
                    "INSERT INTO user_coins (user_id, balance) VALUES (?, 3) "
                    "ON CONFLICT(user_id) DO UPDATE SET balance = balance + 3",
                    (str(inter.author.id),),
                )
                await db.execute(
                    "INSERT INTO rewarded_candidates (candidate_id) VALUES (?)",
                    (str(self.target_user_id),),
                )

            await db.execute(
                "UPDATE applications SET status = ? WHERE message_id = ?",
                ("rejected", self.message_id),
            )
            await db.commit()

        app_embed = None
        try:
            msg = await inter.channel.fetch_message(int(self.message_id))
            if msg.embeds:
                app_embed = msg.embeds[0]
        except Exception:
            pass

        results_channel_id = int(
            config.get("CHANNELS", {}).get(
                "RESULTS_CHANNEL", 1463104920268836999
            )
        )
        log_channel = inter.bot.get_channel(results_channel_id)
        if not log_channel:
            try:
                log_channel = await inter.bot.fetch_channel(
                    results_channel_id
                )
            except Exception:
                pass

        if log_channel:
            desc = (
                f"Заявка от пользователя <@{self.target_user_id}>\n\n"
                f"<:red:1486616915186159636>На вступление в семью была "
                f"**отклонена**\n\n"
                f"**Причина:**\n"
                f"{formatted_reason}\n\n"
                f"Рассматривал заявку: {inter.author.mention}"
            )
            log_embed = disnake.Embed(
                title="Заявка отклонена",
                description=desc,
                color=disnake.Color.red(),
            )

            if member and getattr(member, "display_avatar", None):
                log_embed.set_thumbnail(url=member.display_avatar.url)
            elif get_safe_logo():
                log_embed.set_thumbnail(url=get_safe_logo())

            if get_safe_logo():
                log_embed.set_footer(
                    text="Trappa Famq", icon_url=get_safe_logo()
                )
            else:
                log_embed.set_footer(text="Trappa Famq")

            await log_channel.send(embed=log_embed)

        global_logs_channel_id = int(
            config.get("CHANNELS", {}).get(
                "GLOBAL_LOGS_CHANNEL", 1482857963428516010
            )
        )
        global_channel = inter.bot.get_channel(global_logs_channel_id)
        if not global_channel:
            try:
                global_channel = await inter.bot.fetch_channel(
                    global_logs_channel_id
                )
            except Exception:
                pass

        if global_channel:
            global_embed = disnake.Embed(
                title=f"{e('LOGS')}Глобальный лог: Отклонение",
                color=disnake.Color.red(),
                timestamp=datetime.datetime.now(),
            )
            global_embed.add_field(
                name="Кандидат",
                value=f"<@{self.target_user_id}>",
                inline=True,
            )
            global_embed.add_field(
                name="Проверил", value=inter.author.mention, inline=True
            )
            global_embed.add_field(
                name="Причина", value=f"{formatted_reason}", inline=True
            )

            reward_amount = 0 if is_farm else 3
            global_embed.add_field(
                name="Награда модератора",
                value=f"`{reward_amount} TC`",
                inline=True,
            )
            global_embed.add_field(
                name="Был в семье?",
                value=f"{e('SUCCESS')}Да (Анти-Абуз)"
                if is_farm
                else f"{e('ERROR')}Нет",
                inline=True,
            )

            join_date = (
                f"<t:{int(member.joined_at.timestamp())}:D>"
                if member and member.joined_at
                else "Неизвестно"
            )
            global_embed.add_field(
                name="Зашел на сервер", value=join_date, inline=True
            )

            if app_embed and app_embed.description:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_embed.description}"
                )

            await global_channel.send(embed=global_embed)

        await inter.channel.delete(reason="Заявка отклонена")


# ==========================================
# COG
# ==========================================
class ApplicationsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS applications "
                "(user_id TEXT, message_id TEXT, status TEXT)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS rewarded_candidates "
                "(candidate_id TEXT PRIMARY KEY)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_coins "
                "(user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 0)"
            )
            await db.commit()

    @commands.Cog.listener()
    async def on_dropdown(self, inter: disnake.MessageInteraction):
        """Обработчик встроенного селекта в Components V2 панели."""
        if inter.component.custom_id != APPLICATION_SELECT_CID:
            return
        if not inter.values or inter.values[0] != APPLICATION_OPTION_CREATE:
            return

        category = inter.guild.get_channel(
            int(config["CHANNELS"]["APPLICATION_REVIEW"])
        )
        if category and isinstance(category, disnake.CategoryChannel):
            for ch in category.text_channels:
                if str(inter.author.id) in (ch.topic or ""):
                    return await inter.response.send_message(
                        f"У вас уже открыта заявка: {ch.mention}",
                        ephemeral=True,
                    )

        await inter.response.send_modal(ApplicationModal())

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        custom_id = inter.component.custom_id
        if not custom_id:
            return

        if custom_id.startswith(("accept_", "reject_", "call_")):
            moderator_roles = config.get("ROLES", {}).get("MODERATOR", [])
            is_mod = any(
                r.id in moderator_roles for r in inter.author.roles
            )
            if not is_mod and not inter.author.guild_permissions.administrator:
                return await inter.response.send_message(
                    f"{e('REJECT')}У вас нет прав.", ephemeral=True
                )

        if custom_id.startswith("accept_"):
            await inter.response.send_modal(
                AcceptModal(custom_id.split("_")[1], str(inter.message.id))
            )

        elif custom_id.startswith("reject_"):
            await inter.response.send_modal(
                RejectModal(custom_id.split("_")[1], str(inter.message.id))
            )

        elif custom_id.startswith("call_"):
            await inter.response.defer(ephemeral=True)
            user_id = custom_id.split("_")[1]
            message_id = str(inter.message.id)

            channel_id = 1463605913117134900

            async with aiosqlite.connect("data/database.sqlite") as db:
                await db.execute(
                    "UPDATE applications SET status = ? WHERE user_id = ?",
                    ("interview", user_id),
                )
                await db.commit()

            member = inter.guild.get_member(int(user_id))
            if not member:
                try:
                    member = await inter.guild.fetch_member(int(user_id))
                except Exception:
                    pass

            if member:
                try:
                    await inter.channel.edit(name=f"обзвон-{member.name}")
                except Exception:
                    pass
                try:
                    dm_embed = disnake.Embed(
                        description=(
                            f"Ваша заявка находится на рассмотрении.\n\n"
                            f"Свяжитесь со мной, если готовы пройти обзвон — "
                            f"{inter.author.mention}"
                        ),
                        color=INVISIBLE_COLOR,
                    )
                    logo = get_safe_logo()
                    if logo:
                        dm_embed.set_thumbnail(url=logo)
                    await member.send(embed=dm_embed)
                except Exception:
                    pass

            try:
                msg = await inter.channel.fetch_message(int(message_id))
                embed = msg.embeds[0]
                embed.color = disnake.Color.orange()
                embed.set_footer(
                    text=f"Переведено на обзвон: {inter.author.display_name}"
                )
                view = disnake.ui.View(timeout=None)
                view.add_item(
                    disnake.ui.Button(
                        label="Принять",
                        emoji=e_btn("SUCCESS"),
                        style=disnake.ButtonStyle.success,
                        custom_id=f"accept_{user_id}",
                    )
                )
                view.add_item(
                    disnake.ui.Button(
                        label="Отклонить",
                        emoji=e_btn("REJECT"),
                        style=disnake.ButtonStyle.danger,
                        custom_id=f"reject_{user_id}",
                    )
                )
                await msg.edit(embed=embed, view=view)
            except Exception:
                pass

            results_channel_id = int(
                config.get("CHANNELS", {}).get(
                    "RESULTS_CHANNEL", 1463104920268836999
                )
            )
            res_channel = inter.bot.get_channel(results_channel_id)
            if not res_channel:
                try:
                    res_channel = await inter.bot.fetch_channel(
                        results_channel_id
                    )
                except Exception:
                    pass

            if res_channel:
                desc = (
                    f"Заявка от пользователя <@{user_id}>\n\n"
                    f"<:green:1486608277046562926>На вступление в семью была "
                    f"рассмотрена!\n\n"
                    f"Для прохода обзвона ожидаем вас в канале:\n"
                    f"<a:strelka1:1485470220905746654> <#{channel_id}>\n\n"
                    f"Рассматривал заявку: {inter.author.mention}"
                )
                call_res_embed = disnake.Embed(
                    description=desc, color=disnake.Color.green()
                )

                if member and getattr(member, "display_avatar", None):
                    call_res_embed.set_thumbnail(
                        url=member.display_avatar.url
                    )
                elif get_safe_logo():
                    call_res_embed.set_thumbnail(url=get_safe_logo())

                if get_safe_logo():
                    call_res_embed.set_footer(
                        text="Trappa Famq", icon_url=get_safe_logo()
                    )
                else:
                    call_res_embed.set_footer(text="Trappa Famq")

                await res_channel.send(embed=call_res_embed)

            global_logs_channel_id = int(
                config.get("CHANNELS", {}).get(
                    "GLOBAL_LOGS_CHANNEL", 1482857963428516010
                )
            )
            global_channel = inter.bot.get_channel(global_logs_channel_id)
            if not global_channel:
                try:
                    global_channel = await inter.bot.fetch_channel(
                        global_logs_channel_id
                    )
                except Exception:
                    pass

            if global_channel:
                call_log = disnake.Embed(
                    title=f"{e('CALL')}Глобальный лог: Перевод на обзвон",
                    color=disnake.Color.orange(),
                    timestamp=datetime.datetime.now(),
                )
                call_log.add_field(
                    name="Кандидат", value=f"<@{user_id}>", inline=True
                )
                call_log.add_field(
                    name="Модератор", value=inter.author.mention, inline=True
                )
                call_log.add_field(
                    name="Канал", value=f"<#{channel_id}>", inline=True
                )
                await global_channel.send(embed=call_log)

            await inter.channel.send(
                f"{e('CALL')}<@{user_id}>, модератор {inter.author.mention} "
                f"готов! Зайдите в <#{channel_id}>"
            )
            await inter.followup.send(
                f"{e('SUCCESS')}Кандидат вызван.", ephemeral=True
            )

    @commands.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def setup_panel(self, ctx):
        """Постит Components V2 панель заявок в текущий канал."""
        components = build_application_panel()
        await ctx.send(components=components)
        try:
            await ctx.message.delete()
        except Exception:
            pass


def setup(bot):
    bot.add_cog(ApplicationsCog(bot))
