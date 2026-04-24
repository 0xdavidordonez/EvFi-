import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

import evfi_fleet_core as core


class GamificationLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "evfi_test.db")
        self.original_db_path = core.DB_PATH
        self.original_now_ts = core.now_ts
        core.DB_PATH = self.db_path
        core.init_db()
        self.user = core.get_or_create_user("0x1111111111111111111111111111111111111111")

    def tearDown(self):
        core.now_ts = self.original_now_ts
        core.DB_PATH = self.original_db_path
        self.tmp_dir.cleanup()

    def _set_now(self, dt_value):
        ts = int(dt_value.timestamp())
        core.now_ts = lambda: ts
        return ts

    def _fetch_one(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        conn.close()
        return row

    def test_streak_increment_once_per_day_and_reset_after_gap(self):
        user_id = self.user["id"]

        first = core.updateDailyActivity(user_id, "2026-04-20", "login")
        self.assertEqual(first["streak"]["currentStreak"], 1)
        self.assertTrue(first["streak"]["streakIncreased"])

        same_day = core.updateDailyActivity(user_id, "2026-04-20", "reward_check")
        self.assertEqual(same_day["streak"]["currentStreak"], 1)
        self.assertFalse(same_day["streak"]["streakIncreased"])

        next_day = core.updateDailyActivity(user_id, "2026-04-21", "sync")
        self.assertEqual(next_day["streak"]["currentStreak"], 2)
        self.assertTrue(next_day["streak"]["streakIncreased"])

        after_gap = core.updateDailyActivity(user_id, "2026-04-23", "sync")
        self.assertEqual(after_gap["streak"]["currentStreak"], 1)
        self.assertTrue(after_gap["streak"]["streakReset"])

    def test_challenge_rollover_archives_previous_window(self):
        user_id = self.user["id"]
        monday = datetime(2026, 4, 20, 10, 0, 0)
        monday_ts = self._set_now(monday)
        core.processTelemetrySync(
            user_id,
            {
                "synced_at": monday_ts,
                "odometer": 1230.0,
                "miles_delta": 30.0,
                "verified_miles": 30.0,
            },
        )
        first_state = core.getGamificationState(user_id)
        drive = next((x for x in first_state["challenges"] if x["challenge_key"] == "drive_25_miles_weekly"), None)
        self.assertIsNotNone(drive)
        self.assertEqual(int(drive["completed"]), 1)
        first_window_key = drive["window_key"]

        next_week = datetime(2026, 4, 27, 10, 0, 0)
        self._set_now(next_week)
        core.updateChallengeProgress(user_id, {"verified_miles": 0.0})

        second_state = core.getGamificationState(user_id)
        drive_new = next((x for x in second_state["challenges"] if x["challenge_key"] == "drive_25_miles_weekly"), None)
        self.assertIsNotNone(drive_new)
        self.assertEqual(float(drive_new["progress"]), 0.0)
        self.assertEqual(int(drive_new["completed"]), 0)
        self.assertNotEqual(drive_new["window_key"], first_window_key)

        archived = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM gamification_challenge_windows
            WHERE user_id = ? AND challenge_key = ? AND active = 0
            """,
            (user_id, "drive_25_miles_weekly"),
        )
        self.assertGreaterEqual(int(archived["total"]), 1)

    def test_badges_are_not_duplicated_and_persist(self):
        user_id = self.user["id"]
        base_ts = self._set_now(datetime(2026, 4, 20, 9, 0, 0))
        core.processTelemetrySync(
            user_id,
            {
                "synced_at": base_ts,
                "odometer": 1005.0,
                "miles_delta": 5.0,
                "verified_miles": 5.0,
            },
        )
        core.awardEligibleBadges(user_id)
        core.awardEligibleBadges(user_id)

        count = self._fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM gamification_badges
            WHERE user_id = ? AND badge_key = 'first_sync'
            """,
            (user_id,),
        )
        self.assertEqual(int(count["total"]), 1)

        # Persistence check via fresh state read after later activity day.
        core.updateDailyActivity(user_id, "2026-04-21", "login")
        state = core.getGamificationState(user_id)
        badge_keys = {row["badge_key"] for row in state["badges"]}
        self.assertIn("first_sync", badge_keys)

    def test_anti_abuse_speed_and_interval_checks_block_scoring(self):
        user_id = self.user["id"]
        vehicle_id = "veh-1"
        base = int(datetime(2026, 4, 20, 8, 0, 0).timestamp())

        too_fast = core.validate_trip_for_scoring(
            user_id,
            vehicle_id,
            miles_added=220.0,
            previous_synced_at=base,
            synced_at=base + 3600,
        )
        self.assertEqual(too_fast, 0.0)

        too_frequent = core.validate_trip_for_scoring(
            user_id,
            vehicle_id,
            miles_added=10.0,
            previous_synced_at=base,
            synced_at=base + 30,
        )
        self.assertEqual(too_frequent, 0.0)


if __name__ == "__main__":
    unittest.main()
