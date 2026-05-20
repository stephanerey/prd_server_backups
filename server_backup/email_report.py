from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SENSITIVE_LINE_TOKENS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "PGPASSWORD",
    "MYSQL_PWD",
    "RESTIC_PASSWORD",
    "RESTIC_PASSWORD_FILE",
    "SSH_IDENTITY_FILE",
    "PRIVATE",
    "PASSPHRASE",
)

LAST_EMAIL_REPORT_FILE = "last-email-report.json"


def _boolish(value: object) -> bool:
    return str(value).strip().lower() == "true"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_header_value(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def _locate_sendmail() -> str | None:
    preferred = Path("/usr/sbin/sendmail")
    if preferred.exists():
        return str(preferred)
    return shutil.which("sendmail")


def _locate_mail_command() -> str | None:
    return shutil.which("mail") or shutil.which("mailx")


def _looks_like_r_unsupported(stderr: str, stdout: str) -> bool:
    combined = f"{stderr}\n{stdout}".lower()
    return any(
        token in combined
        for token in (
            "invalid option",
            "unknown option",
            "illegal option",
            "unrecognized option",
            "usage:",
        )
    )


def _write_last_email_report(global_config: dict[str, Any], payload: dict[str, Any]) -> str:
    state_dir = Path(str(global_config.get("STATE_DIR", "/var/lib/server-backup/state")))
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / LAST_EMAIL_REPORT_FILE
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def load_email_config(global_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": _boolish(global_config.get("EMAIL_REPORT_ENABLED", "")),
        "to": str(global_config.get("EMAIL_REPORT_TO", "")).strip(),
        "from": str(global_config.get("EMAIL_REPORT_FROM", "")).strip(),
        "subject_prefix": str(global_config.get("EMAIL_REPORT_SUBJECT_PREFIX", "[server-backup]")).strip() or "[server-backup]",
        "send_on_success": _boolish(global_config.get("EMAIL_REPORT_SEND_ON_SUCCESS", "")),
        "send_on_failure": _boolish(global_config.get("EMAIL_REPORT_SEND_ON_FAILURE", "")),
        "command": str(global_config.get("EMAIL_REPORT_COMMAND", "")).strip(),
    }


def should_send_email(status: str, email_config: dict[str, Any]) -> bool:
    if not bool(email_config.get("enabled")):
        return False
    lowered = str(status).strip().lower()
    if lowered == "success":
        return bool(email_config.get("send_on_success"))
    return bool(email_config.get("send_on_failure"))


def redact_sensitive_lines(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines():
        upper = line.upper()
        if any(token in upper for token in SENSITIVE_LINE_TOKENS):
            redacted_lines.append("<redacted>")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def sanitize_email_body(text: str) -> str:
    return redact_sensitive_lines(text.replace("\x00", "")).strip() + "\n"


def sanitize_email_subject(text: str) -> str:
    return redact_sensitive_lines(_sanitize_header_value(text))


def build_email_subject(
    kind: str,
    status: str,
    backup_name: str,
    hostname: str,
    prefix: str = "[server-backup]",
) -> str:
    safe_prefix = sanitize_email_subject(prefix or "[server-backup]")
    safe_backup_name = sanitize_email_subject(backup_name or "server-backup")
    safe_hostname = sanitize_email_subject(hostname or socket.gethostname())
    safe_kind = sanitize_email_subject(kind)
    safe_status = sanitize_email_subject(status)

    if safe_kind == "test":
        return f"{safe_prefix} TEST {safe_backup_name} on {safe_hostname}"
    return f"{safe_prefix} {safe_status.upper()} {safe_kind} {safe_backup_name} on {safe_hostname}"


def build_email_message(to_addr: str, from_addr: str, subject: str, body: str) -> str:
    safe_to = sanitize_email_subject(to_addr)
    safe_from = sanitize_email_subject(from_addr)
    safe_subject = sanitize_email_subject(subject)
    safe_body = sanitize_email_body(body)
    return (
        f"To: {safe_to}\n"
        f"From: {safe_from}\n"
        f"Subject: {safe_subject}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        f"{safe_body}"
    )


def send_with_sendmail(message: str, from_addr: str) -> subprocess.CompletedProcess[str]:
    sendmail = _locate_sendmail()
    if not sendmail:
        raise RuntimeError("sendmail is not available. Install or configure a local MTA first.")
    return subprocess.run(
        [sendmail, "-t", "-f", sanitize_email_subject(from_addr)],
        check=False,
        capture_output=True,
        text=True,
        input=message,
        shell=False,
    )


def send_with_mail(to_addr: str, from_addr: str, subject: str, body: str) -> subprocess.CompletedProcess[str]:
    mail_cmd = _locate_mail_command()
    if not mail_cmd:
        raise RuntimeError("mail/mailx is not available. Install mailutils or mailx first.")

    first_attempt = subprocess.run(
        [mail_cmd, "-s", sanitize_email_subject(subject), "-r", sanitize_email_subject(from_addr), sanitize_email_subject(to_addr)],
        check=False,
        capture_output=True,
        text=True,
        input=sanitize_email_body(body),
        shell=False,
    )
    if first_attempt.returncode == 0:
        return first_attempt

    if _looks_like_r_unsupported(first_attempt.stderr or "", first_attempt.stdout or ""):
        return subprocess.run(
            [mail_cmd, "-s", sanitize_email_subject(subject), sanitize_email_subject(to_addr)],
            check=False,
            capture_output=True,
            text=True,
            input=f"From: {sanitize_email_subject(from_addr)}\n\n{sanitize_email_body(body)}",
            shell=False,
        )

    return first_attempt


def send_email_report(kind: str, status: str, report_text: str, global_config: dict[str, Any]) -> dict[str, Any]:
    email_config = load_email_config(global_config)
    attempted = should_send_email(status, email_config)
    result: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "attempted": attempted,
        "success": False,
        "skipped": not attempted,
        "to": email_config.get("to", ""),
        "from": email_config.get("from", ""),
        "subject": "",
        "command": email_config.get("command", ""),
        "sent_at": _timestamp(),
        "error": "",
    }

    if not attempted:
        result["skip_reason"] = "Automatic email disabled by configuration or send policy."
        return result

    to_addr = str(email_config.get("to", "")).strip()
    from_addr = str(email_config.get("from", "")).strip()
    command = str(email_config.get("command", "")).strip()
    if not to_addr:
        result["error"] = "EMAIL_REPORT_TO is missing."
    elif not from_addr:
        result["error"] = "EMAIL_REPORT_FROM is missing."
    elif command not in {"sendmail", "mail"}:
        result["error"] = "EMAIL_REPORT_COMMAND must be 'sendmail' or 'mail'."

    backup_name = str(global_config.get("BACKUP_NAME", "")).strip()
    hostname = socket.gethostname()
    result["subject"] = build_email_subject(
        kind,
        status,
        backup_name,
        hostname,
        prefix=str(email_config.get("subject_prefix", "[server-backup]")),
    )

    if result["error"]:
        result["last_email_report_path"] = _write_last_email_report(global_config, result)
        return result

    body = sanitize_email_body(report_text)
    try:
        if command == "sendmail":
            message = build_email_message(to_addr, from_addr, result["subject"], body)
            completed = send_with_sendmail(message, from_addr)
        else:
            completed = send_with_mail(to_addr, from_addr, result["subject"], body)
    except RuntimeError as exc:
        result["error"] = str(exc)
        result["last_email_report_path"] = _write_last_email_report(global_config, result)
        return result

    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout or "Email command failed without output.").strip()
    else:
        result["success"] = True

    result["last_email_report_path"] = _write_last_email_report(global_config, result)
    return result


