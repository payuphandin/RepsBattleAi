import math
import secrets
import string
import time
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock


ROOM_CODE_LENGTH = 6
ROOM_CODE_CHARACTERS = string.ascii_uppercase + "23456789"
MATCH_DURATION_SECONDS = 60
MATCH_COUNTDOWN_SECONDS = 5

# Prototype storage: rooms are cleared whenever the API process restarts.
rooms: dict[str, dict] = {}
# Track active WebSocket ownership separately so an old socket's close event
# cannot mark a newer reconnection as disconnected.
player_connections: dict[tuple[str, str], str] = {}
_rooms_lock = Lock()


class RoomNotFoundError(Exception):
    pass


class RoomFullError(Exception):
    pass


class RoomPlayerNotFoundError(Exception):
    pass


class RoomPermissionError(Exception):
    pass


class RoomNotReadyError(Exception):
    pass


class RoomPlayersNotConnectedError(Exception):
    pass


def _generate_room_code() -> str:
    while True:
        code = "".join(
            secrets.choice(ROOM_CODE_CHARACTERS)
            for _ in range(ROOM_CODE_LENGTH)
        )
        if code not in rooms:
            return code


def _refresh_room_state(room: dict) -> None:
    now = time.time()
    status = room["status"]

    if status == "countdown" and now >= room["start_at"]:
        room["status"] = "running"
        status = "running"

    if status == "running" and now >= room["end_at"]:
        room["status"] = "finished"
        scores = [player["reps"] for player in room["players"]]

        if scores[0] > scores[1]:
            room["winner_player_id"] = room["players"][0]["player_id"]
            room["result"] = "winner"
        elif scores[1] > scores[0]:
            room["winner_player_id"] = room["players"][1]["player_id"]
            room["result"] = "winner"
        else:
            room["winner_player_id"] = None
            room["result"] = "draw"

        status = "finished"

    if status == "countdown":
        room["remaining_seconds"] = max(
            0,
            math.ceil(room["start_at"] - now),
        )
    elif status == "running":
        room["remaining_seconds"] = max(
            0,
            math.ceil(room["end_at"] - now),
        )
    elif status == "finished":
        room["remaining_seconds"] = 0
    else:
        room["remaining_seconds"] = None


def create_room(host_name: str) -> dict:
    with _rooms_lock:
        room_code = _generate_room_code()
        player_id = secrets.token_urlsafe(16)

        room = {
            "room_code": room_code,
            "status": "waiting",
            "max_players": 2,
            "duration_seconds": MATCH_DURATION_SECONDS,
            "countdown_seconds": MATCH_COUNTDOWN_SECONDS,
            "remaining_seconds": None,
            "start_at": None,
            "end_at": None,
            "winner_player_id": None,
            "result": None,
            "players": [
                {
                    "player_id": player_id,
                    "name": host_name,
                    "role": "host",
                    "reps": 0,
                    "connected": False,
                }
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        rooms[room_code] = room
        _refresh_room_state(room)

        return {
            "room": deepcopy(room),
            "player_id": player_id,
        }


def join_room(room_code: str, player_name: str) -> dict:
    with _rooms_lock:
        room = rooms.get(room_code.upper())
        if room is None:
            raise RoomNotFoundError

        _refresh_room_state(room)

        if len(room["players"]) >= room["max_players"]:
            raise RoomFullError

        if room["status"] != "waiting":
            raise RoomNotReadyError

        player_id = secrets.token_urlsafe(16)
        room["players"].append({
            "player_id": player_id,
            "name": player_name,
            "role": "guest",
            "reps": 0,
            "connected": False,
        })

        room["status"] = "ready"
        _refresh_room_state(room)

        return {
            "room": deepcopy(room),
            "player_id": player_id,
        }


def _find_player(room_code: str, player_id: str) -> dict:
    room = rooms.get(room_code.upper())
    if room is None:
        raise RoomNotFoundError

    for player in room["players"]:
        if player["player_id"] == player_id:
            return player

    raise RoomPlayerNotFoundError


def start_match(room_code: str, player_id: str) -> dict:
    with _rooms_lock:
        room = rooms.get(room_code.upper())
        if room is None:
            raise RoomNotFoundError

        _refresh_room_state(room)
        player = _find_player(room_code, player_id)

        if player["role"] != "host":
            raise RoomPermissionError

        if room["status"] != "ready" or len(room["players"]) != 2:
            raise RoomNotReadyError

        if not all(member["connected"] for member in room["players"]):
            raise RoomPlayersNotConnectedError

        now = time.time()
        room["start_at"] = now + MATCH_COUNTDOWN_SECONDS
        room["end_at"] = room["start_at"] + room["duration_seconds"]
        room["status"] = "countdown"
        room["winner_player_id"] = None
        room["result"] = None
        room["players"] = [
            {**member, "reps": 0}
            for member in room["players"]
        ]
        _refresh_room_state(room)

        return {
            "room": deepcopy(room),
            "player_id": player_id,
        }


def get_room(room_code: str) -> dict | None:
    with _rooms_lock:
        room = rooms.get(room_code.upper())
        if room is None:
            return None

        _refresh_room_state(room)
        return deepcopy(room)


def set_player_connected(
    room_code: str,
    player_id: str,
    connected: bool,
    connection_id: str | None = None,
) -> str | None:
    with _rooms_lock:
        player = _find_player(room_code, player_id)
        connection_key = (room_code.upper(), player_id)

        if connected:
            active_connection_id = connection_id or secrets.token_urlsafe(16)
            player_connections[connection_key] = active_connection_id
            player["connected"] = True
            return active_connection_id

        # Ignore a stale disconnect from a socket that has already been
        # replaced by a newer connection for the same player.
        current_connection_id = player_connections.get(connection_key)
        if connection_id is None or current_connection_id == connection_id:
            player_connections.pop(connection_key, None)
            player["connected"] = False

        return None


def update_player_reps(
    room_code: str,
    player_id: str,
    reps: int,
) -> None:
    with _rooms_lock:
        room = rooms.get(room_code.upper())
        if room is None:
            raise RoomNotFoundError

        _refresh_room_state(room)
        player = _find_player(room_code, player_id)

        # Accept score updates only while the server-authoritative match is running.
        if room["status"] == "running":
            player["reps"] = max(0, int(reps))
