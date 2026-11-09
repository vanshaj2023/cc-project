"use client";

import { useRef, useState, type PointerEvent } from "react";
import type { Detection, ManualBox, NormalizedBox, PageInfo } from "@/lib/types";

const MIN_BOX_SIZE = 0.006;

interface PageCanvasProps {
  page: PageInfo;
  detections: Detection[];
  selectedIds: Set<string>;
  manualBoxes: ManualBox[];
  onToggleDetection: (id: string) => void;
  onAddBox: (page: number, box: NormalizedBox) => void;
  onRemoveBox: (id: string) => void;
}

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function toStyle(box: NormalizedBox) {
  return {
    left: `${box.x0 * 100}%`,
    top: `${box.y0 * 100}%`,
    width: `${(box.x1 - box.x0) * 100}%`,
    height: `${(box.y1 - box.y0) * 100}%`,
  };
}

export function PageCanvas({
  page,
  detections,
  selectedIds,
  manualBoxes,
  onToggleDetection,
  onAddBox,
  onRemoveBox,
}: PageCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const originRef = useRef<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<NormalizedBox | null>(null);

  const readPoint = (event: PointerEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return null;
    return {
      x: clamp((event.clientX - rect.left) / rect.width),
      y: clamp((event.clientY - rect.top) / rect.height),
    };
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const point = readPoint(event);
    if (!point) return;
    originRef.current = point;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDraft({ x0: point.x, y0: point.y, x1: point.x, y1: point.y });
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const origin = originRef.current;
    const point = readPoint(event);
    if (!origin || !point) return;
    setDraft({
      x0: Math.min(origin.x, point.x),
      y0: Math.min(origin.y, point.y),
      x1: Math.max(origin.x, point.x),
      y1: Math.max(origin.y, point.y),
    });
  };

  const handlePointerUp = () => {
    originRef.current = null;
    if (draft && draft.x1 - draft.x0 > MIN_BOX_SIZE && draft.y1 - draft.y0 > MIN_BOX_SIZE) {
      onAddBox(page.index, draft);
    }
    setDraft(null);
  };

  return (
    <div
      ref={containerRef}
      data-page={page.index}
      className="relative w-full touch-none select-none overflow-hidden rounded-lg bg-white shadow-2xl shadow-black/60"
      style={{ aspectRatio: `${page.width} / ${page.height}`, cursor: "crosshair" }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={page.image} alt={`Page ${page.index + 1}`} draggable={false} className="pointer-events-none h-full w-full" />

      {detections.map((detection) => {
        if (!detection.box) return null;
        const [x0, y0, x1, y1] = detection.box;
        const isSelected = selectedIds.has(detection.id);
        return (
          <button
            key={detection.id}
            type="button"
            title={isSelected ? "Click to keep visible" : "Click to redact"}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => onToggleDetection(detection.id)}
            className={`absolute cursor-pointer transition-colors duration-150 ${
              isSelected ? "bg-black" : "border border-dashed border-accent bg-accent/15 hover:bg-accent/30"
            }`}
            style={toStyle({ x0, y0, x1, y1 })}
          />
        );
      })}

      {manualBoxes.map((box) => (
        <div key={box.id} className="group absolute bg-black" style={toStyle(box)}>
          <button
            type="button"
            aria-label="Remove redaction"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => onRemoveBox(box.id)}
            className="absolute -right-2 -top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-danger text-xs font-medium text-black group-hover:flex"
          >
            x
          </button>
        </div>
      ))}

      {draft && <div className="absolute border border-accent bg-black/70" style={toStyle(draft)} />}
    </div>
  );
}
