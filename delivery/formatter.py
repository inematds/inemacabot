"""Formatação segura dos estados dos jobs."""

from __future__ import annotations

from queueing.models import Job, JobStatus


STATUS_LABELS = {
    JobStatus.PENDING: "aguardando",
    JobStatus.RUNNING: "executando",
    JobStatus.COMPLETED: "concluído",
    JobStatus.FAILED: "falhou",
    JobStatus.CANCELLED: "cancelado",
}


def format_job_summary(job: Job) -> str:
    lines = [
        f"Job: {job.id}",
        f"Fila: {job.queue.value}",
        f"Skill: {job.skill}",
        f"Status: {STATUS_LABELS[job.status]}",
        f"Progresso: {job.progress}%",
        f"Tentativas: {job.attempts}/{job.max_attempts}",
    ]
    if job.error:
        lines.append(f"Erro: {job.error}")
    return "\n\n".join(lines)


def format_delivery(job: Job) -> str:
    if job.status == JobStatus.COMPLETED:
        summary = ""
        if job.result:
            value = job.result.get("summary")
            if isinstance(value, str):
                summary = value.strip()
        message = f"Seu pedido foi concluído.\n\nJob: {job.id}"
        if summary:
            message += f"\n\n{summary}"
        return message
    if job.status == JobStatus.CANCELLED:
        return f"Seu pedido foi cancelado.\n\nJob: {job.id}"
    return (
        "Não foi possível concluir seu pedido.\n\n"
        f"Job: {job.id}\n\n"
        f"Tentativas: {job.attempts}\n\n"
        f"Motivo: {job.error or 'erro durante a execução'}"
    )
