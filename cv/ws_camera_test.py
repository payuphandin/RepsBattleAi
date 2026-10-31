import asyncio
import json

import cv2
import websockets


WEBSOCKET_URL = "ws://127.0.0.1:8000/ws/pushup"


async def main():
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError("ไม่สามารถเปิด Webcam ได้")

    try:
        async with websockets.connect(
            WEBSOCKET_URL,
            max_size=2_000_000,
        ) as websocket:
            # รอข้อความยืนยันว่า API สร้าง PushUpDetector สำเร็จ
            ready_message = json.loads(await websocket.recv())
            print("Server:", ready_message)

            if ready_message.get("type") != "ready":
                raise RuntimeError("CV API ยังไม่พร้อมใช้งาน")

            print("ส่งภาพไปยัง CV API แล้ว กด q เพื่อออกจากโปรแกรม")

            while True:
                success, frame = camera.read()
                if not success:
                    print("ไม่สามารถอ่านภาพจาก Webcam ได้")
                    break

                frame = cv2.flip(frame, 1)

                encoded, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 70],
                )
                if not encoded:
                    continue

                # ส่ง JPEG bytes ไปยัง FastAPI ผ่าน WebSocket
                await websocket.send(buffer.tobytes())

                # รอผล JSON ที่ API ประมวลผลจากภาพเฟรมนี้
                response = json.loads(await websocket.recv())

                if response.get("type") == "error":
                    print("API error:", response.get("message"))
                    continue

                angle = response.get("elbow_angle")
                angle_text = (
                    f"Elbow: {angle:.1f} deg"
                    if angle is not None
                    else "Elbow: --"
                )

                cv2.putText(
                    frame,
                    f"REPS: {response.get('reps', 0)}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    frame,
                    angle_text,
                    (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    frame,
                    f"PHASE: {response.get('phase', '--')}",
                    (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

                cv2.imshow("RepBattle AI - WebSocket Camera Test", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(main())
