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
ACCENT_COLOR = disnake.Colour(SKY_BLUE)
SUCCESS_COLOR = disnake.Colour(0x2E8B57)
ERROR_COLOR = disnake.Colour(0xED4245)
ORANGE_COLOR = disnake.Colour(0xE67E22)

# Максимум фото персонажей, которые можно прикрепить к заявке
MAX_APPLICATION_FILES = 10

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
# ХЕЛПЕРЫ ДЛЯ COMPONENTS V2
# ==========================================
def simple_container(
    text: str, color: disnake.Colour = ACCENT_COLOR
) -> list[disnake.ui.Container]:
    return [
        disnake.ui.Container(
            disnake.ui.TextDisplay(text), accent_colour=color
        )
    ]


def _to_ui_container(container) -> disnake.ui.Container:
    """Гарантирует, что контейнер — disnake.ui.Container.

    ``inter.message.components[0]`` возвращает ``disnake.components.Container``,
    у которого children — тоже типа ``disnake.components.X``. Чтобы isinstance
    проверки на ``disnake.ui.X`` работали, конвертируем.
    """
    if isinstance(container, disnake.ui.Container):
        return container
    return disnake.ui.Container.from_component(container)


def _file_upload_label(
    label: str = "Фото персонажей",
    required: bool = True,
    max_files: int = MAX_APPLICATION_FILES,
) -> disnake.ui.Label:
    """Готовый Label с FileUpload (1–max_files файлов)."""
    return disnake.ui.Label(
        label,
        component=disnake.ui.FileUpload(
            custom_id="files",
            min_values=1 if required else 0,
            max_values=max_files,
            required=required,
        ),
        description=(
            f"Прикрепите до {max_files} фото персонажей "
            "(скриншоты из игры)."
        ),
    )


def _is_attachment_like(obj) -> bool:
    """Утка-тайпинг для Attachment — на случай разных билдов disnake."""
    return (
        obj is not None
        and hasattr(obj, "id")
        and hasattr(obj, "filename")
        and hasattr(obj, "to_file")
    )


def _collect_modal_attachments(inter: disnake.ModalInteraction) -> list:
    """Собирает все Attachment из модалки максимально устойчиво.

    Главный путь — пройти по ``inter.data.components`` (как структура
    приходит от Discord), найти ``file_upload`` (type=19) внутри ``label``
    (type=18) и взять Attachment из ``inter.data.resolved.attachments`` по
    snowflake. Параллельно есть несколько резервных путей: чистый
    ``resolved_values`` disnake, прямой обход ``data.resolved.attachments``
    и сборка из сырого ``data["resolved"]["attachments"]`` если повезёт.
    """
    found: list = []
    seen_ids: set[int] = set()

    def _push(att) -> None:
        if not _is_attachment_like(att):
            return
        try:
            aid = int(att.id)
        except Exception:
            return
        if aid in seen_ids:
            return
        seen_ids.add(aid)
        found.append(att)

    def _walk(items):
        for c in items or []:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == 1 and "components" in c:  # action_row
                yield from _walk(c["components"])
            elif t == 18 and "component" in c:  # label
                yield from _walk([c["component"]])
            else:
                yield c

    # PRIMARY: components -> file_upload(values) -> resolved.attachments by id.
    try:
        resolved_obj = getattr(inter.data, "resolved", None)
        atts_map = getattr(resolved_obj, "attachments", None) or {}
        for comp in _walk(getattr(inter.data, "components", []) or []):
            if comp.get("type") != 19:  # file_upload
                continue
            for vid in comp.get("values") or []:
                try:
                    att = atts_map.get(int(vid))
                except Exception:
                    att = None
                if att is None:
                    att = atts_map.get(str(vid))
                _push(att)
    except Exception as ex:
        print(f"[applications] primary walk failed: {ex!r}")

    if found:
        return found

    # 2) disnake resolved_values
    try:
        rv = getattr(inter, "resolved_values", None) or {}
        for v in rv.values():
            if isinstance(v, (list, tuple)):
                for item in v:
                    _push(item)
    except Exception as ex:
        print(f"[applications] resolved_values failed: {ex!r}")

    if found:
        return found

    # 3) Просто всё из inter.data.resolved.attachments
    try:
        resolved_obj = getattr(inter.data, "resolved", None)
        atts_map = getattr(resolved_obj, "attachments", None) or {}
        for att in atts_map.values():
            _push(att)
    except Exception as ex:
        print(f"[applications] resolved.attachments failed: {ex!r}")

    if found:
        return found

    # 4) Сырой dict-resolved — конструируем Attachment руками.
    try:
        raw_resolved = (
            inter.data.get("resolved")
            if hasattr(inter.data, "get")
            else None
        ) or {}
        raw_atts = raw_resolved.get("attachments") or {}
        state = getattr(inter, "_state", None)
        if state is not None:
            for raw_att in raw_atts.values():
                try:
                    _push(disnake.Attachment(data=raw_att, state=state))
                except Exception as ex:
                    print(f"[applications] Attachment ctor failed: {ex!r}")
    except Exception as ex:
        print(f"[applications] raw walk failed: {ex!r}")

    return found


