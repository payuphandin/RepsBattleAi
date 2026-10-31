import cv2


def main():
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        raise RuntimeError("ไม่สามารถเปิดกล้องได้ กรุณาตรวจสอบการเชื่อมต่อหรือสิทธิ์การใช้งานกล้อง")

    print("เปิดกล้องสำเร็จ กด q เพื่อออกจากโปรแกรม")

    while True:
        success, frame = camera.read()
        if not success:
            print("ไม่สามารถอ่านภาพจากกล้องได้")
            break

        cv2.imshow("RepBattle AI - Camera Test", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
