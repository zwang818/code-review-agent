"""Observe/act loop and bounded, transactional conversation memory."""

import copy
import json
from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings
from .errors import AgentError, ModelError
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, ToolRegistry


@dataclass
class ReviewResult:
    report: str
    trace: list
    model_calls: int
    tool_calls: int


class ReviewAgent:
    def __init__(self, client, tools: ToolRegistry, settings: Settings,
                 on_event: Optional[Callable[[str], None]] = None):
        self.client, self.tools, self.settings = client, tools, settings
        self.on_event = on_event or (lambda message: None)
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self) -> None:
        self.messages = self.messages[:1]

    def _trim(self) -> None:
        """Discard whole oldest user turns, never orphan tool-call messages."""
        while True:
            starts = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
            too_many = len(starts) > self.settings.memory_turns
            too_large = len(json.dumps(self.messages, ensure_ascii=False)) > self.settings.max_context_chars
            if not (too_many or too_large) or len(starts) < 2:
                break
            del self.messages[starts[0]:starts[1]]
            self.on_event("[记忆] 已移除最早的一轮完整会话以控制上下文长度。")

    def run(self, task: str) -> ReviewResult:
        if not isinstance(task, str) or not task.strip():
            raise AgentError("任务不能为空。")
        if len(task) > 12000:
            raise AgentError("任务描述过长，请缩短到 12000 字符以内。")
        snapshot = copy.deepcopy(self.messages)
        first_turn = len(self.messages) == 1
        trace, count = [], 0
        self.messages.append({"role": "user", "content": task.strip()})
        try:
            self._trim()
            for round_no in range(self.settings.max_rounds + 1):
                if len(json.dumps(self.messages, ensure_ascii=False)) > self.settings.max_context_chars:
                    raise AgentError("当前任务超过上下文字符预算，请缩小文件范围或 /reset。")
                final_round = round_no == self.settings.max_rounds or count >= self.settings.max_tool_calls
                request_messages = copy.deepcopy(self.messages)
                if final_round:
                    # This instruction is for this request only, not later user turns.
                    request_messages.append({"role": "system", "content":
                        "工具调用预算已耗尽。请仅基于已有证据输出报告，并明确说明未检查的范围。"})
                choice = "none" if final_round else ("required" if first_turn and round_no == 0 else "auto")
                self.on_event("[决策] 第 %d 轮%s" % (round_no + 1, "（收束报告）" if final_round else ""))
                message = self.client.complete(request_messages, TOOL_SCHEMAS, choice)
                calls = message.get("tool_calls") or []
                if choice == "required" and not calls:
                    raise ModelError("模型未执行要求的工具调用，请更换支持 tools 的模型。")
                if final_round and calls:
                    raise ModelError("模型忽略了工具预算，请缩小审查范围或更换模型。")
                self.messages.append(message)
                if not calls:
                    report = message.get("content", "")
                    if not report.strip():
                        raise ModelError("模型返回了空报告。")
                    if final_round:
                        report = "> 本轮已达到调用预算；报告仅覆盖已获取的证据。\n\n" + report
                        message["content"] = report
                    self._trim()
                    return ReviewResult(report, trace, round_no + 1, count)
                for call in calls:
                    name, arguments = call["function"]["name"], call["function"]["arguments"]
                    if count >= self.settings.max_tool_calls:
                        result = {"ok": False, "error": "工具调用预算耗尽，此调用未执行。"}
                    else:
                        result = self.tools.execute(name, arguments)
                        count += 1
                    data = result.get("data", {})
                    entry = {"tool": name, "ok": result["ok"], "path": data.get("path"),
                             "error": result.get("error")}
                    trace.append(entry)
                    summary = "成功" if result["ok"] else result["error"]
                    self.on_event("[工具] %s%s：%s" % (name, " " + data["path"] if data.get("path") else "", summary))
                    self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                          "content": json.dumps(result, ensure_ascii=False)})
            raise AgentError("Agent 未能在调用预算内结束。")
        except (Exception, KeyboardInterrupt):
            # Roll back incomplete turns so the next request has valid protocol history.
            self.messages = snapshot
            raise