async def _resolve_modal_files(
    inter: disnake.ModalInteraction,
) -> tuple[list[disnake.File], list[disnake.ui.Component]]:
    """Достаёт прикреплённые в модалку файлы и готовит их к повторной отправке.

    Возвращает кортеж: (files_to_attach, container_children_for_preview).
    Превью склеивается одной MediaGallery (если есть картинки/видео) и/или
    набором File-компонентов (для прочих файлов) — Discord отрендерит их
    прямо внутри Container, и пользователь сможет открыть/скачать каждый файл.
    """
    attachments = _collect_modal_attachments(inter)
    if not attachments:
        try:
            raw_components = getattr(inter.data, "components", None)
            raw_resolved = (
                inter.data.get("resolved")
                if hasattr(inter.data, "get")
                else None
            )
            print(
                "[applications] no attachments resolved | "
                f"components={raw_components!r} resolved={raw_resolved!r}"
            )
        except Exception:
            pass

    files: list[disnake.File] = []
    gallery_items: list[disnake.MediaGalleryItem] = []
    file_components: list[disnake.ui.Component] = []
    for idx, att in enumerate(attachments[:MAX_APPLICATION_FILES]):
        try:
            base_name = (att.filename or f"file_{idx}").replace(" ", "_")
            unique_name = f"{idx}_{base_name}"
            try:
                f = await att.to_file(filename=unique_name)
            except TypeError:
                f = await att.to_file()
                try:
                    f.filename = unique_name
                except Exception:
                    pass
            files.append(f)
            ct = (att.content_type or "").lower()
            ref = f"attachment://{unique_name}"
            if ct.startswith("image/") or ct.startswith("video/"):
                gallery_items.append(disnake.MediaGalleryItem(ref))
            else:
                file_components.append(
                    disnake.ui.File(disnake.UnfurledMediaItem(ref))
                )
        except Exception as ex:
            print(
                f"[applications] to_file failed for "
                f"{getattr(att, 'filename', '?')}: {ex!r}"
            )
            continue

    preview: list[disnake.ui.Component] = []
    if gallery_items:
        preview.append(disnake.ui.MediaGallery(*gallery_items))
    preview.extend(file_components)
    return files, preview


def _build_review_buttons(target_user_id: int) -> disnake.ui.ActionRow:
    """Кнопки модерации заявки (Принять / Отклонить / Обзвон)."""
    return disnake.ui.ActionRow(
        disnake.ui.Button(
            label="Принять",
            emoji=e_btn("SUCCESS"),
            style=disnake.ButtonStyle.success,
            custom_id=f"accept_{target_user_id}",
        ),
        disnake.ui.Button(
            label="Отклонить",
            emoji=e_btn("REJECT"),
            style=disnake.ButtonStyle.danger,
            custom_id=f"reject_{target_user_id}",
        ),
        disnake.ui.Button(
            label="Обзвон",
            emoji=e_btn("CALL"),
            style=disnake.ButtonStyle.secondary,
            custom_id=f"call_{target_user_id}",
        ),
    )


