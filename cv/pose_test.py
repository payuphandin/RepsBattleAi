import cv2

from pushup_detector import PushUpDetector


def main():
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError(
            "ไม่สามารถเปิดกล้องได้ กรุณาตรวจสอบ Webcam"
        )

    print("เริ่มทดสอบ Push-up Detector กด q เพื่อออกจากโปรแกรม")

    try:
        with PushUpDetector() as detector:
            while True:
                success, frame = camera.read()
                if not success:
                    print("ไม่สามารถอ่านภาพจากกล้องได้")
                    break

                # กลับภาพแบบกระจกเฉพาะตอนแสดงผลจากกล้องเครื่องนี้
                frame = cv2.flip(frame, 1)

                annotated_frame, result = detector.process_frame(frame)

                if result["pose_detected"]:
                    status = "POSE DETECTED"
                    status_color = (0, 255, 0)
                else:
                    status = "NO POSE"
                    status_color = (0, 0, 255)

                angle = result["elbow_angle"]
                if angle is None:
                    angle_text = "Elbow: --"
                else:
                    angle_text = (
                        f"Elbow: {angle:.1f} deg "
                        f"({result['arm_side']})"
                    )

                cv2.putText(
                    annotated_frame,
                    status,
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    status_color,
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    annotated_frame,
                    angle_text,
                    (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    annotated_frame,
                    f"REPS: {result['reps']}",
                    (20, 110),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    annotated_frame,
                    f"PHASE: {result['phase']}",
                    (20, 145),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

                cv2.imshow(
                    "RepBattle AI - Push-up Detector Test",
                    annotated_frame,
                )

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
