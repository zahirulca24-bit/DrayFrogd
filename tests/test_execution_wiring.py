import unittest

import app.main as main_module
from app.execution import execute_signal
from app.risk_execution import execute_signal as compatibility_execute_signal


class ExecutionWiringTests(unittest.TestCase):
    def test_api_and_background_compatibility_entrypoints_share_one_executor(self) -> None:
        self.assertIs(main_module.execute_signal, execute_signal)
        self.assertIs(compatibility_execute_signal, execute_signal)


if __name__ == "__main__":
    unittest.main()