def _extract_application_text(msg: disnake.Message) -> str:
    """Возвращает текст анкеты из Container'а заявки.

    Сначала пытается достать содержимое первого ``TextDisplay`` из
    ``msg.components[0]``. Если сообщение пришло в старом формате
    (через ``embeds``), берёт ``embeds[0].description``.
    """
    try:
        if getattr(msg, "components", None):
            cont = msg.components[0]
            for child in getattr(cont, "children", []) or []:
                content = getattr(child, "content", None)
                if content:
                    return content
    except Exception:
        pass
    try:
        if getattr(msg, "embeds", None):
            return msg.embeds[0].description or ""
    except Exception:
        pass
    return ""


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

    children.append(
        disnake.ui.TextDisplay(
            "## <a:qq:1485470088600621219>Оформление заявки в семью.\n"
            "Уведомление о приглашении на обзвон отправляется в личные сообщения.\n"
            "Заявки открыты только на 17 сервер Portland <:Portland:1501581436036186244>"
        )
    )

    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "> В среднем заявки обрабатываются в течение 12-ти часов"
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
                label="Ник/Статик/Возраст",
                placeholder="Андрей, 1488, 20 лет",
                custom_id="name_static_age",
                style=disnake.TextInputStyle.short,
                max_length=80,
            ),
            _file_upload_label(
                f"Фото персонажей (1–{MAX_APPLICATION_FILES})",
                required=True,
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

        files, preview = await _resolve_modal_files(inter)
        if not files:
            return await inter.followup.send(
                components=simple_container(
                    f"{e('REJECT')}Нужно прикрепить хотя бы одно "
                    "фото персонажа.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )

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

        desc_lines = [
            "**Новая заявка**",
            "",
            f"**От:** {inter.author.mention}",
            f"**Ник/Статик/Возраст:** "
            f"{inter.text_values['name_static_age']}",
            f"**Откаты стрельбы:** {inter.text_values['reels']}",
            f"**История семей:** {inter.text_values['history']}",
            f"**Опыт и онлайн:** {inter.text_values['online']}",
            f"-# Прикреплено фото персонажей: **{len(files)}**",
        ]

        children: list = [
            disnake.ui.TextDisplay("\n".join(desc_lines)),
            disnake.ui.Separator(
                divider=True, spacing=disnake.SeparatorSpacing.small
            ),
        ]
        children.extend(preview)
        if preview:
            children.append(
                disnake.ui.Separator(
                    divider=True, spacing=disnake.SeparatorSpacing.small
                )
            )
        children.append(_build_review_buttons(inter.author.id))

        cont = [
            disnake.ui.Container(
                *children, accent_colour=ORANGE_COLOR
            )
        ]

        mentions = " ".join(
            [f"<@&{r}>" for r in config["ROLES"]["MODERATOR"]]
        )
        msg = await ticket_channel.send(
            content=f"{mentions}\nНовая заявка от {inter.author.mention}",
            components=cont,
            files=files,
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

        app_text = ""
        try:
            msg = await inter.channel.fetch_message(int(self.message_id))
            app_text = _extract_application_text(msg)
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

            if app_text:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_text}"
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

        app_text = ""
        try:
            msg = await inter.channel.fetch_message(int(self.message_id))
            app_text = _extract_application_text(msg)
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

            if app_text:
                global_embed.description = (
                    f"**Анкета кандидата:**\n\n{app_text}"
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

        # Если значение не из ожидаемых — просто сбрасываем селект и выходим.
        if not inter.values or inter.values[0] != APPLICATION_OPTION_CREATE:
            try:
                await inter.message.edit(components=build_application_panel())
            except Exception:
                pass
            return

        category = inter.guild.get_channel(
            int(config["CHANNELS"]["APPLICATION_REVIEW"])
        )
        already_open: disnake.TextChannel | None = None
        if category and isinstance(category, disnake.CategoryChannel):
            for ch in category.text_channels:
                if str(inter.author.id) in (ch.topic or ""):
                    already_open = ch
                    break

        if already_open is not None:
            await inter.response.send_message(
                f"У вас уже открыта заявка: {already_open.mention}",
                ephemeral=True,
            )
        else:
            await inter.response.send_modal(ApplicationModal())

        # После любого клика по селекту всегда сбрасываем его состояние,
        # чтобы кнопка снова была «чистой» и пользователь мог выбрать пункт
        # повторно без обновления страницы.
        try:
            await inter.message.edit(components=build_application_panel())
        except Exception:
            pass

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
                if msg.components:
                    ui_container = _to_ui_container(msg.components[0])
                    new_children: list = []
                    replaced = False
                    for child in list(
                        getattr(ui_container, "children", []) or []
                    ):
                        if not replaced and type(child).__name__ == "ActionRow":
                            new_children.append(
                                disnake.ui.ActionRow(
                                    disnake.ui.Button(
                                        label="Принять",
                                        emoji=e_btn("SUCCESS"),
                                        style=disnake.ButtonStyle.success,
                                        custom_id=f"accept_{user_id}",
                                    ),
                                    disnake.ui.Button(
                                        label="Отклонить",
                                        emoji=e_btn("REJECT"),
                                        style=disnake.ButtonStyle.danger,
                                        custom_id=f"reject_{user_id}",
                                    ),
                                )
                            )
                            replaced = True
                        else:
                            new_children.append(child)
                    new_children.append(
                        disnake.ui.TextDisplay(
                            f"-# Переведено на обзвон: "
                            f"{inter.author.display_name}"
                        )
                    )
                    new_cont = [
                        disnake.ui.Container(
                            *new_children, accent_colour=ORANGE_COLOR
                        )
                    ]
                    await msg.edit(components=new_cont)
                elif msg.embeds:
                    embed = msg.embeds[0]
                    embed.color = disnake.Color.orange()
                    embed.set_footer(
                        text=f"Переведено на обзвон: "
                        f"{inter.author.display_name}"
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
