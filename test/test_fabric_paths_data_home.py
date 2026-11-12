"""FAA-192 (16): FABRIC_DATA_HOME, an absolute folder on a durable volume, holds a kit service's data folder on a host
whose own disk does not persist (a cloud platform); logs and cache stay where the OS puts them. A relative value is
refused, and without the variable nothing changes. The twin is fabric-paths-data-home.test.mjs."""
import os
import unittest
from pathlib import Path
from unittest import mock

from test_fabric_service import load

fp = load("fabric_paths")


class DataHome(unittest.TestCase):
    def test_unset_changes_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FABRIC_DATA_HOME", None)
            self.assertEqual(fp.service_dirs("example-agent")["data"].name, "example-agent")

    def test_an_absolute_folder_holds_the_data_and_each_instance(self):
        volume = str(Path(os.path.abspath(os.sep)) / "mnt" / "durable")
        with mock.patch.dict(os.environ, {"FABRIC_DATA_HOME": volume}):
            dirs = fp.service_dirs("example-agent")
            self.assertEqual(dirs["data"], Path(volume) / "example-agent")
            self.assertNotEqual(dirs["logs"].parent, Path(volume))
            self.assertEqual(fp.instance_dirs("example-agent", "acme")["data"], Path(volume) / "example-agent.acme")

    def test_a_relative_value_is_refused(self):
        with mock.patch.dict(os.environ, {"FABRIC_DATA_HOME": "data"}):
            with self.assertRaises(fp.ServiceError):
                fp.service_dirs("example-agent")


if __name__ == "__main__":
    unittest.main()
