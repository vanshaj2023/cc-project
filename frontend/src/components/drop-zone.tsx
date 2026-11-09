"use client";

import { useRef, useState } from "react";

const ACCEPTED = ".pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp";

interface DropZoneProps {
  disabled: boolean;
  onFile: (file: File) => void;
}

export function DropZone({ disabled, onFile }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) onFile(file);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(event) => {
        if (!disabled && (event.key === "Enter" || event.key === " ")) inputRef.current?.click();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        if (!disabled) handleFiles(event.dataTransfer.files);
      }}
      className={`group flex w-full max-w-xl cursor-pointer flex-col items-center gap-3 rounded-2xl border border-dashed px-8 py-14 text-center transition-colors duration-300 ${
        isDragging ? "border-accent bg-accent/10" : "border-white/15 bg-surface hover:border-accent/60"
      } ${disabled ? "pointer-events-none opacity-60" : ""}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={(event) => {
          handleFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <span className="text-lg font-medium">{disabled ? "Scanning document..." : "Drop a file to redact"}</span>
      <span className="text-sm text-muted">PDF, DOCX, PNG, JPG or WEBP, up to 25 MB</span>
    </div>
  );
}
