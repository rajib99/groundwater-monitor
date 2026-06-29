"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { LiveReadingMessage, Reading } from "@/types/api";

export type WsStatus = "connecting" | "connected" | "disconnected" | "error";

interface UseWebSocketOptions {
  siteId?: number;
  onReading?: (reading: Reading, siteId: number) => void;
}

export function useWebSocket({ siteId, onReading }: UseWebSocketOptions = {}) {
  const [status, setStatus] = useState<WsStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);

  const connect = useCallback(() => {
    if (!isMounted.current) return;

    const wsBase =
      process.env.NEXT_PUBLIC_WS_URL ??
      (typeof window !== "undefined"
        ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
        : "ws://localhost:8000");

    const url = siteId
      ? `${wsBase}/ws/live-feed?site_id=${siteId}`
      : `${wsBase}/ws/live-feed`;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMounted.current) return;
      setStatus("connected");
    };

    ws.onmessage = (evt) => {
      if (!isMounted.current) return;
      try {
        const msg: LiveReadingMessage = JSON.parse(evt.data);
        if (msg.event === "reading" && msg.data && msg.site_id !== null) {
          onReading?.(msg.data, msg.site_id!);
        }
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      if (!isMounted.current) return;
      setStatus("error");
    };

    ws.onclose = () => {
      if (!isMounted.current) return;
      setStatus("disconnected");
      reconnectTimer.current = setTimeout(() => {
        if (isMounted.current) connect();
      }, 5_000);
    };
  }, [siteId, onReading]);

  useEffect(() => {
    isMounted.current = true;
    connect();

    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 30_000);

    return () => {
      isMounted.current = false;
      clearInterval(ping);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { status };
}
