export type FileKind = "pdf" | "image" | "docx";

export type Category =
  | "email"
  | "phone"
  | "card"
  | "iban"
  | "tax_id"
  | "ssn"
  | "date"
  | "url"
  | "ip"
  | "custom";

export interface NormalizedBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Detection {
  id: string;
  page: number;
  text: string;
  category: Category;
  box: [number, number, number, number] | null;
}

export interface PageInfo {
  index: number;
  width: number;
  height: number;
  image: string;
}

export interface Analysis {
  kind: FileKind;
  pages: PageInfo[];
  detections: Detection[];
  paragraphs?: string[];
}

export interface ManualBox extends NormalizedBox {
  id: string;
  page: number;
}

export const CATEGORY_LABELS: Record<Category, string> = {
  email: "Email",
  phone: "Phone",
  card: "Card number",
  iban: "IBAN",
  tax_id: "Tax ID",
  ssn: "SSN",
  date: "Date",
  url: "URL",
  ip: "IP address",
  custom: "Keyword",
};
