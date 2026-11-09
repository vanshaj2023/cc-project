"use client";

import { useState, type FormEvent } from "react";
import { CATEGORY_LABELS, type Category, type Detection, type FileKind } from "@/lib/types";

interface SidePanelProps {
  kind: FileKind;
  detections: Detection[];
  hiddenCategories: Set<Category>;
  selectedIds: Set<string>;
  manualCount: number;
  isBusy: boolean;
  isExporting: boolean;
  onToggleCategory: (category: Category) => void;
  onToggleDetection: (id: string) => void;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onClearManual: () => void;
  onAddKeywords: (keywords: string) => void;
  onExport: () => void;
  onReset: () => void;
}

export function SidePanel({
  kind,
  detections,
  hiddenCategories,
  selectedIds,
  manualCount,
  isBusy,
  isExporting,
  onToggleCategory,
  onToggleDetection,
  onSelectAll,
  onSelectNone,
  onClearManual,
  onAddKeywords,
  onExport,
  onReset,
}: SidePanelProps) {
  const [keywords, setKeywords] = useState("");

  const counts = detections.reduce<Partial<Record<Category, number>>>((acc, detection) => {
    acc[detection.category] = (acc[detection.category] ?? 0) + 1;
    return acc;
  }, {});
  const categories = Object.keys(counts) as Category[];
  const visible = detections.filter((detection) => !hiddenCategories.has(detection.category));
  const redactionCount = detections.filter((detection) => selectedIds.has(detection.id)).length + manualCount;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!keywords.trim()) return;
    onAddKeywords(keywords);
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col gap-5 rounded-2xl border border-border bg-surface p-5 lg:w-96">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted">{kind === "docx" ? "Word document" : kind === "pdf" ? "PDF" : "Image"}</span>
        <button type="button" onClick={onReset} className="text-sm text-muted transition-colors hover:text-text">
          New file
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={keywords}
          onChange={(event) => setKeywords(event.target.value)}
          placeholder="Names or words, comma separated"
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-accent"
        />
        <button
          type="submit"
          disabled={isBusy}
          className="rounded-lg bg-surface-2 px-3 py-2 text-sm transition-colors hover:bg-white/10 disabled:opacity-50"
        >
          Find
        </button>
      </form>

      {categories.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {categories.map((category) => {
            const isOff = hiddenCategories.has(category);
            return (
              <button
                key={category}
                type="button"
                onClick={() => onToggleCategory(category)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  isOff ? "border-border text-muted" : "border-accent/60 bg-accent/15 text-text"
                }`}
              >
                {CATEGORY_LABELS[category]} {counts[category]}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-muted">
        <span>{visible.length} detected</span>
        <span className="flex gap-3">
          <button type="button" onClick={onSelectAll} className="hover:text-text">
            Select all
          </button>
          <button type="button" onClick={onSelectNone} className="hover:text-text">
            None
          </button>
        </span>
      </div>

      <ul className="scroll-thin -mt-2 min-h-24 flex-1 space-y-1 overflow-y-auto pr-1">
        {visible.length === 0 && (
          <li className="py-6 text-center text-sm text-muted">
            {kind === "docx" ? "Nothing detected." : "Nothing detected. Draw boxes on the page to redact."}
          </li>
        )}
        {visible.map((detection) => (
          <li key={detection.id}>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-white/5">
              <input
                type="checkbox"
                checked={selectedIds.has(detection.id)}
                onChange={() => onToggleDetection(detection.id)}
                className="accent-accent"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{detection.text}</span>
                <span className="block text-xs text-muted">
                  {CATEGORY_LABELS[detection.category]}
                  {kind !== "docx" && ` · page ${detection.page + 1}`}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>

      {kind !== "docx" && (
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{manualCount} drawn</span>
          {manualCount > 0 && (
            <button type="button" onClick={onClearManual} className="hover:text-text">
              Clear drawn
            </button>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={onExport}
        disabled={redactionCount === 0 || isExporting}
        className="rounded-xl bg-accent px-4 py-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {isExporting ? "Redacting..." : `Redact ${redactionCount} and download`}
      </button>
    </aside>
  );
}
