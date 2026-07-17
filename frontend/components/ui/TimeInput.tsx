"use client";
import { useState, useRef } from "react";
import { formatDuration } from "@/lib/utils";

export default function TimeInput({ value, onChange, rangeMax }: { value: number; onChange: (v: number) => void; rangeMax?: number }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = () => {
    setText(String(value));
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 50);
  };
  const commit = () => {
    const parsed = parseFloat(text);
    if (!isNaN(parsed) && parsed > 0) onChange(parsed);
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        step="any"
        min={0}
        className="w-16 font-mono text-xs text-gray-900 bg-indigo-50 border border-indigo-200 rounded px-1.5 py-0.5 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        value={text}
        onChange={e => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
      />
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-xs text-gray-500 cursor-pointer hover:text-indigo-600 hover:bg-indigo-50 rounded px-2 py-0.5 transition border border-dashed border-gray-300 hover:border-indigo-400 select-none group/time"
      onClick={startEdit}
      title="Click to type exact hours"
    >
      {formatDuration(value, rangeMax)}
      <span className="text-[8px] text-gray-400 group-hover/time:text-indigo-400 transition opacity-0 group-hover/time:opacity-100">✎</span>
    </span>
  );
}
