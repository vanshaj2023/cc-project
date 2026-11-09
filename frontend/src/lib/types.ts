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
  | "custom"
  | "person_name"
  | "organization"
  | "address"
  | "location"
  | "date_of_birth"
  | "fiscal_code"
  | "health_card"
  | "id_number"
  | "other";

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
  warning?: string;
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
  person_name: "Name",
  organization: "Organization",
  address: "Address",
  location: "Location",
  date_of_birth: "Date of birth",
  fiscal_code: "Fiscal code",
  health_card: "Health card",
  id_number: "ID number",
  other: "Other",
};
