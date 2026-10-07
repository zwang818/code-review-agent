import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_review_agent.cli import main, write_report
from code_review_agent.errors import AgentError


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "example with space.py").write_text("x = 1\n")
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, args, inputs=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch("builtins.input", side_effect=inputs or ["/exit"]):
            code = main(args + ["--env-file", str(self.root / "missing.env")])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_demo_cli_exports_report_without_key(self):
        report = self.root / "reports" / "review.md"
        code, out, err = self.invoke(["--demo", "--root", str(self.root), "example with space.py",
                                      "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertIn("有限规则未发现问题", out)
        self.assertIn("[工具]", err)
        self.assertEqual(report.read_text(), out)

    def test_real_mode_missing_key_explains_next_step(self):
        code, _, err = self.invoke(["--root", str(self.root), "example with space.py"])
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_API_KEY", err)
        self.assertNotIn("Traceback", err)

    def test_invalid_target_has_nonzero_exit(self):
        code, _, err = self.invoke(["--demo", "--root", str(self.root), "missing.py"])
        self.assertEqual(code, 1)
        self.assertIn("不存在", err)

    def test_chat_review_followup_reset_and_exit(self):
        code, out, err = self.invoke(["--demo", "--chat", "--root", str(self.root)],
                                    ["/review example with space.py", "解释问题", "/reset", "/save no.md", "/exit"])
        self.assertEqual(code, 0)
        self.assertIn("不具备自由问答能力", out)
        self.assertIn("已清空", out)
        self.assertIn("还没有可保存", err)

    def test_report_does_not_overwrite(self):
        path = self.root / "report.md"
        write_report(str(path), "first")
        with self.assertRaises(AgentError):
            write_report(str(path), "second")
        self.assertEqual(path.read_text(), "first\n")


if __name__ == "__main__":
    unittest.main()
