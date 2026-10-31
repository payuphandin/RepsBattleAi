"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type CvResult = {
  type?: "ready" | "result" | "error" | "match_finished";
  message?: string;
  pose_detected?: boolean;
  elbow_angle?: number | null;
  arm_side?: string | null;
  reps?: number;
  phase?: string;
  processing_ms?: number;
  result?: "winner" | "draw" | null;
  winner_player_id?: string | null;
  room?: MatchRoom;
};

function getApiBaseUrl() {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configuredUrl) {
    return configuredUrl.replace(/\/+$/, "");
  }

  // Do not silently target the frontend host on port 8000 in production.
  if (process.env.NODE_ENV === "production") {
    throw new Error("ยังไม่ได้ตั้งค่า NEXT_PUBLIC_API_URL สำหรับ Production");
  }

  if (typeof window === "undefined") {
    return "http://127.0.0.1:8000";
  }

  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${window.location.hostname}:8000`;
}

function getPushUpWebSocketUrl() {
  const apiUrl = getApiBaseUrl();
  const wsUrl = apiUrl.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  return `${wsUrl}/ws/pushup`;
}

const SEND_INTERVAL_MS = 150;

type MatchRoom = {
  room_code: string;
  status: string;
  max_players: number;
  duration_seconds: number;
  countdown_seconds: number;
  remaining_seconds: number | null;
  start_at: number | null;
  end_at: number | null;
  winner_player_id: string | null;
  result: "winner" | "draw" | null;
  players: Array<{
    player_id: string;
    name: string;
    role: string;
    reps: number;
    connected: boolean;
  }>;
  created_at: string;
};

type CreatedRoomResponse = {
  room: MatchRoom;
  player_id: string;
};

type SavedRoomSession = {
  room_code: string;
  player_id: string;
  player_name: string;
};

const ROOM_SESSION_STORAGE_KEY = "repbattle_room_session";

function saveRoomSession(data: CreatedRoomResponse, playerName: string) {
  const session: SavedRoomSession = {
    room_code: data.room.room_code,
    player_id: data.player_id,
    player_name: playerName,
  };

  window.localStorage.setItem(
    ROOM_SESSION_STORAGE_KEY,
    JSON.stringify(session),
  );
}

export default function Home() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sendingRef = useRef(false);
  const frameSentAtRef = useRef<number | null>(null);

  const [status, setStatus] = useState("ยังไม่ได้เชื่อมต่อ");
  const [isRunning, setIsRunning] = useState(false);
  const [hasCameraStream, setHasCameraStream] = useState(false);
  const [reps, setReps] = useState(0);
  const [angle, setAngle] = useState<number | null>(null);
  const [phase, setPhase] = useState("--");
  const [poseDetected, setPoseDetected] = useState(false);
  const [error, setError] = useState("");
  const [playerName, setPlayerName] = useState("Player 1");
  const [roomInfo, setRoomInfo] = useState<CreatedRoomResponse | null>(null);
  const [isCreatingRoom, setIsCreatingRoom] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [isJoiningRoom, setIsJoiningRoom] = useState(false);
  const [isStartingMatch, setIsStartingMatch] = useState(false);
  const [isRestoringRoom, setIsRestoringRoom] = useState(true);

  // Restore the player's room identity after a page refresh.
  useEffect(() => {
    let cancelled = false;

    const restoreRoom = async () => {
      try {
        const savedValue = window.localStorage.getItem(ROOM_SESSION_STORAGE_KEY);
        if (!savedValue) return;

        const parsed = JSON.parse(savedValue) as unknown;
        if (!parsed || typeof parsed !== "object") {
          window.localStorage.removeItem(ROOM_SESSION_STORAGE_KEY);
          if (!cancelled) {
            setError("ข้อมูลห้องที่บันทึกไว้ไม่ถูกต้อง กรุณาเข้าร่วมห้องอีกครั้ง");
          }
          return;
        }

        const saved = parsed as Partial<SavedRoomSession>;
        const savedRoomCode = saved.room_code;
        const savedPlayerId = saved.player_id;
        const savedPlayerName = saved.player_name;

        if (
          typeof savedRoomCode !== "string" ||
          !/^[A-Z2-9]{6}$/.test(savedRoomCode) ||
          typeof savedPlayerId !== "string" ||
          !savedPlayerId ||
          typeof savedPlayerName !== "string"
        ) {
          window.localStorage.removeItem(ROOM_SESSION_STORAGE_KEY);
          if (!cancelled) {
            setError("ข้อมูลห้องที่บันทึกไว้ไม่ถูกต้อง กรุณาเข้าร่วมห้องอีกครั้ง");
          }
          return;
        }

        const response = await fetch(
          `${getApiBaseUrl()}/rooms/${encodeURIComponent(savedRoomCode)}`,
        );

        if (response.status === 404) {
          window.localStorage.removeItem(ROOM_SESSION_STORAGE_KEY);
          if (!cancelled) {
            setError("ไม่พบห้องเดิมแล้ว อาจเกิดจาก Server เริ่มทำงานใหม่");
          }
          return;
        }

        if (!response.ok) {
          throw new Error("ไม่สามารถโหลดข้อมูลห้องเดิมได้");
        }

        const data = (await response.json()) as { room: MatchRoom };
        const isMember = data.room.players.some(
          (player) => player.player_id === savedPlayerId,
        );

        if (!isMember) {
          window.localStorage.removeItem(ROOM_SESSION_STORAGE_KEY);
          if (!cancelled) {
            setError("ไม่พบผู้เล่นของคุณในห้องเดิม กรุณาเข้าร่วมห้องอีกครั้ง");
          }
          return;
        }

        if (!cancelled) {
          setPlayerName(savedPlayerName);
          setRoomInfo({
            room: data.room,
            player_id: savedPlayerId,
          });
        }
      } catch {
        if (!cancelled) {
          setError("เชื่อมต่อ Server ไม่ได้ จึงกู้คืนห้องเดิมไม่สำเร็จ");
        }
      } finally {
        if (!cancelled) {
          setIsRestoringRoom(false);
        }
      }
    };

    void restoreRoom();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreateRoom = async () => {
    const cleanName = playerName.trim();
    if (!cleanName) {
      setError("กรุณากรอกชื่อผู้เล่น");
      return;
    }

    setIsCreatingRoom(true);
    setError("");

    try {
      const response = await fetch(`${getApiBaseUrl()}/rooms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_name: cleanName }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "ไม่สามารถสร้างห้องแข่งขันได้");
      }

      const createdRoom = data as CreatedRoomResponse;
      saveRoomSession(createdRoom, cleanName);
      setRoomInfo(createdRoom);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "เชื่อมต่อ Room Server ไม่สำเร็จ",
      );
    } finally {
      setIsCreatingRoom(false);
    }
  };

  const handleJoinRoom = async () => {
    const cleanName = playerName.trim();
    const cleanCode = joinCode.trim().toUpperCase();

    if (!cleanName) {
      setError("กรุณากรอกชื่อผู้เล่น");
      return;
    }
    if (!/^[A-Z2-9]{6}$/.test(cleanCode)) {
      setError("รหัสห้องต้องเป็นตัวอักษร A-Z หรือเลข 2-9 จำนวน 6 ตัว");
      return;
    }

    setIsJoiningRoom(true);
    setError("");

    try {
      const response = await fetch(
        `${getApiBaseUrl()}/rooms/${encodeURIComponent(cleanCode)}/join`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_name: cleanName }),
        },
      );

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "ไม่สามารถเข้าร่วมห้องได้");
      }

      const joinedRoom = data as CreatedRoomResponse;
      saveRoomSession(joinedRoom, cleanName);
      setRoomInfo(joinedRoom);
      setJoinCode(cleanCode);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "เชื่อมต่อ Room Server ไม่สำเร็จ",
      );
    } finally {
      setIsJoiningRoom(false);
    }
  };

  const handleStartMatch = async () => {
    if (!roomInfo) return;

    setIsStartingMatch(true);
    setError("");

    try {
      const response = await fetch(
        `${getApiBaseUrl()}/rooms/${roomInfo.room.room_code}/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: roomInfo.player_id }),
        },
      );

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "ไม่สามารถเริ่มการแข่งขันได้");
      }

      setRoomInfo(data as CreatedRoomResponse);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "ไม่สามารถเริ่มการแข่งขันได้",
      );
    } finally {
      setIsStartingMatch(false);
    }
  };

  // Refresh room state so both players see the same server-side match clock.
  useEffect(() => {
    const roomCode = roomInfo?.room.room_code;
    if (!roomCode) return;

    let cancelled = false;

    const refreshRoom = async () => {
      try {
        const response = await fetch(`${getApiBaseUrl()}/rooms/${roomCode}`);
        if (!response.ok) return;
        const data = await response.json();

        if (!cancelled) {
          setRoomInfo((current) =>
            current
              ? { ...current, room: data.room as MatchRoom }
              : current,
          );
        }
      } catch {
        // Keep the last known room state if a temporary request fails.
      }
    };

    void refreshRoom();
    const timer = setInterval(() => {
      void refreshRoom();
    }, 500);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [roomInfo?.room.room_code]);

  const stopSession = useCallback((message = "หยุดการทดสอบแล้ว") => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    const socket = socketRef.current;
    socketRef.current = null;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setHasCameraStream(false);

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    sendingRef.current = false;
    frameSentAtRef.current = null;
    setIsRunning(false);
    setStatus(message);
  }, []);

  const startSession = useCallback(async () => {
    const reconnectableStatuses = ["ready", "countdown", "running"];
    if (roomInfo && !reconnectableStatuses.includes(roomInfo.room.status)) {
      setError("ห้องนี้ยังไม่พร้อมเชื่อมต่อกล้อง หรือการแข่งขันสิ้นสุดแล้ว");
      return;
    }

    setError("");
    setReps(
      roomInfo
        ? roomInfo.room.players.find(
            (player) => player.player_id === roomInfo.player_id,
          )?.reps ?? 0
        : 0,
    );
    setAngle(null);
    setPhase("--");
    setPoseDetected(false);
    setStatus("กำลังขอสิทธิ์ใช้งานกล้อง...");

    try {
      if (!window.isSecureContext) {
        throw new Error(
          "เบราว์เซอร์ไม่อนุญาตให้ใช้กล้องบน HTTP กรุณาเปิดเว็บผ่าน HTTPS หรือ localhost",
        );
      }

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Browser นี้ไม่รองรับการเปิดกล้อง กรุณาใช้ Browser รุ่นใหม่");
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: "user",
          width: { ideal: 640 },
          height: { ideal: 480 },
        },
      });
      streamRef.current = stream;

      const video = videoRef.current;
      if (!video) throw new Error("ไม่พบ video element");

      video.srcObject = stream;
      await video.play();
      setHasCameraStream(true);

      setStatus("กำลังเชื่อมต่อ AI Server...");

      const baseWebSocketUrl = getPushUpWebSocketUrl();
      const socketUrl = roomInfo
        ? `${baseWebSocketUrl}?room_code=${encodeURIComponent(roomInfo.room.room_code)}&player_id=${encodeURIComponent(roomInfo.player_id)}`
        : baseWebSocketUrl;
      const socket = new WebSocket(socketUrl);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      socket.onopen = () => {
        setStatus("เชื่อมต่อแล้ว กำลังรอ AI...");
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        if (socketRef.current !== socket) return;

        let data: CvResult;
        try {
          data = JSON.parse(event.data) as CvResult;
        } catch {
          sendingRef.current = false;
          frameSentAtRef.current = null;
          setError("ได้รับข้อมูลจาก AI ในรูปแบบที่ไม่ถูกต้อง");
          return;
        }

        if (data.type === "ready") {
          setStatus(roomInfo ? "AI พร้อมใช้งาน · CONNECTED TO ROOM" : "AI พร้อมใช้งาน");
          setIsRunning(true);
          return;
        }

        if (data.type === "error") {
          sendingRef.current = false;
          frameSentAtRef.current = null;
          setError(data.message ?? "เกิดข้อผิดพลาดจาก AI Server");
          return;
        }

        if (data.type === "match_finished") {
          if (data.room) {
            setRoomInfo((current) =>
              current ? { ...current, room: data.room as MatchRoom } : current,
            );
          }
          stopSession("การแข่งขันสิ้นสุดแล้ว");
          return;
        }

        if (data.type === "result") {
          const sentAt = frameSentAtRef.current;
          if (sentAt !== null) {
            console.debug("[RepBattle] Frame timing", {
              roundTripMs: Math.round(performance.now() - sentAt),
              processingMs: data.processing_ms ?? null,
            });
          }
          sendingRef.current = false;
          frameSentAtRef.current = null;
          setPoseDetected(Boolean(data.pose_detected));
          setAngle(data.elbow_angle ?? null);
          setReps(data.reps ?? 0);
          setPhase(data.phase ?? "--");
        }
      };

      socket.onerror = () => {
        setError("เชื่อมต่อ AI Server ไม่สำเร็จ ตรวจสอบว่า FastAPI กำลังทำงานอยู่");
        stopSession("เชื่อมต่อไม่สำเร็จ");
      };

      socket.onclose = (event) => {
        if (socketRef.current === socket) {
          if (event.code === 4404) {
            setError("ไม่พบห้องหรือผู้เล่นนี้ กรุณาสร้างห้องหรือเข้าร่วมใหม่");
          } else if (event.code === 4409) {
            setError("การแข่งขันสิ้นสุดแล้ว ไม่สามารถเชื่อมต่อกล้องได้");
          }
          stopSession("การเชื่อมต่อ AI ถูกปิดแล้ว");
        }
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : "ไม่สามารถเริ่มการทดสอบได้";
      setError(message);
      stopSession("เริ่มการทดสอบไม่สำเร็จ");
    }
  }, [stopSession, roomInfo]);

  useEffect(() => {
    if (!isRunning) return;

    intervalRef.current = setInterval(() => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const socket = socketRef.current;

      if (
        !video ||
        !canvas ||
        !socket ||
        socket.readyState !== WebSocket.OPEN ||
        video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
        sendingRef.current ||
        socket.bufferedAmount > 1_000_000
      ) {
        return;
      }

      const sourceWidth = video.videoWidth;
      const sourceHeight = video.videoHeight;
      if (!sourceWidth || !sourceHeight) return;

      // ส่งภาพไม่เกิน 640x480 เพื่อลดขนาดข้อมูลที่ส่งไปยัง AI Server
      const scale = Math.min(640 / sourceWidth, 480 / sourceHeight, 1);
      const width = Math.round(sourceWidth * scale);
      const height = Math.round(sourceHeight * scale);

      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) return;

      // กลับภาพแบบกระจกให้ตรงกับภาพตัวอย่างบนหน้าเว็บ
      context.save();
      context.translate(width, 0);
      context.scale(-1, 1);
      context.drawImage(video, 0, 0, width, height);
      context.restore();

      // ส่งได้ครั้งละ 1 เฟรม และรอผลจาก Backend ก่อนส่งเฟรมถัดไป
      sendingRef.current = true;
      frameSentAtRef.current = performance.now();
      canvas.toBlob(
        (blob) => {
          if (
            !blob ||
            socket.readyState !== WebSocket.OPEN ||
            socketRef.current !== socket
          ) {
            if (socketRef.current === socket) {
              sendingRef.current = false;
              frameSentAtRef.current = null;
            }
            return;
          }

          try {
            socket.send(blob);
          } catch {
            if (socketRef.current === socket) {
              sendingRef.current = false;
              frameSentAtRef.current = null;
              setError("ส่งภาพไปยัง AI Server ไม่สำเร็จ");
            }
          }
        },
        "image/jpeg",
        0.7,
      );
    }, SEND_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning]);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      socketRef.current?.close();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <main className="min-h-screen px-4 py-6 sm:px-8 sm:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="brand-mark">R</div>
            <div>
              <p className="text-lg font-black tracking-tight">RepBattle <span className="text-lime-400">AI</span></p>
              <p className="text-xs text-slate-400">REAL-TIME FITNESS BATTLE</p>
            </div>
          </div>
          <div className="status-pill">
            <span className={`status-dot ${isRunning ? "online" : ""}`} />
            {status}
          </div>
        </header>

        <section className="mb-7">
          <p className="mb-2 text-sm font-semibold uppercase tracking-[0.22em] text-lime-400">Computer Vision Lab / 01</p>
          <h1 className="text-3xl font-black tracking-tight sm:text-5xl">Push-up <span className="text-gradient">Detection</span></h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">
            ทดสอบการเชื่อมต่อกล้องจาก Browser กับ Python AI ผ่าน WebSocket
            พร้อมตรวจจับท่าทางและนับจำนวน Push-up แบบ Real-time
          </p>
        </section>

        <section className="panel mb-6 p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-bold">MATCH ROOM</p>
              <p className="mt-1 text-xs text-slate-500">สร้างห้องเพื่อเตรียมแข่งขัน Push-up แบบ 1v1</p>
            </div>
            <span className="live-label">STEP 01 / ROOM SETUP</span>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3">
              <p className="text-xs font-semibold text-slate-400">YOUR PLAYER NAME</p>
              <input
                value={playerName}
                onChange={(event) => setPlayerName(event.target.value)}
                maxLength={20}
                placeholder="ชื่อผู้เล่น"
                aria-label="ชื่อผู้เล่น"
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-lime-400/50"
              />
              <button
                className="primary-button w-full"
                onClick={handleCreateRoom}
                disabled={isCreatingRoom || isJoiningRoom || isRestoringRoom}
              >
                {isCreatingRoom ? "กำลังสร้าง..." : "Create New Room"}
                {!isCreatingRoom && <span> →</span>}
              </button>
            </div>

            <div className="space-y-3">
              <p className="text-xs font-semibold text-slate-400">JOIN WITH ROOM CODE</p>
              <input
                value={joinCode}
                onChange={(event) => setJoinCode(event.target.value.toUpperCase().replace(/[^A-Z2-9]/g, "").slice(0, 6))}
                maxLength={6}
                placeholder="กรอกรหัส 6 ตัว"
                aria-label="รหัสห้องแข่งขัน"
                className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm uppercase tracking-[0.2em] text-white outline-none transition focus:border-lime-400/50"
              />
              <button
                className="stop-button w-full"
                onClick={handleJoinRoom}
                disabled={isJoiningRoom || isCreatingRoom || isRestoringRoom}
              >
                {isJoiningRoom ? "กำลังเข้าร่วม..." : "Join Room"}
              </button>
            </div>
          </div>

          {roomInfo && (
            <div className="mt-5 rounded-xl border border-lime-400/20 bg-lime-400/[0.06] p-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold tracking-wider text-lime-300">ROOM CODE</p>
                  <p className="mt-1 font-mono text-3xl font-black tracking-[0.2em] text-white">{roomInfo.room.room_code}</p>
                </div>
                <div className="text-right">
                  <span className={`live-label ${roomInfo.room.status === "ready" || roomInfo.room.status === "running" ? "live" : ""}`}>
                    {roomInfo.room.status === "waiting" && "WAITING FOR PLAYER"}
                    {roomInfo.room.status === "ready" && "2 PLAYERS READY"}
                    {roomInfo.room.status === "countdown" && "GET READY"}
                    {roomInfo.room.status === "running" && "MATCH LIVE"}
                    {roomInfo.room.status === "finished" && "MATCH FINISHED"}
                  </span>
                  <p className="mt-2 text-xs text-slate-400">
                    {roomInfo.room.players.length}/{roomInfo.room.max_players} players
                  </p>
                </div>
                <button
                  className="stop-button"
                  onClick={() => {
                    void navigator.clipboard.writeText(roomInfo.room.room_code);
                  }}
                >
                  Copy Code
                </button>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {roomInfo.room.players.map((player, index) => (
                  <div key={player.player_id} className="rounded-lg border border-white/10 bg-black/20 p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                      {index === 0 ? "PLAYER 1 · HOST" : "PLAYER 2 · GUEST"}
                    </p>
                    <p className="mt-1 font-semibold text-white">{player.name}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      <span className={player.connected ? "text-lime-400" : "text-slate-500"}>
                        {player.connected ? "AI CONNECTED" : "AI NOT CONNECTED"}
                      </span>
                    </p>
                  </div>
                ))}
                {roomInfo.room.players.length < roomInfo.room.max_players && (
                  <div className="rounded-lg border border-dashed border-white/10 p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">PLAYER 2</p>
                    <p className="mt-1 text-sm text-slate-500">รอผู้เล่นเข้าร่วม...</p>
                  </div>
                )}
              </div>

              {roomInfo.room.status === "ready" && roomInfo.room.players[0]?.player_id === roomInfo.player_id && (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/20 p-3">
                  <div>
                    <p className="text-sm font-semibold text-white">เริ่มการแข่งขัน</p>
                    <p className="mt-1 text-xs text-slate-400">
                      {roomInfo.room.players.every((player) => player.connected)
                        ? "ผู้เล่นทั้งสองคนเชื่อมต่อ AI แล้ว พร้อมเริ่มได้"
                        : "ให้ผู้เล่นทั้งสองคนกด Connect Camera ก่อน"}
                    </p>
                  </div>
                  <button
                    className="primary-button"
                    onClick={handleStartMatch}
                    disabled={isStartingMatch || !roomInfo.room.players.every((player) => player.connected)}
                  >
                    {isStartingMatch ? "กำลังเริ่ม..." : "Start Match →"}
                  </button>
                </div>
              )}

              {roomInfo.room.status === "ready" && roomInfo.room.players[0]?.player_id !== roomInfo.player_id && (
                <p className="mt-4 text-xs text-slate-400">
                  รอเจ้าของห้องเริ่มการแข่งขัน หลังจากผู้เล่นทั้งสองเชื่อมต่อ AI แล้ว
                </p>
              )}

              {(roomInfo.room.status === "countdown" || roomInfo.room.status === "running") && (
                <>
                  {roomInfo.room.players.some((player) => !player.connected) && (
                    <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-xs text-amber-200">
                      มีผู้เล่นหลุดการเชื่อมต่อ เวลาการแข่งขันยังเดินต่อ และสามารถกด Connect Camera เพื่อกลับเข้ามาได้
                    </p>
                  )}
                  <div className="mt-4 rounded-xl border border-lime-400/20 bg-lime-400/[0.06] p-4 text-center">
                    <p className="text-xs font-semibold tracking-widest text-lime-300">
                      {roomInfo.room.status === "countdown" ? "MATCH STARTS IN" : "TIME REMAINING"}
                    </p>
                    <p className="mt-1 text-5xl font-black tabular-nums text-white">
                      {roomInfo.room.remaining_seconds ?? "--"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {roomInfo.room.status === "countdown"
                        ? "เตรียมตัวให้พร้อม"
                        : "ทำ Push-up ให้ได้มากที่สุด"}
                    </p>
                  </div>
                </>
              )}

              {roomInfo.room.status === "finished" && (
                <div className="mt-4 rounded-xl border border-lime-400/20 bg-lime-400/[0.06] p-4">
                  <p className="text-xs font-semibold tracking-widest text-lime-300">MATCH RESULT</p>
                  <p className="mt-2 text-xl font-black text-white">
                    {roomInfo.room.result === "draw"
                      ? "เสมอกัน!"
                      : `ผู้ชนะ: ${roomInfo.room.players.find((player) => player.player_id === roomInfo.room.winner_player_id)?.name ?? "Unknown"}`}
                  </p>
                </div>
              )}
            </div>
          )}
        </section>

        <div className="grid gap-5 lg:grid-cols-[1.55fr_0.85fr]">
          <section className="panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <p className="font-bold">Camera Feed</p>
                <p className="mt-1 text-xs text-slate-500">Browser webcam input</p>
              </div>
              <span className={`live-label ${isRunning ? "live" : ""}`}>
                <span className="status-dot" /> {isRunning ? "LIVE" : "STANDBY"}
              </span>
            </div>

            <div className="camera-stage">
              <video ref={videoRef} autoPlay muted playsInline className="camera-video" />
              <canvas ref={canvasRef} className="hidden" />
              {!hasCameraStream && (
                <div className="camera-placeholder">
                  <div className="camera-icon">◎</div>
                  <p className="font-semibold text-slate-300">Camera is waiting</p>
                  <p className="mt-1 text-xs text-slate-500">กด Start Test เพื่อเปิดกล้อง</p>
                </div>
              )}
              <div className="camera-overlay">
                <span>REP BATTLE / CV INPUT</span>
                <span>{poseDetected ? "POSE TRACKING" : "WAITING FOR POSE"}</span>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <p className="text-xs text-slate-500">แนะนำให้วางกล้องด้านข้างและเห็นช่วงไหล่ถึงข้อมือ</p>
              {!isRunning ? (
                <button
                  className="primary-button"
                  onClick={startSession}
                  disabled={Boolean(
                    roomInfo &&
                      !["ready", "countdown", "running"].includes(roomInfo.room.status),
                  )}
                >
                  {roomInfo ? "Connect Camera" : "Start Test"} <span>→</span>
                </button>
              ) : (
                <button className="stop-button" onClick={() => stopSession()}>Stop Test</button>
              )}
            </div>
          </section>

          <section className="flex flex-col gap-5">
            <div className="panel score-panel">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-300">MATCH SCORE</p>
                  <p className="mt-1 text-xs text-slate-500">คะแนนจาก AI ของผู้เล่นทั้งสองคน</p>
                </div>
                <span className="score-icon">↗</span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-lime-400/20 bg-lime-400/[0.06] p-3">
                  <p className="truncate text-xs font-semibold text-lime-300">
                    {roomInfo
                      ? roomInfo.room.players.find((player) => player.player_id === roomInfo.player_id)?.name ?? "YOU"
                      : "YOU"}
                  </p>
                  <p className="mt-2 text-4xl font-black tabular-nums text-white">
                    {reps.toString().padStart(2, "0")}
                  </p>
                  <p className="mt-1 text-[10px] text-slate-500">YOUR REPS</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <p className="truncate text-xs font-semibold text-slate-300">
                    {roomInfo
                      ? roomInfo.room.players.find((player) => player.player_id !== roomInfo.player_id)?.name ?? "OPPONENT"
                      : "OPPONENT"}
                  </p>
                  <p className="mt-2 text-4xl font-black tabular-nums text-white">
                    {(roomInfo?.room.players.find((player) => player.player_id !== roomInfo.player_id)?.reps ?? 0).toString().padStart(2, "0")}
                  </p>
                  <p className="mt-1 text-[10px] text-slate-500">OPPONENT REPS</p>
                </div>
              </div>

              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-lime-400 transition-all"
                  style={{ width: `${Math.min(reps * 5, 100)}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {roomInfo
                  ? "คะแนนคู่แข่งจะอัปเดตจาก Server ทุก 0.5 วินาที"
                  : "สร้างหรือเข้าร่วมห้องเพื่อดูคะแนนคู่แข่ง"}
              </p>
            </div>

            <div className="panel p-5">
              <p className="mb-4 text-sm font-bold">AI ANALYSIS</p>
              <div className="metric-row">
                <span>Elbow angle</span>
                <strong>{angle === null ? "--" : `${angle.toFixed(1)}°`}</strong>
              </div>
              <div className="metric-row">
                <span>Movement phase</span>
                <strong>{phase}</strong>
              </div>
              <div className="metric-row">
                <span>Pose detection</span>
                <strong className={poseDetected ? "text-lime-400" : "text-slate-500"}>{poseDetected ? "DETECTED" : "NOT FOUND"}</strong>
              </div>
              <div className="metric-row">
                <span>AI connection</span>
                <strong className={isRunning ? "text-lime-400" : "text-slate-500"}>{isRunning ? "CONNECTED" : "OFFLINE"}</strong>
              </div>
            </div>

            <div className="rounded-2xl border border-lime-400/15 bg-lime-400/[0.06] p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-lime-300">Development status</p>
              <p className="mt-2 text-xs leading-5 text-slate-400">
                {roomInfo?.room.status === "ready"
                  ? "เชื่อมต่อกล้องทั้งสองคน แล้วให้เจ้าของห้องกด Start Match"
                  : roomInfo?.room.status === "countdown"
                    ? "เริ่มนับถอยหลังแล้ว เตรียมท่าให้พร้อม"
                    : roomInfo?.room.status === "running"
                      ? "การแข่งขันกำลังดำเนินอยู่ คะแนนจะอัปเดตจาก AI"
                      : roomInfo?.room.status === "finished"
                        ? "การแข่งขันสิ้นสุดแล้ว ดูผลผู้ชนะด้านบน"
                        : roomInfo
                          ? "ส่งรหัสห้องให้เพื่อนเพื่อให้ผู้เล่นคนที่ 2 เข้าร่วม"
                          : "สร้างห้องใหม่หรือกรอกรหัสเพื่อเข้าร่วมห้องของเพื่อน"}
              </p>
            </div>
          </section>
        </div>

        {error && (
          <div className="mt-5 rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        <footer className="mt-8 flex flex-wrap justify-between gap-2 border-t border-white/10 pt-5 text-xs text-slate-600">
          <span>REPBATTLE AI · COMPUTER VISION PROTOTYPE</span>
          <span>POWERED BY MEDIAPIPE + FASTAPI</span>
        </footer>
      </div>
    </main>
  );
}
