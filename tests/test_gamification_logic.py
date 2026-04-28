import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest import mock

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

    def _insert_reward_event(self, vehicle_id, synced_at, miles):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reward_events
            (user_id, tesla_vehicle_id, odometer_reading, miles_added, verified_miles, drv_earned, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (self.user["id"], vehicle_id, 1000.0 + miles, miles, miles, miles, synced_at),
        )
        conn.commit()
        conn.close()

    def _insert_charge_session(self, synced_at):
        conn = core.get_db_connection()
        cur = conn.cursor()
        core.append_charge_session_record(
            cur,
            self.user["id"],
            {
                "session_start_ts": synced_at,
                "session_end_ts": synced_at + 1800,
                "last_synced_at": synced_at + 1800,
                "start_battery": 55.0,
                "end_battery": 70.0,
                "max_battery": 70.0,
                "snapshot_count": 2,
                "avg_charge_rate": 7.2,
                "max_charge_rate": 7.2,
                "offpeak": True,
            },
        )
        conn.commit()
        conn.close()

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

    def test_validate_trip_allows_reasonable_daily_syncs(self):
        user_id = self.user["id"]
        vehicle_id = "veh-2"
        base = int(datetime(2026, 4, 20, 8, 0, 0).timestamp())

        verified = core.validate_trip_for_scoring(
            user_id,
            vehicle_id,
            miles_added=75.66,
            previous_synced_at=base,
            synced_at=base + 86400,
        )
        self.assertAlmostEqual(verified, 75.66)

    def test_sync_vehicle_rewards_records_raw_and_verified_miles_separately(self):
        wallet = self.user["wallet_address"]
        vehicle_id = "veh-3"
        vin = "5YJTESTEVFI00001"
        first_sync = int(datetime(2026, 4, 20, 8, 0, 0).timestamp())
        second_sync = int(datetime(2026, 4, 21, 8, 0, 0).timestamp())

        with mock.patch.object(core.time, "time", return_value=first_sync):
            core.sync_vehicle_rewards(vehicle_id, "Model Y", vin, 124313.78, wallet_address=wallet)
        with mock.patch.object(core.time, "time", return_value=second_sync):
            core.sync_vehicle_rewards(vehicle_id, "Model Y", vin, 124389.44, wallet_address=wallet)

        latest = self._fetch_one(
            """
            SELECT miles_added, verified_miles, drv_earned, odometer_reading
            FROM reward_events
            WHERE tesla_vehicle_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (vehicle_id,),
        )
        self.assertAlmostEqual(float(latest["odometer_reading"]), 124389.44)
        self.assertAlmostEqual(float(latest["miles_added"]), 75.66, places=2)
        self.assertAlmostEqual(float(latest["verified_miles"]), 75.66, places=2)
        self.assertAlmostEqual(float(latest["drv_earned"]), 75.66, places=2)

    def test_reward_event_history_repair_backfills_raw_mileage(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO reward_events
            (user_id, tesla_vehicle_id, odometer_reading, miles_added, verified_miles, drv_earned, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (self.user["id"], "veh-4", 124313.78, 0.0, None, 0.0, int(datetime(2026, 4, 22, 8, 0, 0).timestamp())),
                (self.user["id"], "veh-4", 124389.44, 0.0, None, 0.0, int(datetime(2026, 4, 23, 8, 0, 0).timestamp())),
                (self.user["id"], "veh-4", 124437.64, 0.0, None, 0.0, int(datetime(2026, 4, 24, 8, 0, 0).timestamp())),
            ],
        )
        core.repair_reward_event_history(conn)
        conn.commit()
        conn.close()

        repaired = self._fetch_one(
            """
            SELECT miles_added, verified_miles
            FROM reward_events
            WHERE tesla_vehicle_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("veh-4",),
        )
        self.assertAlmostEqual(float(repaired["miles_added"]), 48.2, places=2)
        self.assertAlmostEqual(float(repaired["verified_miles"]), 0.0, places=2)

    def test_weekly_reward_estimate_uses_bootstrap_floor(self):
        week_start = int(datetime(2026, 4, 20, 0, 0, 0).timestamp())
        week_end = week_start + 604799
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO weekly_scores
            (user_id, vin, week_start, week_end, verified_miles, active_days, charge_health_score, streak_multiplier, mission_bonus, total_score, created_at, score_breakdown_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (self.user["id"], "VINBOOTSTRAP", week_start, week_end, 0.0, 0, 0.0, 1.0, 0.0, 250.0, week_start, "{}"),
        )
        conn.commit()
        conn.close()

        preview = core.estimate_weekly_reward(250.0, week_start, week_end)
        self.assertEqual(float(preview["actual_network_score"]), 250.0)
        self.assertEqual(float(preview["effective_network_score"]), float(core.WEEKLY_SCORE_BOOTSTRAP_FLOOR))
        self.assertEqual(float(preview["estimated_evfi"]), 250.0)

    def test_mission_bonus_is_capped_by_real_weekly_activity(self):
        self._set_now(datetime(2026, 4, 20, 9, 0, 0))
        week_start, _ = core.current_week_bounds()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO missions (user_id, mission_type, progress, completed, completed_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (self.user["id"], "stay_active_all_week", 7.0, week_start),
        )
        conn.commit()
        conn.close()

        score = core.calculate_weekly_score(self.user["id"], "VINCAP", "veh-cap")
        self.assertEqual(float(score["total_score"]), 0.0)
        self.assertEqual(float(score["mission_bonus"]), 0.0)

    def test_onboarding_airdrop_is_fixed_and_normalizes_legacy_claim(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO claims (user_id, week_start, week_end, score, evfi_allocated, claimed, claimed_at)
            VALUES (?, 0, 0, ?, ?, 0, NULL)
            """,
            (self.user["id"], 123456.78, 123456.78),
        )
        conn.commit()
        conn.close()

        claim = core.ensure_airdrop_claim(self.user["id"], 123456.78)
        self.assertEqual(float(claim["evfi_allocated"]), float(core.ONBOARDING_AIRDROP_EVFI))

    def test_weekly_score_persists_breakdown_json_for_dashboard(self):
        user_id = self.user["id"]
        sync_ts = self._set_now(datetime(2026, 4, 20, 9, 0, 0))
        core.processTelemetrySync(
            user_id,
            {
                "synced_at": sync_ts,
                "odometer": 1500.0,
                "miles_delta": 12.0,
                "verified_miles": 12.0,
                "battery_level": 72.0,
                "charging_state": "Charging",
                "charge_rate": 7.2,
                "efficiency_whmi": 245.0,
            },
        )
        self._insert_reward_event("veh-breakdown", sync_ts, 12.0)
        score = core.calculate_weekly_score(user_id, "VINBREAKDOWN", "veh-breakdown")
        breakdown = core.extract_weekly_score_breakdown(score)

        self.assertIn("score_breakdown_json", score.keys())
        self.assertGreaterEqual(float(breakdown["verifiedMiles"]), 12.0)
        self.assertGreaterEqual(float(breakdown["totalScore"]), 0.0)

    def test_weekly_score_breakdown_uses_richer_charging_signals(self):
        user_id = self.user["id"]
        sync_ts = self._set_now(datetime(2026, 4, 20, 23, 0, 0))
        core.processTelemetrySync(
            user_id,
            {
                "synced_at": sync_ts,
                "odometer": 2200.0,
                "miles_delta": 8.0,
                "verified_miles": 8.0,
                "battery_level": 70.0,
                "charging_state": "Charging",
                "charge_rate": 7.2,
                "efficiency_whmi": 230.0,
            },
        )
        self._insert_reward_event("veh-charge", sync_ts, 8.0)
        self._insert_charge_session(sync_ts)
        score = core.calculate_weekly_score(user_id, "VINCHARGE", "veh-charge")
        breakdown = core.extract_weekly_score_breakdown(score)

        self.assertEqual(int(breakdown["healthyChargeSessions"]), 1)
        self.assertEqual(int(breakdown["offpeakChargeSessions"]), 1)
        self.assertEqual(int(breakdown["acChargeSessions"]), 1)
        self.assertGreater(float(breakdown["chargingScore"]), 0.0)

    def test_utility_redeem_and_stake_affect_balance_and_score(self):
        user_id = self.user["id"]
        core.record_evfi_earning(user_id, "test-earn-1", 500.0, "weekly_allocation")

        redeemed = core.redeem_token_utility(user_id, "premium_weekly_insights")
        self.assertEqual(float(redeemed["amountEvfi"]), 25.0)
        self.assertEqual(float(redeemed["utilityState"]["balance"]["available"]), 475.0)

        with self.assertRaisesRegex(RuntimeError, "App-level staking is disabled"):
            core.stake_evfi_tier(user_id, "bronze")

        with mock.patch.object(
            core,
            "build_onchain_staking_summary",
            return_value={"activeStake": {"boostPct": 5.0}},
        ):
            score = core.calculate_weekly_score(user_id, "VINSTAKE", "veh-stake")
        breakdown = core.extract_weekly_score_breakdown(score)
        self.assertEqual(float(breakdown["stakingBoostPct"]), 5.0)

        with self.assertRaisesRegex(RuntimeError, "App-level unstaking is disabled"):
            core.unstake_evfi(user_id)

    def test_offpeak_hour_logic_handles_overnight_window(self):
        self.assertTrue(core.is_offpeak_hour(23))
        self.assertTrue(core.is_offpeak_hour(2))
        self.assertFalse(core.is_offpeak_hour(14))


if __name__ == "__main__":
    unittest.main()
