import sys
import tempfile
import unittest
from pathlib import Path

from officediff.render import RenderError, _rasterize


class RenderBudgetTests(unittest.TestCase):
    def test_stops_rasterizer_while_it_exceeds_the_byte_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generated = output / "page-1.png"
            script = (
                "from pathlib import Path; import time; "
                f"Path({str(generated)!r}).write_bytes(b'x' * 1048576); "
                "time.sleep(5)"
            )
            with self.assertRaisesRegex(RenderError, "output safety limit"):
                _rasterize([sys.executable, "-c", script], output, maximum=1024)


if __name__ == "__main__":
    unittest.main()
