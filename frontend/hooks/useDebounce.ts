"use client";
import { useRef, useCallback } from "react";

export function useDebounce() {
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const debounce = useCallback((key: string, fn: () => void, delay = 500) => {
    if (timers.current[key]) clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(fn, delay);
  }, []);

  return debounce;
}
