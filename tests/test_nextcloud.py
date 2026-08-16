from __future__ import annotations

import unittest
from unittest import mock

from hcr2.integrations import nextcloud


class NextcloudIntegrationTests(unittest.TestCase):
    def test_match_sheet_remote_path(self) -> None:
        self.assertEqual(
            nextcloud.match_sheet_remote_path(62, "12_Event_Opponent.xlsx").as_posix(),
            "Power-Ladys-Scores/Team-Event/S62/12_Event_Opponent.xlsx",
        )

    def test_remote_url_normalizes_leading_slash(self) -> None:
        with mock.patch.object(nextcloud, "NEXTCLOUD_AUTH", ("user", "secret")):
            self.assertEqual(
                nextcloud.remote_url("/Power-Ladys-Scores/Ladys/Ladys.xlsx"),
                "http://192.168.178.101:8080/remote.php/dav/files/user/Power-Ladys-Scores/Ladys/Ladys.xlsx",
            )
