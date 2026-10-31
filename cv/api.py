import asyncio
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pushup_detector import MODEL_PATH, PushUpDetector
from room_manager import (
    RoomFullError,
    RoomNotFoundError,
    RoomPlayerNotFoundError,
    RoomPermissionError,
    RoomNotReadyError,
    RoomPlayersNotConnectedError,
    create_room,
    get_room,
    join_room,
    set_player_connected,
    start_match,
    update_player_reps,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repbattle.cv")

MAX_FRAME_BYTES = 1_500_000
MAX_FRAME_WIDTH = 1280
MAX_FRAME_HEIGHT = 720

app = FastAPI(
    title="RepBattle AI - Computer Vision API",
    version="0.1.0",
    description="Real-time Push-up pose detection and repetition counting.",
)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# Production must explicitly list the public frontend origin(s).
FRONTEND_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
]

LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# LAN HTTP origins are allowed only during local development.
LOCAL_FRONTEND_ORIGIN_REGEX = (
    r"^http://(localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):3000$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        FRONTEND_ORIGINS
        if IS_PRODUCTION
        else [*LOCAL_FRONTEND_ORIGINS, *FRONTEND_ORIGINS]
    ),
    allow_origin_regex=(
        None if IS_PRODUCTION else LOCAL_FRONTEND_ORIGIN_REGEX
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class CreateRoomRequest(BaseModel):
    player_name: str = Field(default="Player 1", min_length=1, max_length=20)


class JoinRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=20)


class StartMatchRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=100)


@app.get("/")
async def root():
    return {
        "name": "RepBattle AI CV API",
        "status": "running",
        "docs": "/docs",
        "websocket": "/ws/pushup",
    }


@app.post("/rooms", status_code=201)
async def create_match_room(payload: CreateRoomRequest):
    player_name = payload.player_name.strip()
    if not player_name:
        raise HTTPException(
            status_code=400,
            detail="กรุณาระบุชื่อผู้เล่น",
        )

    return create_room(player_name)


@app.post("/rooms/{room_code}/join", status_code=200)
async def join_match_room(room_code: str, payload: JoinRoomRequest):
    player_name = payload.player_name.strip()
    if not player_name:
        raise HTTPException(
            status_code=400,
            detail="กรุณาระบุชื่อผู้เล่น",
        )

    try:
        return join_room(room_code, player_name)
    except RoomNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบห้องแข่งขันนี้",
        )
    except RoomFullError:
        raise HTTPException(
            status_code=409,
            detail="ห้องนี้มีผู้เล่นครบ 2 คนแล้ว",
        )
    except RoomNotReadyError:
        raise HTTPException(
            status_code=409,
            detail="ห้องนี้ไม่สามารถเข้าร่วมได้แล้ว",
        )


@app.post("/rooms/{room_code}/start", status_code=200)
async def start_match_room(room_code: str, payload: StartMatchRequest):
    try:
        return start_match(room_code, payload.player_id)
    except RoomNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบห้องแข่งขันนี้",
        )
    except RoomPlayerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบผู้เล่นในห้องนี้",
        )
    except RoomPermissionError:
        raise HTTPException(
            status_code=403,
            detail="เฉพาะเจ้าของห้องเท่านั้นที่เริ่มการแข่งขันได้",
        )
    except RoomPlayersNotConnectedError:
        raise HTTPException(
            status_code=409,
            detail="ผู้เล่นทั้งสองคนต้องเชื่อมต่อ AI ก่อนเริ่มการแข่งขัน",
        )
    except RoomNotReadyError:
        raise HTTPException(
            status_code=409,
            detail="ห้องยังไม่พร้อมเริ่มการแข่งขัน",
        )


@app.get("/rooms/{room_code}")
async def read_match_room(room_code: str):
    room = get_room(room_code)
    if room is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบห้องแข่งขันนี้",
        )

    return {"room": room}


@app.get("/health")
async def health():
    model_available = MODEL_PATH.is_file()
    if not model_available:
        raise HTTPException(
            status_code=503,
            detail="ไม่พบไฟล์ Pose Landmarker model",
        )

    return {
        "status": "ok",
        "model_available": True,
    }


