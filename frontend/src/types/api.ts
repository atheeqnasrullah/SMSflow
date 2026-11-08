// Hand-maintained API types. Run `npm run gen:api` to generate the full OpenAPI types
// (src/types/openapi.d.ts) from a running backend.

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  role: string;
  mode: "demo" | "live";
  status: string;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  locale: string;
  email_verified: boolean;
  is_platform_admin: boolean;
  current_tenant_id: string | null;
  role: string | null;
  permissions: string[];
  workspaces: Workspace[];
}

export interface Contact {
  id: string;
  phone_e164: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  attributes: Record<string, string>;
  language: string;
  consent_status: "granted" | "revoked" | "unknown";
  created_at: string;
  group_ids: string[];
  suppressed: boolean;
}

export interface Group {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
}

export interface Suppression {
  id: string;
  phone_e164: string;
  reason: string;
  note: string | null;
  created_at: string;
}

export interface ImportJob {
  id: string;
  filename: string;
  status: string;
  total_rows: number;
  imported: number;
  updated: number;
  duplicates: number;
  invalid: number;
  error: string | null;
  has_error_report: boolean;
}

export interface Template {
  id: string;
  name: string;
  body: string;
  variables: string[];
  category: "otp" | "transactional" | "promotional";
  language: string;
  encoding: string;
  segments: number;
}

export interface CampaignStats {
  total?: number;
  queued?: number;
  submitting?: number;
  accepted?: number;
  delivered?: number;
  undelivered?: number;
  failed?: number;
  rejected?: number;
  unknown?: number;
  submitted?: number;
  spent?: number;
  delivery_rate?: number;
}

export interface Campaign {
  id: string;
  name: string;
  body: string;
  template_id: string | null;
  sender: string | null;
  category: "transactional" | "promotional";
  audience: { group_ids?: string[]; contact_ids?: string[]; numbers?: string[]; all_contacts?: boolean };
  status: "draft" | "scheduled" | "processing" | "paused" | "completed" | "cancelled";
  scheduled_at: string | null;
  recurrence: string | null;
  is_demo: boolean;
  estimated_recipients: number;
  estimated_segments: number;
  estimated_cost: number;
  skipped: Record<string, number>;
  stats: CampaignStats;
  started_at: string | null;
  completed_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface Estimate {
  recipients: number;
  segments: number;
  unit_price: number;
  cost: number;
  currency: string;
  encoding: string;
  skipped: Record<string, number>;
  is_demo: boolean;
  available_balance: number;
  demo_credits: number;
  sufficient: boolean;
  sample: { to: string; body: string; segments: number }[];
}

export interface Message {
  message_id: string;
  status: string;
  to: string;
  sender: string;
  segments: number;
  encoding: string;
  cost: number;
  currency: string;
  is_demo: boolean;
  campaign_id: string | null;
  source: string;
  error_code: string | null;
  created_at: string;
  delivered_at: string | null;
  body?: string;
  events?: { status: string; occurred_at: string }[];
}

export interface Wallet {
  balance: number;
  reserved: number;
  available: number;
  currency: string;
  demo_credits: number;
  low_balance_threshold: number;
  mode: "demo" | "live";
  price_per_segment: number;
}

export interface Package {
  id: string;
  name: string;
  description: string | null;
  price_lkr: number;
  credits: number;
  bonus_credits: number;
}

export interface LedgerEntry {
  id: string;
  type: string;
  amount: number;
  reserved_delta: number;
  balance_after: number;
  reserved_after: number;
  reference_type: string | null;
  description: string | null;
  created_at: string;
}

export interface Payment {
  id: string;
  order_id: string;
  amount: number;
  credits: number;
  bonus_credits: number;
  status: string;
  created_at: string;
  invoice_id: string | null;
  invoice_number: string | null;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  is_test: boolean;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  key?: string;
}

export interface WebhookEndpoint {
  id: string;
  url: string;
  description: string | null;
  events: string[];
  is_active: boolean;
  consecutive_failures: number;
  disabled_reason: string | null;
  secret?: string;
}

export interface WebhookDelivery {
  id: string;
  event_type: string;
  attempt: number;
  response_status: number | null;
  status: string;
  created_at: string;
}

export interface SenderId {
  id: string;
  value: string;
  status: "pending" | "approved" | "rejected";
  purpose: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  status: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface WorkspaceDetail {
  id: string;
  name: string;
  slug: string;
  business_type: string | null;
  status: string;
  mode: "demo" | "live";
  contact_email: string | null;
  contact_phone: string | null;
  address: string | null;
  live_requested_at: string | null;
}

export interface Overview {
  total_messages: number;
  total_segments: number;
  spend: number;
  submitted: number;
  delivered: number;
  delivery_rate: number;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  daily: { date: string; total: number; delivered: number; failed: number }[];
  contacts: number;
  active_campaigns: number;
}
