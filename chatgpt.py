"""Read a ChatGPT data export (conversations*.json or the export .zip) read-only."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import zipfile

MAX_JSON_BYTES = 512 * 1024 * 1024


class ExportError(Exception):
    pass


@dataclass
class Message:
    role: str
    text: str
    when: datetime | None = None


@dataclass
class Conversation:
    id: str
    title: str
    created: datetime | None
    updated: datetime | None
    messages: list[Message] = field(default_factory=list)

    @property
    def when(self):
        return self.updated or self.created


def stamp(value):
    try:
        return datetime.fromtimestamp(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def part_text(part):
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        if isinstance(part.get("text"), str):
            return part["text"]
        kind = part.get("content_type") or part.get("type") or "첨부"
        return f"[{kind}]"
    return ""


def message_text(message):
    content = message.get("content") or {}
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if isinstance(parts, list):
        return "\n".join(filter(None, (part_text(part) for part in parts))).strip()
    for key in ("text", "result"):
        if isinstance(content.get(key), str):
            return content[key].strip()
    return ""


def thread(conversation):
    """Messages on the displayed branch: current_node back to the root."""
    mapping = conversation.get("mapping") or {}
    if not isinstance(mapping, dict):
        return []
    node_id = conversation.get("current_node")
    if node_id not in mapping:
        # Fall back to the newest leaf.
        leaves = [key for key, node in mapping.items() if isinstance(node, dict) and not node.get("children")]
        node_id = leaves[-1] if leaves else None
    chain, seen = [], set()
    while node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id] if isinstance(mapping[node_id], dict) else {}
        message = node.get("message")
        if isinstance(message, dict):
            role = str((message.get("author") or {}).get("role") or "")
            text = message_text(message)
            hidden = (message.get("metadata") or {}).get("is_visually_hidden_from_conversation")
            if role in ("user", "assistant") and text and not hidden:
                chain.append(Message(role=role, text=text, when=stamp(message.get("create_time"))))
        node_id = node.get("parent")
    chain.reverse()
    return chain


def parse(data):
    if isinstance(data, dict):
        data = data.get("conversations", [])
    if not isinstance(data, list):
        raise ExportError("conversations 목록 형식이 아님")
    result = []
    for number, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        result.append(Conversation(
            id=str(item.get("id") or item.get("conversation_id") or number),
            title=str(item.get("title") or "제목 없음"),
            created=stamp(item.get("create_time")), updated=stamp(item.get("update_time")),
            messages=thread(item)))
    result.sort(key=lambda conv: conv.when or datetime.min, reverse=True)
    return result


def load_export(path):
    path = Path(path)
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = sorted(name for name in archive.namelist()
                               if Path(name).name.startswith("conversations") and name.endswith(".json"))
                if not names:
                    raise ExportError("zip 안에 conversations.json 없음")
                data = []
                for name in names:
                    if archive.getinfo(name).file_size > MAX_JSON_BYTES:
                        raise ExportError(f"{name} 파일이 너무 큼")
                    chunk = json.loads(archive.read(name).decode("utf-8"))
                    data += chunk if isinstance(chunk, list) else [chunk]
        else:
            if path.stat().st_size > MAX_JSON_BYTES:
                raise ExportError("파일이 너무 큼")
            data = json.loads(path.read_text(encoding="utf-8"))
    except ExportError:
        raise
    except (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as error:
        raise ExportError(f"읽기 실패: {error}") from error
    return parse(data)


def to_markdown(conversation: Conversation):
    lines = [f"# {conversation.title}", ""]
    if conversation.when:
        lines += [f"*{conversation.when:%Y-%m-%d %H:%M}*", ""]
    for message in conversation.messages:
        lines += [f"### {'사용자' if message.role == 'user' else 'ChatGPT'}", "", message.text, ""]
    if not conversation.messages:
        lines.append("표시할 메시지 없음")
    return "\n".join(lines)
