import type { Detection } from "@/lib/types";

interface DocxPreviewProps {
  paragraphs: string[];
  detections: Detection[];
  selectedIds: Set<string>;
}

function escapePattern(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function DocxPreview({ paragraphs, detections, selectedIds }: DocxPreviewProps) {
  const redacted = detections.filter((detection) => selectedIds.has(detection.id)).map((detection) => detection.text);
  const pattern = redacted.length
    ? new RegExp(`(${[...redacted].sort((a, b) => b.length - a.length).map(escapePattern).join("|")})`, "gi")
    : null;
  const lowered = new Set(redacted.map((text) => text.toLowerCase()));

  return (
    <div className="w-full rounded-lg bg-white px-10 py-12 text-sm leading-relaxed text-neutral-900 shadow-2xl shadow-black/60">
      {paragraphs.map((paragraph, index) => (
        <p key={index} className="mb-3">
          {(pattern ? paragraph.split(pattern) : [paragraph]).map((part, partIndex) =>
            lowered.has(part.toLowerCase()) ? (
              <span key={partIndex} className="rounded-sm bg-black text-black">
                {part}
              </span>
            ) : (
              <span key={partIndex}>{part}</span>
            ),
          )}
        </p>
      ))}
    </div>
  );
}
