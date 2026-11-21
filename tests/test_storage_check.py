"""Storage that is checked, not assumed (roadmap 1.7, ADR-036): reading the mount table and judging the data folder.

The quality report of 2026-11-19 (page 4) found that any ``NEURON_FLOW_DATA_DIR`` made the storage "persistent", so a
wrong path or a disk that is not attached would let the page say "ถาวร" while every deploy still empties the queue.
The mount tables below are written by hand in the kernel's format (proc(5)): a container with a named volume as in
*Service container*, the same container without one, a tmpfs, stacked mounts and escaped mount points.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import settings as settings_module
from app.settings import (NOT_CHECKED, STORAGE_CHECK_RESULTS, TEMPORARY_FILESYSTEMS, Settings, StorageCheck,
                          check_storage, parse_mountinfo)

ROOT = ("612 535 0:58 / / rw,relatime master:301 - overlay overlay rw,lowerdir=/var/lib/docker/overlay2/l/A:"
        "/var/lib/docker/overlay2/l/B,upperdir=/var/lib/docker/overlay2/c/diff,workdir=/var/lib/docker/overlay2/c/work")
PROC = "613 612 0:61 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw"
DEV = "614 612 0:62 / /dev rw,nosuid - tmpfs tmpfs rw,size=65536k,mode=755"
RESOLV = ("620 612 8:1 /var/lib/docker/containers/c1/resolv.conf /etc/resolv.conf rw,relatime - ext4 /dev/root "
          "rw,discard,errors=remount-ro")
VOLUME = ("619 612 8:1 /var/lib/docker/volumes/nf-data/_data /var/data rw,relatime master:1 - ext4 /dev/root "
          "rw,discard,errors=remount-ro")
TMPFS = "621 612 0:70 / /var/data rw,nosuid,nodev,noexec,relatime - tmpfs tmpfs rw,size=65536k"


def table(*lines):
    return "\n".join(lines) + "\n"


WITH_VOLUME = table(ROOT, PROC, DEV, VOLUME, RESOLV)
PLAIN_FOLDER = table(ROOT, PROC, DEV, RESOLV)


class ParseTests(unittest.TestCase):
    def test_mount_points_and_types_in_file_order(self):
        self.assertEqual(parse_mountinfo(WITH_VOLUME), [("/", "overlay"), ("/proc", "proc"), ("/dev", "tmpfs"),
                                                        ("/var/data", "ext4"), ("/etc/resolv.conf", "ext4")])

    def test_optional_fields_may_be_none_or_several(self):
        none = "27 1 254:0 / / rw,relatime - ext4 /dev/vda rw,discard"
        several = "30 27 8:2 / /srv rw,relatime shared:5 master:2 propagate_from:1 - xfs /dev/sdb rw"
        self.assertEqual(parse_mountinfo(table(none, several)), [("/", "ext4"), ("/srv", "xfs")])

    def test_escaped_mount_points_are_read_back(self):
        line = r"40 27 8:3 / /mnt/my\040disk\011two\134x rw,relatime - ext4 /dev/sdc rw"
        self.assertEqual(parse_mountinfo(line), [("/mnt/my disk\ttwo\\x", "ext4")])

    def test_lines_that_do_not_fit_are_skipped(self):
        broken = ["", "garbage", "1 2 3", "1 2 3:4 / /a rw no-separator-here ext4", "1 2 3:4 / /b rw -",
                  "1 2 3:4 / relative rw - ext4 /dev/x rw"]
        self.assertEqual(parse_mountinfo(table(*broken, VOLUME)), [("/var/data", "ext4")])


class CheckTests(unittest.TestCase):
    def test_a_folder_on_its_own_disk_is_confirmed(self):
        # *Service container* runs the image with a named volume at /var/data, as render.yaml's paid variant would.
        for folder in ("/var/data", "/var/data/neuron"):
            with self.subTest(folder=folder):
                self.assertEqual(check_storage(folder, WITH_VOLUME), StorageCheck("confirmed", "ext4"))

    def test_a_plain_folder_in_the_container_is_on_the_root_filesystem(self):
        # The report's risk: NEURON_FLOW_DATA_DIR set, no disk attached.
        self.assertEqual(check_storage("/var/data", PLAIN_FOLDER), StorageCheck("root_filesystem", "overlay"))
        root_disk = table("27 1 254:0 / / rw,relatime - ext4 /dev/vda rw")  # not a container: still not confirmed
        self.assertEqual(check_storage("/srv/data", root_disk), StorageCheck("root_filesystem", "ext4"))

    def test_a_memory_or_layer_filesystem_is_temporary(self):
        self.assertEqual(check_storage("/var/data", table(ROOT, TMPFS)), StorageCheck("temporary_filesystem", "tmpfs"))
        for filesystem in sorted(TEMPORARY_FILESYSTEMS):
            with self.subTest(filesystem=filesystem):
                line = f"700 612 0:80 / /var/data rw,relatime - {filesystem} none rw"
                self.assertEqual(check_storage("/var/data", table(ROOT, line)).result, "temporary_filesystem")

    def test_a_mount_point_holds_whole_path_parts_only(self):
        # /var/data2 is not inside the volume mounted at /var/data.
        self.assertEqual(check_storage("/var/data2", WITH_VOLUME).result, "root_filesystem")
        self.assertEqual(check_storage("/var", WITH_VOLUME).result, "root_filesystem")

    def test_the_mount_on_top_wins(self):
        self.assertEqual(check_storage("/var/data", table(ROOT, VOLUME, TMPFS)).result, "temporary_filesystem")
        self.assertEqual(check_storage("/var/data", table(ROOT, TMPFS, VOLUME)).result, "confirmed")

    def test_an_escaped_mount_point_still_holds_its_folder(self):
        line = r"40 612 8:3 / /mnt/my\040disk rw,relatime - ext4 /dev/sdc rw"
        self.assertEqual(check_storage("/mnt/my disk/data", table(ROOT, line)), StorageCheck("confirmed", "ext4"))

    def test_without_a_mount_table_nothing_is_confirmed(self):
        self.assertEqual(check_storage("/var/data", ""), StorageCheck("mount_table_unreadable"))
        self.assertEqual(check_storage("/var/data", "garbage\n"), StorageCheck("mount_table_unreadable"))
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(settings_module, "MOUNTINFO", Path(folder) / "missing"):
            self.assertEqual(check_storage("/var/data"), StorageCheck("mount_table_unreadable"))

    def test_an_odd_filesystem_name_is_not_passed_on(self):
        line = "700 612 0:80 / /var/data rw,relatime - fs<b>name none rw"
        self.assertEqual(check_storage("/var/data", table(ROOT, line)), StorageCheck("confirmed", "other"))

    def test_this_machines_own_table_gives_a_known_result(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn(check_storage(Path(folder).resolve()).result, STORAGE_CHECK_RESULTS)

    def test_every_result_is_listed_for_the_page(self):
        seen = {check_storage("/var/data", WITH_VOLUME).result, check_storage("/var/data", PLAIN_FOLDER).result,
                check_storage("/var/data", table(ROOT, TMPFS)).result, check_storage("/var/data", "").result,
                NOT_CHECKED.result, Settings.from_env({}).storage_check.result}
        self.assertEqual(seen, set(STORAGE_CHECK_RESULTS))


class SettingsTests(unittest.TestCase):
    def test_persistent_only_when_the_folder_is_confirmed(self):
        on_disk = Settings.from_env({"NEURON_FLOW_DATA_DIR": "/var/data"}, mountinfo=WITH_VOLUME)
        self.assertEqual((on_disk.storage, on_disk.storage_check.result, on_disk.persistent),
                         ("configured", "confirmed", True))
        plain = Settings.from_env({"NEURON_FLOW_DATA_DIR": "/var/data"}, mountinfo=PLAIN_FOLDER)
        self.assertEqual((plain.storage, plain.storage_check.result, plain.persistent),
                         ("configured", "root_filesystem", False))
        railway = Settings.from_env({"RAILWAY_VOLUME_MOUNT_PATH": "/var/data"}, mountinfo=WITH_VOLUME)
        self.assertEqual((railway.storage, railway.persistent), ("railway_volume", True))

    def test_the_local_default_reads_no_mount_table(self):
        with mock.patch.object(settings_module, "check_storage", side_effect=AssertionError("read the table")):
            local = Settings.from_env({}, mountinfo=WITH_VOLUME)
        self.assertEqual((local.storage, local.storage_check.result, local.persistent),
                         ("local_default", "not_configured", False))

    def test_settings_built_by_hand_are_never_persistent(self):
        built = Settings(data_dir=Path("/var/data"), storage="configured")
        self.assertEqual((built.storage_check, built.persistent), (NOT_CHECKED, False))
        confirmed_local = Settings(data_dir=Path("/var/data"), storage="local_default",
                                   storage_check=StorageCheck("confirmed", "ext4"))
        self.assertFalse(confirmed_local.persistent)


if __name__ == "__main__":
    unittest.main()