def send_test_email(global_config: dict[str, Any], to_override: str | None = None) -> dict[str, Any]:
    email_config = load_email_config(global_config)
    to_addr = to_override.strip() if to_override else str(email_config.get("to", "")).strip()
    from_addr = str(email_config.get("from", "")).strip() or f"server-backup@{socket.gethostname()}"
    command = str(email_config.get("command", "")).strip()
    backup_name = str(global_config.get("BACKUP_NAME", "")).strip() or "server-backup"
    hostname = socket.gethostname()
    subject = build_email_subject(
        "test",
        "test",
        backup_name,
        hostname,
        prefix=str(email_config.get("subject_prefix", "[server-backup]")),
    )
    body_lines = [
        "server-backup email test",
        "",
        f"BACKUP_NAME: {backup_name}",
        f"Hostname: {hostname}",
        f"Sent at: {_timestamp()}",
        "",
        "This is a test email from server-backup.",
    ]
    body = sanitize_email_body("\n".join(body_lines))
    result: dict[str, Any] = {
        "kind": "test",
        "status": "test",
        "attempted": True,
        "success": False,
        "skipped": False,
        "to": to_addr,
        "from": from_addr,
        "subject": subject,
        "command": command,
        "sent_at": _timestamp(),
        "error": "",
    }

    if not to_addr:
        result["error"] = "EMAIL_REPORT_TO is missing. Use --to or configure EMAIL_REPORT_TO."
    elif command not in {"sendmail", "mail"}:
        result["error"] = "EMAIL_REPORT_COMMAND must be 'sendmail' or 'mail'."

    if result["error"]:
        result["last_email_report_path"] = _write_last_email_report(global_config, result)
        return result

    try:
        if command == "sendmail":
            message = build_email_message(to_addr, from_addr, subject, body)
            completed = send_with_sendmail(message, from_addr)
        else:
            completed = send_with_mail(to_addr, from_addr, subject, body)
    except RuntimeError as exc:
        result["error"] = str(exc)
        result["last_email_report_path"] = _write_last_email_report(global_config, result)
        return result

    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout or "Email command failed without output.").strip()
    else:
        result["success"] = True

    result["last_email_report_path"] = _write_last_email_report(global_config, result)
    return result
