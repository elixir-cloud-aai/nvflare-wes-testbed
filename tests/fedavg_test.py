"""Unit tests of `wes/fedavg.py`, the plain FedAvg workflow (test T10). No network, no NumPy.

Usage: python3 tests/fedavg_test.py
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from wes import fedavg


def stdout(*updates: dict[str, object], noise: str = "") -> str:
    """Build what a site's task prints.

    Args:
        *updates: The update lines, in order.
        noise: Other output before them.

    Returns:
        The output.
    """
    return noise + "".join(f"{fedavg.MARKER}{json.dumps(update)}\n" for update in updates)


class RoundsTest(unittest.TestCase):
    """The number of rounds a run asks for."""

    def test_default(self) -> None:
        """Without `rounds`, the same as the NVFlare job (T1)."""
        self.assertEqual(fedavg.parse_rounds({}), fedavg.DEFAULT_ROUNDS)
        self.assertEqual(fedavg.DEFAULT_ROUNDS, 5)

    def test_given(self) -> None:
        """A number in range is taken as it is."""
        self.assertEqual(fedavg.parse_rounds({"rounds": 1}), 1)
        self.assertEqual(fedavg.parse_rounds({"rounds": fedavg.MAX_ROUNDS}), fedavg.MAX_ROUNDS)

    def test_refused(self) -> None:
        """Anything else is refused, with a message that names the range."""
        for value in (0, -1, fedavg.MAX_ROUNDS + 1, 2.5, "3", True, None, [3]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "rounds"):
                fedavg.parse_rounds({"rounds": value})


class WorkloadTest(unittest.TestCase):
    """The workloads in the image."""

    def test_known(self) -> None:
        """`logreg` starts from the same model as the NVFlare job."""
        self.assertEqual(fedavg.workload("logreg").initial, [0.0, 0.0, 0.0])

    def test_unknown(self) -> None:
        """Anything else, paths included, is refused, naming what there is."""
        for name in ("", "logreg-fedavg", "../logreg", "/app/testset/fedavg/site_round.py"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "logreg"):
                fedavg.workload(name)


class SiteTaskTest(unittest.TestCase):
    """The TES task of one site in one round."""

    def setUp(self) -> None:
        """Build the task of site 1 in round 3."""
        self.task = fedavg.site_task(
            "0123456789abcdef", "site-1", 3, [0.5, -1.0, 0.25], "file:///data/site-1.csv", "img:1", "logreg"
        )

    def test_inputs(self) -> None:
        """The data by its URL at the site, and the model inline: nothing to fetch from the hub."""
        inputs = {entry["name"]: entry for entry in self.task["inputs"]}
        self.assertEqual(set(inputs), {"data", "model"})
        self.assertEqual(inputs["data"]["url"], "file:///data/site-1.csv")
        self.assertNotIn("url", inputs["model"])
        self.assertEqual(json.loads(inputs["model"]["content"]), [0.5, -1.0, 0.25])

    def test_no_secret_and_no_address(self) -> None:
        """No token, link or address of the hub in the record: only the data URL is a URL at all."""
        text = json.dumps(self.task)
        self.assertEqual(text.count("://"), 1)
        self.assertNotIn("token", text.lower())

    def test_executor(self) -> None:
        """The workload's script, on the paths of the inputs."""
        executor = self.task["executors"][0]
        self.assertEqual(executor["image"], "img:1")
        self.assertEqual(executor["command"][:2], ["python3", "/app/testset/fedavg/site_round.py"])
        paths = {entry["path"] for entry in self.task["inputs"]}
        self.assertTrue(paths <= set(executor["command"]))

    def test_tags(self) -> None:
        """Tags name the run, the site and the round."""
        self.assertEqual(self.task["tags"], {"wes_run_id": "0123456789abcdef", "site": "site-1", "round": "3"})
        self.assertIn("site-1", self.task["name"])
        self.assertIn("r3", self.task["name"])


