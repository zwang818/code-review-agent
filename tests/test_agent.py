import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from code_review_agent.agent import ReviewAgent
from code_review_agent.cli import review_task
from code_review_agent.config import Settings
from code_review_agent.demo import DemoClient
from code_review_agent.errors import AgentError, ModelError
from code_review_agent.tools import ToolRegistry


def call(name="read_file", arguments='{"path":"a.py"}', identifier="call_1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": identifier, "type": "function",
                            "function": {"name": name, "arguments": arguments}}]}


class ScriptedClient:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def complete(self, messages, tools, tool_choice="auto"):
        self.requests.append((copy.deepcopy(messages), tool_choice))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "a.py").write_text("def f(items=[]):\n    return items\n")
        self.tools, self.settings = ToolRegistry(self.root), Settings()

    def agent(self, responses, settings=None):
        client = ScriptedClient(responses)
        return ReviewAgent(client, self.tools, settings or self.settings), client

    def test_tool_observation_is_returned_to_model(self):
        agent, client = self.agent([call(), {"role": "assistant", "content": "报告"}])
        result = agent.run("审查 a.py")
        self.assertEqual((result.model_calls, result.tool_calls), (2, 1))
        messages = client.requests[1][0]
        self.assertEqual(messages[-1]["tool_call_id"], "call_1")
        self.assertTrue(json.loads(messages[-1]["content"])["ok"])

    def test_invalid_tool_arguments_can_be_corrected(self):
        agent, client = self.agent([call(arguments="not-json"), call(identifier="call_2"),
                                   {"role": "assistant", "content": "已恢复"}])
        result = agent.run("审查 a.py")
        self.assertEqual(result.report, "已恢复")
        self.assertFalse(json.loads(client.requests[1][0][-1]["content"])["ok"])
        self.assertTrue(json.loads(client.requests[2][0][-1]["content"])["ok"])

    def test_memory_retains_report_and_reset_clears(self):
        agent, client = self.agent([call(), {"role": "assistant", "content": "第一轮报告"},
                                   {"role": "assistant", "content": "追问回答"}])
        agent.run("审查 a.py")
        agent.run("第一个问题怎么改？")
        self.assertIn("第一轮报告", [m.get("content") for m in client.requests[-1][0]])
        self.assertEqual(client.requests[-1][1], "auto")
        agent.reset()
        self.assertEqual(len(agent.messages), 1)

    def test_failure_rolls_back_incomplete_turn(self):
        agent, client = self.agent([call(), {"role": "assistant", "content": "第一轮"},
                                   call(identifier="second"), ModelError("offline")])
        agent.run("审查 a.py")
        snapshot = copy.deepcopy(agent.messages)
        with self.assertRaises(ModelError):
            agent.run("继续分析")
        self.assertEqual(agent.messages, snapshot)

    def test_round_budget_forces_final_and_does_not_pollute_memory(self):
        agent, client = self.agent([call(), {"role": "assistant", "content": "部分报告"},
                                   {"role": "assistant", "content": "下一轮"}],
                                  replace(self.settings, max_rounds=1))
        result = agent.run("审查 a.py")
        self.assertIn("调用预算", result.report)
        self.assertEqual(client.requests[1][1], "none")
        self.assertEqual(sum(m["role"] == "system" for m in agent.messages), 1)
        agent.run("追问")
        self.assertEqual(client.requests[-1][1], "auto")

    def test_tool_budget_pairs_even_unexecuted_calls(self):
        batch = call()
        batch["tool_calls"] += call(identifier="call_2")["tool_calls"]
        agent, client = self.agent([batch, {"role": "assistant", "content": "部分报告"}],
                                  replace(self.settings, max_tool_calls=1))
        result = agent.run("审查 a.py")
        self.assertEqual(result.tool_calls, 1)
        outputs = [m for m in client.requests[-1][0] if m["role"] == "tool"]
        self.assertEqual(len(outputs), 2)
        self.assertFalse(json.loads(outputs[-1]["content"])["ok"])

    def test_model_cannot_ignore_final_budget(self):
        agent, _ = self.agent([call(), call(identifier="second")], replace(self.settings, max_rounds=1))
        with self.assertRaises(ModelError):
            agent.run("审查 a.py")
        self.assertEqual(len(agent.messages), 1)

    def test_first_review_requires_a_tool(self):
        agent, _ = self.agent([{"role": "assistant", "content": "凭空生成报告"}])
        with self.assertRaises(ModelError):
            agent.run("审查 a.py")

    def test_pruning_removes_whole_turns(self):
        responses = [call(identifier="one"), {"role": "assistant", "content": "第一轮"},
                     call(identifier="two"), {"role": "assistant", "content": "第二轮"}]
        agent, client = self.agent(responses, replace(self.settings, memory_turns=1))
        agent.run("task1")
        agent.run("task2")
        latest = client.requests[-1][0]
        self.assertNotIn("task1", [m.get("content") for m in latest])
        self.assertEqual([m["tool_call_id"] for m in latest if m["role"] == "tool"], ["two"])

    def test_empty_and_oversized_tasks(self):
        agent, _ = self.agent([])
        for task in (" ", "x" * 12001):
            with self.assertRaises(AgentError):
                agent.run(task)
        self.assertEqual(len(agent.messages), 1)

    def test_demo_uses_real_tools_and_discloses_limitations(self):
        agent = ReviewAgent(DemoClient(), self.tools, self.settings)
        result = agent.run(review_task("a.py", "检查问题"))
        self.assertEqual(result.tool_calls, 3)
        self.assertIn("可变对象", result.report)
        self.assertIn("没有调用 LLM", result.report)
        followup = agent.run("怎么修复？")
        self.assertIn("不具备自由问答能力", followup.report)


if __name__ == "__main__":
    unittest.main()
