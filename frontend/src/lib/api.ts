import type { Analysis, ManualBox, NormalizedBox } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "Request failed.";
  } catch {
    return "Request failed.";
  }
}

export async function analyzeFile(file: File, keywords: string): Promise<Analysis> {
  const form = new FormData();
  form.append("file", file);
  form.append("keywords", keywords);

  const response = await fetch(`${API_URL}/api/analyze`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as Analysis;
}

export interface RedactedFile {
  blob: Blob;
  filename: string;
}

export async function redactFile(
  file: File,
  boxes: Array<NormalizedBox & { page: number }>,
  terms: string[],
): Promise<RedactedFile> {
  const form = new FormData();
  form.append("file", file);
  form.append("boxes", JSON.stringify(boxes));
  form.append("terms", JSON.stringify(terms));

  const response = await fetch(`${API_URL}/api/redact`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await readError(response));

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? "redacted" };
}

export function toRegion(box: ManualBox): NormalizedBox & { page: number } {
  return { page: box.page, x0: box.x0, y0: box.y0, x1: box.x1, y1: box.y1 };
}