class ParseUpdateTest(unittest.TestCase):
    """A site's update, from its task's output."""

    def test_update(self) -> None:
        """The last update line counts, whatever was printed before it."""
        output = stdout({"weights": [9, 9, 9], "rows": 1}, {"weights": [1, -2.5, 0], "rows": 40}, noise="hello\n")
        update = fedavg.parse_update(output, 3)
        self.assertEqual(update, fedavg.Update([1.0, -2.5, 0.0], 40))

    def test_refused(self) -> None:
        """Updates that would break or skew the average are refused, by what's wrong."""
        cases = {
            "no update": "just logs\n",
            "not JSON": f"{fedavg.MARKER}{{weights\n",
            "not an object": stdout([1, 2, 3]),  # type: ignore[arg-type]
            "wrong size": stdout({"weights": [1, 2], "rows": 40}),
            "not numbers": stdout({"weights": ["1", 2, 3], "rows": 40}),
            "booleans": stdout({"weights": [True, 2, 3], "rows": 40}),
            "not finite": f'{fedavg.MARKER}{{"weights": [NaN, 2, 3], "rows": 40}}\n',
            "infinite": f'{fedavg.MARKER}{{"weights": [Infinity, 2, 3], "rows": 40}}\n',
            "an integer too large for a float": f'{fedavg.MARKER}{{"weights": [1{"0" * 400}, 2, 3], "rows": 1}}\n',
            "a weight out of bounds": stdout({"weights": [fedavg.MAX_WEIGHT * 2, 2, 3], "rows": 40}),
            "a float that overflows a sum": stdout({"weights": [1e308, 2, 3], "rows": 40}),
            "no rows": stdout({"weights": [1, 2, 3]}),
            "zero rows": stdout({"weights": [1, 2, 3], "rows": 0}),
            "fractional rows": stdout({"weights": [1, 2, 3], "rows": 1.5}),
            "too many rows": stdout({"weights": [1, 2, 3], "rows": fedavg.MAX_ROWS + 1}),
            "too long": fedavg.MARKER + " " * fedavg.MAX_LINE + "\n",
        }
        for name, output in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                fedavg.parse_update(output, 3)

    def test_message_holds_no_output(self) -> None:
        """A refusal doesn't echo what the task printed."""
        with self.assertRaises(ValueError) as caught:
            fedavg.parse_update(stdout({"weights": ["decoy-output"], "rows": 40}), 3)
        self.assertNotIn("decoy-output", str(caught.exception))


class AggregateTest(unittest.TestCase):
    """Federated averaging of the updates of one round."""

    def test_weighted_by_rows(self) -> None:
        """Each site counts by its rows."""
        result = fedavg.aggregate([fedavg.Update([1.0, 0.0], 30), fedavg.Update([5.0, 4.0], 10)])
        self.assertEqual(result, [2.0, 1.0])

    def test_equal_rows(self) -> None:
        """With equal rows, the plain mean, as NVFlare's FedAvg in the job of T1."""
        result = fedavg.aggregate([fedavg.Update([1.0, -1.0, 2.0], 40), fedavg.Update([3.0, 1.0, 0.0], 40)])
        self.assertEqual(result, [2.0, 0.0, 1.0])

    def test_bounds_keep_the_average_finite(self) -> None:
        """Updates at the bounds, of the most rows, still average to finite numbers."""
        extreme = fedavg.Update([fedavg.MAX_WEIGHT, -fedavg.MAX_WEIGHT], fedavg.MAX_ROWS)
        self.assertEqual(fedavg.aggregate([extreme] * 10), [fedavg.MAX_WEIGHT, -fedavg.MAX_WEIGHT])

    def test_not_finite(self) -> None:
        """An average that isn't finite is refused, should updates get past the bounds."""
        with self.assertRaisesRegex(ValueError, "finite"):
            fedavg.aggregate([fedavg.Update([1e308], 10), fedavg.Update([1e308], 10)])

    def test_no_updates(self) -> None:
        """No update, no model."""
        with self.assertRaises(ValueError):
            fedavg.aggregate([])


class TaskOutputTest(unittest.TestCase):
    """The output of a task, from its full TES record."""

    def test_last_executor(self) -> None:
        """The last log of the last attempt."""
        record = {"logs": [{"logs": [{"stdout": "old"}]}, {"logs": [{"stdout": "a"}, {"stdout": "b"}]}]}
        self.assertEqual(fedavg.task_stdout(record), "b")

    def test_missing(self) -> None:
        """No logs, or no output, is an empty output."""
        for record in ({}, {"logs": []}, {"logs": [{}]}, {"logs": [{"logs": [{}]}]}, {"logs": None}):
            with self.subTest(record=record):
                self.assertEqual(fedavg.task_stdout(record), "")

    def test_malformed(self) -> None:
        """A record of the wrong shape is refused as a bad output, not as a crash."""
        records = (
            ["not", "an", "object"],
            {"logs": {"a": 1}},
            {"logs": ["x"]},
            {"logs": [{"logs": {"k": 1}}]},
            {"logs": [{"logs": ["x"]}]},
            {"logs": [{"logs": [{"stdout": 5}]}]},
        )
        for record in records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                fedavg.task_stdout(record)


if __name__ == "__main__":
    unittest.main()
