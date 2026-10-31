from pathlib import Path
import math
import time

import cv2
import mediapipe as mp

from pushup_counter import PushUpCounter


MODEL_PATH = (
    Path(__file__).resolve().parent
    / "models"
    / "pose_landmarker_lite.task"
)

POSE_CONNECTIONS = [
    (11, 12),
    (11, 13), (13, 15),
    (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27),
    (24, 26), (26, 28),
    (15, 17), (15, 19), (15, 21),
    (16, 18), (16, 20), (16, 22),
    (27, 29), (29, 31), (27, 31),
    (28, 30), (30, 32), (28, 32),
]


def calculate_angle(a, b, c, frame_width, frame_height):
    """คำนวณมุม ABC โดยให้ b เป็นจุดยอดมุม"""
    ax, ay = a.x * frame_width, a.y * frame_height
    bx, by = b.x * frame_width, b.y * frame_height
    cx, cy = c.x * frame_width, c.y * frame_height

    vector_ba = (ax - bx, ay - by)
    vector_bc = (cx - bx, cy - by)

    length_ba = math.hypot(*vector_ba)
    length_bc = math.hypot(*vector_bc)

    if length_ba == 0 or length_bc == 0:
        return None

    dot_product = (
        vector_ba[0] * vector_bc[0]
        + vector_ba[1] * vector_bc[1]
    )
    cosine = dot_product / (length_ba * length_bc)
    cosine = max(-1.0, min(1.0, cosine))

    return math.degrees(math.acos(cosine))


def get_best_elbow_angle(landmarks, frame_width, frame_height):
    """เลือกข้อศอกด้านที่มองเห็นชัดที่สุด แล้วคำนวณมุมข้อศอก"""
    candidates = [
        ("LEFT", 11, 13, 15),
        ("RIGHT", 12, 14, 16),
    ]

    best_result = None
    best_visibility = 0.5

    for side_name, shoulder_idx, elbow_idx, wrist_idx in candidates:
        shoulder = landmarks[shoulder_idx]
        elbow = landmarks[elbow_idx]
        wrist = landmarks[wrist_idx]

        visibility = min(
            getattr(shoulder, "visibility", 0.0),
            getattr(elbow, "visibility", 0.0),
            getattr(wrist, "visibility", 0.0),
        )

        if visibility <= best_visibility:
            continue

        angle = calculate_angle(
            shoulder,
            elbow,
            wrist,
            frame_width,
            frame_height,
        )
        if angle is None:
            continue

        elbow_position = (
            int(elbow.x * frame_width),
            int(elbow.y * frame_height),
        )

        best_visibility = visibility
        best_result = (side_name, angle, elbow_position)

    return best_result


def draw_pose(frame, landmarks, visibility_threshold=0.5):
    """วาดจุดข้อต่อและเส้นโครงกระดูกลงบนภาพ"""
    height, width = frame.shape[:2]
    points = []

    for landmark in landmarks:
        points.append((
            int(landmark.x * width),
            int(landmark.y * height),
            getattr(landmark, "visibility", 1.0),
        ))

    for start_idx, end_idx in POSE_CONNECTIONS:
        start = points[start_idx]
        end = points[end_idx]

        if (
            start[2] >= visibility_threshold
            and end[2] >= visibility_threshold
        ):
            cv2.line(
                frame,
                (start[0], start[1]),
                (end[0], end[1]),
                (0, 255, 0),
                2,
            )

    for x, y, visibility in points:
        if visibility >= visibility_threshold:
            cv2.circle(frame, (x, y), 5, (0, 140, 255), -1)


class PushUpDetector:
    """
    ประมวลผลภาพ 1 เฟรมสำหรับผู้เล่น 1 คน

    สร้าง PushUpDetector แยก instance ต่อผู้เล่น/การเชื่อมต่อ
    เพื่อไม่ให้ตัวนับและสถานะของผู้เล่นปะปนกัน
    """

    def __init__(
        self,
        up_threshold=160.0,
        down_threshold=90.0,
        hold_seconds=0.12,
        initial_reps=0,
    ):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"ไม่พบโมเดล Pose Landmarker: {MODEL_PATH}"
            )

        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(MODEL_PATH)
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.landmarker = (
            mp.tasks.vision.PoseLandmarker.create_from_options(options)
        )
        self.counter = PushUpCounter(
            up_threshold=up_threshold,
            down_threshold=down_threshold,
            hold_seconds=hold_seconds,
        )
        # Restore the server-side score when a player reconnects mid-match.
        self.counter.reps = max(0, int(initial_reps))
        self.last_timestamp_ms = -1
        self.closed = False

    def process_frame(self, frame):
        """
        รับภาพ BGR จาก OpenCV
        คืนค่า (ภาพที่วาด skeleton แล้ว, ผลวิเคราะห์ที่ส่งผ่าน API ได้)
        """
        if self.closed:
            raise RuntimeError("PushUpDetector ถูกปิดไปแล้ว")

        if frame is None or frame.size == 0:
            raise ValueError("ได้รับภาพว่าง ไม่สามารถประมวลผลได้")

        annotated_frame = frame.copy()
        frame_height, frame_width = frame.shape[:2]

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame,
        )

        now = time.perf_counter()
        timestamp_ms = int(now * 1000)
        timestamp_ms = max(timestamp_ms, self.last_timestamp_ms + 1)
        self.last_timestamp_ms = timestamp_ms

        detection = self.landmarker.detect_for_video(
            mp_image,
            timestamp_ms,
        )

        elbow_angle = None
        arm_side = None
        pose_detected = bool(detection.pose_landmarks)

        if pose_detected:
            landmarks = detection.pose_landmarks[0]
            draw_pose(annotated_frame, landmarks)

            elbow_result = get_best_elbow_angle(
                landmarks,
                frame_width,
                frame_height,
            )

            if elbow_result is not None:
                arm_side, elbow_angle, elbow_position = elbow_result
                self.counter.update(elbow_angle, now)

                cv2.circle(
                    annotated_frame,
                    elbow_position,
                    9,
                    (255, 0, 255),
                    -1,
                )
            else:
                self.counter.update(None, now)
        else:
            self.counter.update(None, now)

        result = {
            "pose_detected": pose_detected,
            "elbow_angle": (
                round(elbow_angle, 1)
                if elbow_angle is not None
                else None
            ),
            "arm_side": arm_side,
            "reps": self.counter.reps,
            "phase": self.counter.state,
        }

        return annotated_frame, result

    def close(self):
        """ปิด MediaPipe resource เมื่อจบการใช้งาน"""
        if not self.closed:
            self.landmarker.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
