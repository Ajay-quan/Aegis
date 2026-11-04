"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const r = await fetch(`/api/aegis/${path}`, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (r.status === 401) {
    window.location.href = "/login?expired=1";
    throw new ApiError(401, "session expired");
  }
  if (!r.ok) {
    let msg = `request failed (${r.status})`;
    try { msg = (await r.json()).error?.message ?? msg; } catch { /* non-JSON */ }
    throw new ApiError(r.status, msg);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

/** Polls `path` every `interval` ms while the tab is visible. */
export function useLive<T>(path: string | null, interval = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      setData(await api<T>(path));
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "error");
    }
  }, [path]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (document.visibilityState === "visible") await load();
      if (alive) timer.current = setTimeout(tick, interval);
    };
    tick();
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [load, interval]);

  return { data, error, updatedAt, reload: load };
}

// -- toasts -------------------------------------------------------------------
type Toast = { id: number; tone: "ok" | "bad" | "info"; text: string };
let toasts: Toast[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

export function toast(text: string, tone: Toast["tone"] = "info") {
  const id = Date.now() + Math.random();
  toasts = [...toasts, { id, tone, text }];
  emit();
  setTimeout(() => { toasts = toasts.filter((t) => t.id !== id); emit(); }, 3500);
}

export function useToasts() {
  return useSyncExternalStore(
    (f) => { subs.add(f); return () => subs.delete(f); },
    () => toasts,
    () => toasts,
  );
}

export function timeAgo(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
