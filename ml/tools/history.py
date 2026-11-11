"""Read-only tool. Its authority comes from the application's current profile."""
import asyncio
import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class HistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    teacher_id: int = Field(gt=0)
    limit: int = Field(ge=1, le=6)


HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "read_topic_history",
        "description": "Получить до шести прошлых тем текущего преподавателя.",
        "parameters": HistoryArgs.model_json_schema(),
        "strict": True,
    },
}


async def dispatch(call: dict, *, teacher_id: int,
                   read: Callable[[], Awaitable[list[str]]], timeout: float = 0.25) -> dict:
    """Validate model arguments and limit reads to the already selected profile."""
    try:
        function = call["function"]
        if function["name"] != "read_topic_history":
            return {"status": "unknown_tool"}
        args = HistoryArgs.model_validate_json(function["arguments"])
    except (KeyError, TypeError, ValidationError):
        return {"status": "invalid_arguments"}
    if args.teacher_id != teacher_id:
        return {"status": "forbidden"}
    try:
        titles = await asyncio.wait_for(read(), timeout)
    except TimeoutError:
        return {"status": "timeout"}
    except (OSError, RuntimeError):
        return {"status": "unavailable"}
    return {"status": "ok", "titles": [title[:500] for title in titles[:args.limit]]}


def tool_message(call_id: str, result: dict) -> dict:
    return {"role": "tool", "name": "read_topic_history", "tool_call_id": call_id,
            "content": json.dumps(result, ensure_ascii=False)}
