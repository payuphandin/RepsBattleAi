class PushUpCounter:
    """
    นับ Push-up จากมุมข้อศอกด้วย State Machine

    ลำดับที่ต้องเกิด:
        WAITING_FOR_UP -> UP -> DOWN -> UP (+1 REP)

    ต้องค้างอยู่เหนือ/ใต้ threshold ตามเวลาที่กำหนด
    เพื่อช่วยลดการเปลี่ยนสถานะจากค่าที่แกว่งเพียงชั่วขณะ
    """

    def __init__(
        self,
        up_threshold=160.0,
        down_threshold=90.0,
        hold_seconds=0.12,
    ):
        if down_threshold >= up_threshold:
            raise ValueError("down_threshold ต้องน้อยกว่า up_threshold")

        self.up_threshold = up_threshold
        self.down_threshold = down_threshold
        self.hold_seconds = hold_seconds

        self.reps = 0
        self.state = "WAITING_FOR_UP"
        self._candidate_since = None

    def update(self, angle, timestamp):
        """
        รับมุมข้อศอกและเวลาปัจจุบัน แล้วอัปเดตสถานะการนับ

        angle: มุมข้อศอกเป็นองศา หรือ None เมื่อไม่เห็นข้อศอกชัด
        timestamp: เวลาจาก time.perf_counter()
        """
        # เมื่อไม่เห็นข้อศอก ให้ยกเลิกรอบที่ยังทำไม่ครบ
        # ผู้เล่นต้องกลับไปอยู่ท่า UP ก่อนเริ่มรอบใหม่
        if angle is None:
            self.state = "WAITING_FOR_UP"
            self._candidate_since = None
            return self.reps

        if self.state == "WAITING_FOR_UP":
            condition_met = angle >= self.up_threshold
            next_state = "UP"

        elif self.state == "UP":
            condition_met = angle <= self.down_threshold
            next_state = "DOWN"

        else:  # state == "DOWN"
            condition_met = angle >= self.up_threshold
            next_state = "UP"

        if not condition_met:
            self._candidate_since = None
            return self.reps

        if self._candidate_since is None:
            self._candidate_since = timestamp
            return self.reps

        held_for = timestamp - self._candidate_since
        if held_for < self.hold_seconds:
            return self.reps

        # นับเมื่อกลับจาก DOWN มา UP ครบวงจรเท่านั้น
        if self.state == "DOWN" and next_state == "UP":
            self.reps += 1

        self.state = next_state
        self._candidate_since = None
        return self.reps
