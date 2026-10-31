import time
import unittest

import room_manager


class RoomManagerTests(unittest.TestCase):
    def setUp(self):
        with room_manager._rooms_lock:
            room_manager.rooms.clear()
            room_manager.player_connections.clear()

    def test_unknown_room_code_is_not_found(self):
        self.assertIsNone(room_manager.get_room("XXXXXX"))

        with self.assertRaises(room_manager.RoomNotFoundError):
            room_manager.join_room("XXXXXX", "Guest")

    def test_room_accepts_two_players_only(self):
        created = room_manager.create_room("Host")
        room_code = created["room"]["room_code"]

        joined = room_manager.join_room(room_code.lower(), "Guest")
        self.assertEqual(joined["room"]["status"], "ready")
        self.assertEqual(len(joined["room"]["players"]), 2)

        with self.assertRaises(room_manager.RoomFullError):
            room_manager.join_room(room_code, "Third Player")

    def test_match_requires_both_players_connected(self):
        created = room_manager.create_room("Host")
        room_code = created["room"]["room_code"]
        joined = room_manager.join_room(room_code, "Guest")

        with self.assertRaises(room_manager.RoomPlayersNotConnectedError):
            room_manager.start_match(room_code, created["player_id"])

        room_manager.set_player_connected(room_code, created["player_id"], True)
        room_manager.set_player_connected(room_code, joined["player_id"], True)

        started = room_manager.start_match(room_code, created["player_id"])
        self.assertEqual(started["room"]["status"], "countdown")

    def test_stale_socket_disconnect_does_not_clear_new_connection(self):
        created = room_manager.create_room("Host")
        room_code = created["room"]["room_code"]
        player_id = created["player_id"]

        old_connection = room_manager.set_player_connected(
            room_code,
            player_id,
            True,
        )
        new_connection = room_manager.set_player_connected(
            room_code,
            player_id,
            True,
        )

        room_manager.set_player_connected(
            room_code,
            player_id,
            False,
            old_connection,
        )

        self.assertTrue(room_manager.get_room(room_code)["players"][0]["connected"])

        room_manager.set_player_connected(
            room_code,
            player_id,
            False,
            new_connection,
        )
        self.assertFalse(room_manager.get_room(room_code)["players"][0]["connected"])

    def test_disconnect_and_reconnect_preserves_score_during_match(self):
        created = room_manager.create_room("Host")
        room_code = created["room"]["room_code"]
        joined = room_manager.join_room(room_code, "Guest")

        room_manager.set_player_connected(room_code, created["player_id"], True)
        room_manager.set_player_connected(room_code, joined["player_id"], True)
        room_manager.start_match(room_code, created["player_id"])

        # Move the countdown clock forward without waiting in the test.
        with room_manager._rooms_lock:
            room = room_manager.rooms[room_code]
            room["start_at"] = time.time() - 1
            room["end_at"] = time.time() + 30

        room_manager.update_player_reps(room_code, created["player_id"], 7)
        room_manager.set_player_connected(room_code, created["player_id"], False)

        disconnected_room = room_manager.get_room(room_code)
        host = disconnected_room["players"][0]
        self.assertFalse(host["connected"])
        self.assertEqual(host["reps"], 7)

        room_manager.set_player_connected(room_code, created["player_id"], True)
        reconnected_room = room_manager.get_room(room_code)
        host = reconnected_room["players"][0]
        self.assertTrue(host["connected"])
        self.assertEqual(host["reps"], 7)


if __name__ == "__main__":
    unittest.main()