@app.websocket("/ws/pushup")
async def pushup_websocket(websocket: WebSocket):
    """
    รับ JPEG binary frame จากผู้เล่น 1 คนต่อ 1 WebSocket connection
    แต่ละ connection มี PushUpDetector ของตัวเอง

    เมื่อต่อ room_code และ player_id มาด้วย ระบบจะบันทึกจำนวน reps
    เฉพาะช่วงที่สถานะการแข่งขันเป็น running ตามเวลาที่ Server กำหนด
    """
    room_code = websocket.query_params.get("room_code")
    player_id = websocket.query_params.get("player_id")
    room_attached = bool(room_code and player_id)

    # ต้องส่ง room_code และ player_id มาคู่กัน หรือไม่ส่งทั้งคู่ (โหมดทดสอบกล้อง)
    if bool(room_code) != bool(player_id):
        await websocket.close(code=4400, reason="room_code and player_id are required together")
        return

    if room_attached:
        room = get_room(room_code)
        is_member = room and any(
            player["player_id"] == player_id
            for player in room["players"]
        )
        if not is_member:
            await websocket.close(code=4404, reason="Room or player not found")
            return

        if room["status"] == "finished":
            await websocket.close(code=4409, reason="Match has already finished")
            return

    # Keep the player's existing score when reconnecting during a live match.
    initial_reps = 0
    if room_attached:
        player = next(
            (
                member
                for member in room["players"]
                if member["player_id"] == player_id
            ),
            None,
        )
        if player is not None:
            initial_reps = player["reps"]

    await websocket.accept()

    # ใช้ worker thread เดียวต่อ connection เพื่อให้ MediaPipe instance
    # ถูกสร้าง ใช้งาน และปิดบน thread เดียวกัน โดยไม่บล็อก event loop
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="repbattle-pose",
    )
    loop = asyncio.get_running_loop()
    detector = None
    connection_id = secrets.token_urlsafe(16)

    try:
        try:
            detector_factory = partial(
                PushUpDetector,
                initial_reps=initial_reps,
            )
            detector = await loop.run_in_executor(
                executor,
                detector_factory,
            )
        except Exception:
            logger.exception("Could not initialize PushUpDetector")
            await websocket.send_json({
                "type": "error",
                "message": "ไม่สามารถเริ่มระบบตรวจจับท่าทางได้ กรุณาตรวจสอบไฟล์โมเดล",
            })
            await websocket.close(code=1011)
            return

        # Mark the player connected only after the detector is initialized.
        # This prevents the host from starting the countdown too early.
        if room_attached:
            set_player_connected(
                room_code,
                player_id,
                True,
                connection_id,
            )

        await websocket.send_json({
            "type": "ready",
            "message": "Push-up detector พร้อมทำงาน",
        })

        while True:
            image_bytes = await websocket.receive_bytes()

            if not image_bytes or len(image_bytes) > MAX_FRAME_BYTES:
                await websocket.send_json({
                    "type": "error",
                    "message": "ข้อมูลภาพว่างหรือมีขนาดใหญ่เกินกำหนด",
                })
                continue

            if room_attached:
                current_room = get_room(room_code)
                if current_room is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "ไม่พบห้องแข่งขันนี้",
                    })
                    break

                if current_room["status"] == "finished":
                    await websocket.send_json({
                        "type": "match_finished",
                        "result": current_room["result"],
                        "winner_player_id": current_room["winner_player_id"],
                        "room": current_room,
                    })
                    break

                # Keep both cameras connected, but do not run or score reps
                # until the server-authoritative match timer enters "running".
                if current_room["status"] != "running":
                    await websocket.send_json({
                        "type": "result",
                        "pose_detected": False,
                        "elbow_angle": None,
                        "arm_side": None,
                        "reps": 0,
                        "phase": current_room["status"].upper(),
                    })
                    continue

            encoded_image = np.frombuffer(image_bytes, dtype=np.uint8)
            frame = cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)

            if frame is None:
                await websocket.send_json({
                    "type": "error",
                    "message": "ไม่สามารถอ่านภาพได้ กรุณาส่งภาพ JPEG",
                })
                continue

            height, width = frame.shape[:2]

            # จำกัดขนาดภาพเพื่อลดภาระ CPU และหน่วยความจำ
            scale = min(
                MAX_FRAME_WIDTH / width,
                MAX_FRAME_HEIGHT / height,
                1.0,
            )
            if scale < 1.0:
                new_size = (
                    int(width * scale),
                    int(height * scale),
                )
                frame = cv2.resize(
                    frame,
                    new_size,
                    interpolation=cv2.INTER_AREA,
                )

            # ใช้ detector ประจำ connection นี้เท่านั้น
            _, result = await loop.run_in_executor(
                executor,
                detector.process_frame,
                frame,
            )

            if room_attached:
                update_player_reps(room_code, player_id, result.get("reps", 0))

            await websocket.send_json({
                "type": "result",
                **result,
            })

    except WebSocketDisconnect:
        logger.info("CV WebSocket client disconnected")
    except Exception:
        logger.exception("Unexpected error in CV WebSocket")
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        if room_attached:
            try:
                set_player_connected(
                    room_code,
                    player_id,
                    False,
                    connection_id,
                )
            except (RoomNotFoundError, RoomPlayerNotFoundError):
                logger.warning(
                    "Could not update connection state for %s in room %s",
                    player_id,
                    room_code,
                )

        if detector is not None:
            try:
                await loop.run_in_executor(executor, detector.close)
            except Exception:
                logger.exception("Could not close PushUpDetector")

        executor.shutdown(wait=True)
