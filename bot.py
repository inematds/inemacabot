"""Ponto de entrada do assistente pessoal no Telegram."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from auth import is_authorized
from codex_client import CodexClient, CodexError
from config import ConfigurationError, Settings
from delivery.formatter import format_job_summary
from history import ConversationHistory
from message_utils import split_message
from queueing.job_repository import JobRepository
from queueing.models import Job, JobStatus, QueueName, generate_job_id
from routing.intent_router import IntentRouter
from routing.models import RouteAction
from skills.registry import SkillRegistry
from transcription_client import (
    GroqTranscriptionClient,
    TranscriptionError,
    TranscriptionNotConfigured,
)


LOGGER = logging.getLogger(__name__)
START_MESSAGE = "Olá! Sou seu assistente pessoal. Envie uma mensagem e eu responderei."
HELP_MESSAGE = (
    "Envie uma mensagem de texto, uma mensagem de voz ou um arquivo de áudio. "
    "Use /limpar para apagar o contexto recente. "
    "Use /skills para ver as tarefas disponíveis e /meusjobs para acompanhar pedidos. "
    "Para criar um vídeo de reforma, envie uma foto com /vsvideo 6 ou "
    "/vsvideo 18. Use /vsvideo 18 codex para gerar as imagens pela assinatura "
    "Codex e acrescente aprovacao para conferir os estágios antes."
)
GENERIC_ERROR_MESSAGE = (
    "Não consegui responder agora. Tente novamente em alguns instantes."
)


@dataclass(slots=True)
class BotServices:
    settings: Settings
    history: ConversationHistory
    codex: CodexClient
    transcription: GroqTranscriptionClient
    jobs: JobRepository
    skills: SkillRegistry
    router: IntentRouter
    conversation_lock: asyncio.Lock


def _services(context: ContextTypes.DEFAULT_TYPE) -> BotServices:
    return context.application.bot_data["services"]


def _authorized(update: Update, services: BotServices) -> bool:
    user = update.effective_user
    return is_authorized(
        user.id if user is not None else None,
        services.settings.telegram_allowed_user_id,
    )


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    if not _authorized(update, services) or update.effective_message is None:
        return
    await update.effective_message.reply_text(START_MESSAGE)


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    if not _authorized(update, services) or update.effective_message is None:
        return
    await update.effective_message.reply_text(HELP_MESSAGE)


async def clear_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    if not _authorized(update, services) or update.effective_message is None:
        return
    async with services.conversation_lock:
        services.history.clear()
    await update.effective_message.reply_text("Histórico da conversa apagado.")


async def text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None or not message.text:
        return
    await _route_or_reply(update, context, message.text.strip())


async def audio_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return

    media = message.voice or message.audio
    if media is None:
        return
    if not services.transcription.configured:
        await message.reply_text(
            "A transcrição de áudio ainda não está configurada. "
            "Defina GROQ_API_KEY no arquivo .env."
        )
        return
    if media.file_size and media.file_size > services.settings.max_audio_bytes:
        max_mb = services.settings.max_audio_bytes // (1024 * 1024)
        await message.reply_text(
            f"O áudio ultrapassa o limite configurado de {max_mb} MB."
        )
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id, action=ChatAction.TYPING
    )

    try:
        telegram_file = await context.bot.get_file(media.file_id)
        content = bytes(await telegram_file.download_as_bytearray())
        filename = getattr(media, "file_name", None) or "mensagem-de-voz.ogg"
        content_type = getattr(media, "mime_type", None) or "audio/ogg"
        transcript = await services.transcription.transcribe(
            filename=filename,
            content=content,
            content_type=content_type,
        )
    except TranscriptionNotConfigured:
        await message.reply_text(
            "A transcrição de áudio ainda não está configurada."
        )
        return
    except TranscriptionError:
        LOGGER.exception("Falha ao transcrever áudio do Telegram.")
        await message.reply_text(
            "Não consegui transcrever esse áudio. Tente novamente."
        )
        return
    except Exception:
        LOGGER.exception("Falha ao baixar áudio do Telegram.")
        await message.reply_text("Não consegui baixar esse áudio.")
        return

    await _route_or_reply(update, context, transcript)


async def virtual_staging_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return
    if not services.settings.agnes_api_key:
        await message.reply_text("A integração Agnes ainda não está configurada.")
        return
    try:
        duration, approval, image_provider = _parse_vsvideo_options(
            message.caption or message.text or "/vsvideo"
        )
    except ValueError:
        await message.reply_text(
            "Uso: envie uma foto com /vsvideo 6, /vsvideo 18 ou "
            "/vsvideo 18 codex. Acrescente aprovacao para conferir antes."
        )
        return
    if not message.photo:
        await message.reply_text(
            "Envie uma foto de interior pronto com /vsvideo 6, /vsvideo 18 "
            "ou /vsvideo 18 codex na legenda."
        )
        return
    photo = message.photo[-1]
    if (
        photo.file_size
        and photo.file_size > services.settings.vsvideo_max_image_bytes
    ):
        max_mb = services.settings.vsvideo_max_image_bytes // (1024 * 1024)
        await message.reply_text(
            f"A imagem ultrapassa o limite configurado de {max_mb} MB."
        )
        return

    job_id = generate_job_id()
    job_root = (Path(services.settings.job_work_root).resolve() / job_id).resolve()
    work_root = Path(services.settings.job_work_root).resolve()
    if job_root.parent != work_root:
        await message.reply_text("Não foi possível preparar o job.")
        return
    image_path = job_root / "files" / "interior-finalizado.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        telegram_file = await context.bot.get_file(photo.file_id)
        content = bytes(await telegram_file.download_as_bytearray())
        if len(content) > services.settings.vsvideo_max_image_bytes:
            raise ValueError("imagem acima do limite")
        image_path.write_bytes(content)
        if image_provider == "codex":
            skill = (
                "vsvideo-codex-agnes-preview"
                if approval
                else "vsvideo-codex-agnes"
            )
            mode = "codex-preview" if approval else "codex-auto18"
        elif duration == 18 and approval:
            skill = "vsvideo-agnes-preview"
            mode = "preview"
        else:
            skill = "vsvideo-agnes"
            mode = "auto18" if duration == 18 else "short"
        job = await _create_job(
            services,
            queue=QueueName.VIDEOS,
            skill=skill,
            payload={
                "image_path": str(image_path),
                "duration": duration,
                "mode": mode,
                "image_provider": image_provider,
            },
            update=update,
            job_id=job_id,
        )
    except ValueError:
        LOGGER.exception("Imagem de virtual staging inválida.")
        await message.reply_text("Não foi possível aceitar essa imagem.")
        return
    except Exception:
        LOGGER.exception("Falha ao criar job de virtual staging.")
        await message.reply_text("Não foi possível criar o vídeo agora.")
        return
    await message.reply_text(_job_created_message(job))


def _parse_vsvideo_options(value: str) -> tuple[int, bool, str]:
    parts = value.strip().split()
    if not parts or parts[0].split("@", 1)[0].casefold() != "/vsvideo":
        raise ValueError("comando inválido")
    duration = 6
    approval = False
    image_provider = "agnes"
    for part in parts[1:]:
        normalized = part.casefold()
        if normalized in {"6", "18"}:
            duration = int(normalized)
        elif normalized in {"aprovacao", "aprovação"}:
            approval = True
        elif normalized in {"codex", "openai"}:
            image_provider = "codex"
        else:
            raise ValueError("parâmetro inválido")
    if approval and duration != 18:
        raise ValueError("aprovação disponível somente para 18 segundos")
    if image_provider == "codex" and duration != 18:
        raise ValueError("imagens Codex disponíveis somente para 18 segundos")
    return duration, approval, image_provider


async def approve_video_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    user = update.effective_user
    if not _authorized(update, services) or message is None or user is None:
        return
    if not context.args:
        await message.reply_text("Uso: /aprovarvideo <job_id>")
        return
    source = await asyncio.to_thread(
        services.jobs.get_job, context.args[0], user_id=str(user.id)
    )
    if (
        source is None
        or source.skill
        not in {
            "vsvideo-agnes-preview",
            "vsvideo-codex-agnes-preview",
        }
        or source.status != JobStatus.COMPLETED
        or not source.result
    ):
        await message.reply_text("Job de aprovação não encontrado ou ainda incompleto.")
        return
    existing = await asyncio.to_thread(
        services.jobs.get_jobs_by_user, str(user.id), limit=100
    )
    repeated = next(
        (
            job
            for job in existing
            if job.skill == "vsvideo-agnes-render"
            and job.payload.get("source_job_id") == source.id
        ),
        None,
    )
    if repeated is not None:
        await message.reply_text(
            f"Esse preview já foi aprovado.\n\nJob do vídeo: {repeated.id}"
        )
        return

    raw_files = source.result.get("stage_files", source.result.get("files"))
    if not isinstance(raw_files, list) or len(raw_files) != 4:
        await message.reply_text("Os estágios desse job estão incompletos.")
        return
    source_root = (Path(services.settings.job_work_root) / source.id).resolve()
    source_paths = [Path(str(value)).resolve() for value in raw_files]
    if any(
        source_root not in path.parents or not path.is_file()
        for path in source_paths
    ):
        await message.reply_text("Os arquivos de aprovação não estão disponíveis.")
        return

    job_id = generate_job_id()
    job_root = (Path(services.settings.job_work_root) / job_id).resolve()
    work_root = Path(services.settings.job_work_root).resolve()
    if job_root.parent != work_root:
        await message.reply_text("Não foi possível preparar o job.")
        return
    destination_root = job_root / "files"
    destination_root.mkdir(parents=True, exist_ok=True)
    destinations: list[str] = []
    try:
        for index, source_path in enumerate(source_paths, start=1):
            destination = destination_root / f"approved-stage-{index}{source_path.suffix}"
            shutil.copyfile(source_path, destination)
            destinations.append(str(destination))
        job = await _create_job(
            services,
            queue=QueueName.VIDEOS,
            skill="vsvideo-agnes-render",
            payload={
                "stage_paths": destinations,
                "source_job_id": source.id,
                "duration": 18,
                "mode": "render18",
            },
            update=update,
            job_id=job_id,
        )
    except Exception:
        LOGGER.exception("Falha ao aprovar vídeo de virtual staging.")
        await message.reply_text("Não foi possível criar o vídeo aprovado agora.")
        return
    await message.reply_text(_job_created_message(job))


async def _route_or_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
) -> None:
    services = _services(context)
    message = update.effective_message
    if message is None or not user_message:
        return
    if not services.settings.queue_routing_enabled:
        await _generate_and_reply(update, context, user_message)
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id, action=ChatAction.TYPING
    )
    try:
        async with services.conversation_lock:
            decision = await services.router.decide(
                services.history.snapshot(), user_message
            )
            if decision.action == RouteAction.REPLY:
                response = decision.response or GENERIC_ERROR_MESSAGE
            elif decision.action == RouteAction.CLARIFY:
                response = decision.question or "Preciso de mais informações."
            else:
                assert decision.queue is not None
                assert decision.skill is not None
                assert decision.payload is not None
                job = await _create_job(
                    services,
                    queue=decision.queue,
                    skill=decision.skill,
                    payload=decision.payload,
                    update=update,
                )
                position = await asyncio.to_thread(
                    services.jobs.get_queue_position, job.id
                )
                response = _job_created_message(job, position)
            services.history.add_exchange(user_message, response)
    except (CodexError, ValueError):
        LOGGER.exception("Falha ao rotear a mensagem.")
        await message.reply_text(
            "Não consegui interpretar esse pedido. Pode reformulá-lo?"
        )
        return

    for chunk in split_message(response):
        await message.reply_text(chunk)


async def _generate_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_message: str,
) -> None:
    services = _services(context)
    message = update.effective_message
    if message is None or not user_message:
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id, action=ChatAction.TYPING
    )

    try:
        async with services.conversation_lock:
            answer = await services.codex.answer(
                services.history.snapshot(), user_message
            )
            services.history.add_exchange(user_message, answer)
    except CodexError:
        LOGGER.exception("Falha ao gerar resposta com o Codex.")
        await message.reply_text(GENERIC_ERROR_MESSAGE)
        return

    for chunk in split_message(answer):
        await message.reply_text(chunk)


async def status_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return
    workers = await asyncio.to_thread(services.jobs.get_workers)
    active = sum(1 for worker in workers if worker["status"] == "running")
    await message.reply_text(
        "InemacaBot ativo.\n\n"
        f"Roteamento por filas: {'ativo' if services.settings.queue_routing_enabled else 'inativo'}\n\n"
        f"Workers registrados: {len(workers)}\n\n"
        f"Workers executando: {active}"
    )


async def queues_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return
    stats = await asyncio.to_thread(services.jobs.get_queue_stats)
    lines = ["Filas:"]
    for queue in QueueName:
        values = stats[queue.value]
        lines.append(
            f"{queue.value}: {values['pending']} aguardando, "
            f"{values['running']} executando, "
            f"{values['completed']} concluídos, {values['failed']} falhos"
        )
    await message.reply_text("\n\n".join(lines))


async def my_jobs_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    user = update.effective_user
    if not _authorized(update, services) or message is None or user is None:
        return
    jobs = await asyncio.to_thread(
        services.jobs.get_jobs_by_user, str(user.id), limit=10
    )
    if not jobs:
        await message.reply_text("Você ainda não possui jobs.")
        return
    await message.reply_text(
        "\n\n".join(
            f"{job.id}\n{job.skill} · {job.queue.value} · {job.status.value} · {job.progress}%"
            for job in jobs
        )
    )


async def job_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    user = update.effective_user
    if not _authorized(update, services) or message is None or user is None:
        return
    if not context.args:
        await message.reply_text("Uso: /job <id>")
        return
    job = await asyncio.to_thread(
        services.jobs.get_job, context.args[0], user_id=str(user.id)
    )
    await message.reply_text(
        format_job_summary(job) if job else "Job não encontrado."
    )


async def cancel_job_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    user = update.effective_user
    if not _authorized(update, services) or message is None or user is None:
        return
    if not context.args:
        await message.reply_text("Uso: /cancelar <id>")
        return
    job = await asyncio.to_thread(
        services.jobs.cancel_job, context.args[0], str(user.id)
    )
    if job is None:
        await message.reply_text("Job não encontrado.")
    elif job.cancel_requested_at and job.status.value == "running":
        await message.reply_text("Cancelamento solicitado ao worker.")
    else:
        await message.reply_text(format_job_summary(job))


async def retry_job_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    user = update.effective_user
    if not _authorized(update, services) or message is None or user is None:
        return
    if not context.args:
        await message.reply_text("Uso: /repetir <id>")
        return
    original = await asyncio.to_thread(
        services.jobs.get_job, context.args[0], user_id=str(user.id)
    )
    if original is None:
        await message.reply_text("Job não encontrado.")
        return
    try:
        services.skills.validate_payload(original.skill, original.payload)
    except ValueError:
        await message.reply_text("A skill desse job não está mais disponível.")
        return
    job = await asyncio.to_thread(
        services.jobs.retry_job, original.id, str(user.id)
    )
    await message.reply_text(
        _job_created_message(job)
        if job
        else "Esse job ainda não pode ser repetido."
    )


async def skills_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return
    lines = ["Skills disponíveis:"]
    for skill in services.skills.enabled():
        fields = ", ".join(skill.required_fields)
        lines.append(
            f"{skill.name} ({skill.queue.value}) — {skill.description}. "
            f"Campos: {fields}"
        )
    await message.reply_text("\n\n".join(lines))


async def test_queue_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    services = _services(context)
    message = update.effective_message
    if not _authorized(update, services) or message is None:
        return
    text = " ".join(context.args).strip()
    if not text:
        await message.reply_text("Uso: /testefila <texto>")
        return
    try:
        services.skills.validate_payload("teste-fila", {"texto": text})
        job = await _create_job(
            services,
            queue=QueueName.SERVICOS,
            skill="teste-fila",
            payload={"texto": text},
            update=update,
        )
    except ValueError as exc:
        await message.reply_text(f"Não foi possível criar o job: {exc}")
        return
    await message.reply_text(_job_created_message(job))


async def _create_job(
    services: BotServices,
    *,
    queue: QueueName,
    skill: str,
    payload: dict[str, object],
    update: Update,
    job_id: str | None = None,
) -> Job:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        raise ValueError("Mensagem sem usuário ou chat.")
    definition = services.skills.validate_payload(skill, payload)
    if definition.queue != queue:
        raise ValueError("A fila não corresponde à skill.")
    if not services.settings.accept_jobs_when_worker_offline:
        worker_online = await asyncio.to_thread(
            services.jobs.has_recent_worker, queue
        )
        if not worker_online:
            raise ValueError(f"Não há worker ativo para a fila {queue.value}.")
    return await asyncio.to_thread(
        services.jobs.create_job,
        queue=queue,
        skill=skill,
        payload=payload,
        user_id=str(user.id),
        chat_id=str(message.chat_id),
        source_message_id=str(message.message_id),
        max_attempts=services.settings.job_default_max_attempts,
        job_id=job_id,
    )


def _job_created_message(job: Job, position: int | None = None) -> str:
    message = (
        "Seu pedido foi adicionado à fila.\n\n"
        f"Job: {job.id}\n\n"
        f"Fila: {job.queue.value}\n\n"
        f"Skill: {job.skill}\n\n"
        "Status: aguardando"
    )
    if position is not None:
        message += f"\nPosição aproximada: {position}"
    return message


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.error(
        "Erro não tratado no bot: %s",
        type(context.error).__name__ if context.error else "desconhecido",
        exc_info=context.error,
    )


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Iniciar o assistente"),
            BotCommand("limpar", "Apagar o histórico da conversa"),
            BotCommand("status", "Mostrar o estado do sistema"),
            BotCommand("filas", "Mostrar o estado das filas"),
            BotCommand("meusjobs", "Listar seus jobs recentes"),
            BotCommand("job", "Consultar um job"),
            BotCommand("cancelar", "Cancelar um job"),
            BotCommand("repetir", "Repetir um job finalizado"),
            BotCommand("skills", "Listar skills disponíveis"),
            BotCommand("testefila", "Criar um job de teste"),
            BotCommand("vsvideo", "Criar vídeo de reforma a partir de uma foto"),
            BotCommand("aprovarvideo", "Aprovar estágios e gerar o vídeo"),
            BotCommand("ajuda", "Mostrar como usar o bot"),
        ]
    )


def build_application(settings: Settings) -> Application:
    jobs = JobRepository(settings.queue_database_path)
    jobs.migrate()
    skills = SkillRegistry.from_file(settings.skills_registry_path)
    codex = CodexClient(
        binary=settings.codex_binary,
        model=settings.codex_model,
        system_prompt=settings.system_prompt,
        timeout_seconds=settings.codex_timeout_seconds,
    )
    services = BotServices(
        settings=settings,
        history=ConversationHistory(settings.history_max_exchanges),
        codex=codex,
        transcription=GroqTranscriptionClient(
            api_key=settings.groq_api_key,
            url=settings.groq_transcription_url,
            model=settings.groq_transcription_model,
            language=settings.groq_transcription_language,
        ),
        jobs=jobs,
        skills=skills,
        router=IntentRouter(codex, skills),
        conversation_lock=asyncio.Lock(),
    )

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["services"] = services
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("limpar", clear_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("filas", queues_command))
    application.add_handler(CommandHandler("meusjobs", my_jobs_command))
    application.add_handler(CommandHandler("job", job_command))
    application.add_handler(CommandHandler("cancelar", cancel_job_command))
    application.add_handler(CommandHandler("repetir", retry_job_command))
    application.add_handler(CommandHandler("skills", skills_command))
    application.add_handler(CommandHandler("testefila", test_queue_command))
    application.add_handler(CommandHandler("vsvideo", virtual_staging_message))
    application.add_handler(CommandHandler("aprovarvideo", approve_video_command))
    application.add_handler(
        MessageHandler(
            filters.PHOTO
            & filters.CaptionRegex(r"^/vsvideo(?:@\w+)?(?:\s|$)"),
            virtual_staging_message,
        )
    )
    application.add_handler(CommandHandler("ajuda", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )
    application.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, audio_message)
    )
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"Erro de configuração: {exc}") from exc

    LOGGER.info("Iniciando o bot por long polling.")
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
