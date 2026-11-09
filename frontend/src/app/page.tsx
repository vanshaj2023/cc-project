"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { analyzeFile, redactFile, toRegion } from "@/lib/api";
import type { Analysis, Category, ManualBox, NormalizedBox } from "@/lib/types";
import { DocxPreview } from "@/components/docx-preview";
import { DropZone } from "@/components/drop-zone";
import { PageCanvas } from "@/components/page-canvas";
import { SidePanel } from "@/components/side-panel";

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [hiddenCategories, setHiddenCategories] = useState<Set<Category>>(new Set());
  const [manualBoxes, setManualBoxes] = useState<ManualBox[]>([]);
  const [keywords, setKeywords] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const heroRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);

  const hasAnalysis = analysis !== null;

  useEffect(() => {
    if (hasAnalysis || !heroRef.current) return;
    const context = gsap.context(() => {
      gsap.from("[data-reveal]", { opacity: 0, y: 32, duration: 0.8, stagger: 0.1, ease: "power3.out" });
    }, heroRef);
    return () => context.revert();
  }, [hasAnalysis]);

  useEffect(() => {
    if (!hasAnalysis || !workspaceRef.current) return;
    const context = gsap.context(() => {
      gsap.from("[data-reveal]", { opacity: 0, y: 24, duration: 0.7, stagger: 0.12, ease: "power3.out" });
    }, workspaceRef);
    return () => context.revert();
  }, [hasAnalysis]);

  const applyAnalysis = (result: Analysis, hidden: Set<Category>) => {
    setAnalysis(result);
    setSelectedIds(
      new Set(result.detections.filter((detection) => !hidden.has(detection.category)).map((detection) => detection.id)),
    );
  };

  const scan = async (target: File, extraKeywords: string, hidden: Set<Category>) => {
    setError(null);
    setIsAnalyzing(true);
    try {
      applyAnalysis(await analyzeFile(target, extraKeywords), hidden);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not scan the file.");
      return false;
    } finally {
      setIsAnalyzing(false);
    }
    return true;
  };

  const handleFile = async (selected: File) => {
    const succeeded = await scan(selected, "", new Set());
    if (!succeeded) return;
    setFile(selected);
    setKeywords("");
    setHiddenCategories(new Set());
    setManualBoxes([]);
  };

  const handleAddKeywords = async (input: string) => {
    if (!file) return;
    const combined = [keywords, input].filter(Boolean).join(",");
    const succeeded = await scan(file, combined, hiddenCategories);
    if (succeeded) setKeywords(combined);
  };

  const handleReset = () => {
    setFile(null);
    setAnalysis(null);
    setSelectedIds(new Set());
    setHiddenCategories(new Set());
    setManualBoxes([]);
    setKeywords("");
    setError(null);
  };

  const toggleDetection = (id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleCategory = (category: Category) => {
    if (!analysis) return;
    const ids = analysis.detections.filter((detection) => detection.category === category).map((detection) => detection.id);
    const isHidden = hiddenCategories.has(category);

    setHiddenCategories((previous) => {
      const next = new Set(previous);
      if (isHidden) next.delete(category);
      else next.add(category);
      return next;
    });
    setSelectedIds((previous) => {
      const next = new Set(previous);
      ids.forEach((id) => (isHidden ? next.add(id) : next.delete(id)));
      return next;
    });
  };

  const selectAll = () => {
    if (!analysis) return;
    setSelectedIds(
      new Set(
        analysis.detections.filter((detection) => !hiddenCategories.has(detection.category)).map((detection) => detection.id),
      ),
    );
  };

  const addManualBox = (page: number, box: NormalizedBox) => {
    setManualBoxes((previous) => [...previous, { ...box, page, id: crypto.randomUUID() }]);
  };

  const handleExport = async () => {
    if (!file || !analysis) return;
    setError(null);
    setIsExporting(true);
    try {
      const chosen = analysis.detections.filter((detection) => selectedIds.has(detection.id));
      const detectionBoxes = chosen.flatMap((detection) =>
        detection.box
          ? [{ page: detection.page, x0: detection.box[0], y0: detection.box[1], x1: detection.box[2], y1: detection.box[3] }]
          : [],
      );
      const result = await redactFile(
        file,
        [...detectionBoxes, ...manualBoxes.map(toRegion)],
        chosen.map((detection) => detection.text),
      );
      downloadBlob(result.blob, result.filename);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Redaction failed.");
    } finally {
      setIsExporting(false);
    }
  };

  if (!analysis || !file) {
    return (
      <main ref={heroRef} className="grid min-h-screen place-items-center px-6 py-16">
        <div className="flex w-full max-w-xl flex-col items-center gap-10 text-center">
          <div className="space-y-4">
            <h1 data-reveal className="text-5xl font-medium tracking-tight sm:text-6xl">
              Redact anything.
            </h1>
            <p data-reveal className="text-muted">
              Black out sensitive data in images, PDFs and Word files. Draw it yourself or let detection find it.
            </p>
          </div>
          <div data-reveal className="flex w-full justify-center">
            <DropZone disabled={isAnalyzing} onFile={handleFile} />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      </main>
    );
  }

  return (
    <main ref={workspaceRef} className="flex min-h-screen flex-col gap-5 p-4 lg:h-screen lg:flex-row lg:p-6">
      <section data-reveal className="scroll-thin flex min-h-0 flex-1 flex-col items-center gap-6 overflow-y-auto rounded-2xl pb-6 lg:px-4">
        <p className="text-sm text-muted">{file.name}. Drag on the page to draw a box. Click a detection to toggle it.</p>
        <div className="flex w-full max-w-3xl flex-col gap-6">
          {analysis.kind === "docx" ? (
            <DocxPreview
              paragraphs={analysis.paragraphs ?? []}
              detections={analysis.detections}
              selectedIds={selectedIds}
            />
          ) : (
            analysis.pages.map((page) => (
              <PageCanvas
                key={page.index}
                page={page}
                detections={analysis.detections.filter(
                  (detection) => detection.page === page.index && !hiddenCategories.has(detection.category),
                )}
                selectedIds={selectedIds}
                manualBoxes={manualBoxes.filter((box) => box.page === page.index)}
                onToggleDetection={toggleDetection}
                onAddBox={addManualBox}
                onRemoveBox={(id) => setManualBoxes((previous) => previous.filter((box) => box.id !== id))}
              />
            ))
          )}
        </div>
      </section>

      <div data-reveal className="flex min-h-0 flex-col gap-3 lg:h-full">
        <SidePanel
          kind={analysis.kind}
          detections={analysis.detections}
          hiddenCategories={hiddenCategories}
          selectedIds={selectedIds}
          manualCount={manualBoxes.length}
          isBusy={isAnalyzing}
          isExporting={isExporting}
          onToggleCategory={toggleCategory}
          onToggleDetection={toggleDetection}
          onSelectAll={selectAll}
          onSelectNone={() => setSelectedIds(new Set())}
          onClearManual={() => setManualBoxes([])}
          onAddKeywords={handleAddKeywords}
          onExport={handleExport}
          onReset={handleReset}
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        {analysis.warning && <p className="text-sm text-muted">{analysis.warning}</p>}
      </div>
    </main>
  );
}
