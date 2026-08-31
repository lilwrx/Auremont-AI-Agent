import { api } from "./client";

export type NewsTopic =
  | "official_update"
  | "project_progress"
  | "infrastructure"
  | "market_potential"
  | "promotion";

export type NewsStatus =
  | "draft"
  | "pending_review"
  | "changes_requested"
  | "rejected"
  | "published"
  | "archived";

export interface NewsDraftPayload {
  title: string;
  summary: string | null;
  content: string;
  image_url: string | null;
  topic: NewsTopic;
  project_names: string[];
}

export interface NewsArticle {
  id: number;
  canonicalUrl: string;
  sourceId: string;
  sourceName: string;
  title: string;
  summary: string | null;
  content: string | null;
  imageUrl: string | null;
  topic: NewsTopic;
  projectNames: string[];
  publishedAt: string | null;
  fetchedAt: string;
}

export interface NewsWorkflowArticle extends NewsArticle {
  status: NewsStatus;
  authorId: number | null;
  authorName: string;
  reviewerId: number | null;
  reviewerName: string | null;
  reviewNote: string | null;
  submittedAt: string | null;
  reviewedAt: string | null;
  expiresAt: string;
  createdAt: string;
  updatedAt: string;
}

interface ApiNewsArticle {
  id: number;
  canonical_url: string;
  source_id: string;
  source_name: string;
  title: string;
  summary: string | null;
  content: string | null;
  image_url: string | null;
  topic: NewsTopic;
  project_names: string[];
  published_at: string | null;
  fetched_at: string;
}

interface ApiNewsWorkflowArticle extends ApiNewsArticle {
  status: NewsStatus;
  author_id: number | null;
  author_name: string;
  reviewer_id: number | null;
  reviewer_name: string | null;
  review_note: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  expires_at: string;
  created_at: string;
  updated_at: string;
}

interface ApiNewsList<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface NewsPageResult<T = NewsArticle> {
  items: T[];
  total: number;
}

function mapArticle(row: ApiNewsArticle): NewsArticle {
  return {
    id: row.id,
    canonicalUrl: row.canonical_url,
    sourceId: row.source_id,
    sourceName: row.source_name,
    title: row.title,
    summary: row.summary,
    content: row.content,
    imageUrl: row.image_url,
    topic: row.topic,
    projectNames: row.project_names,
    publishedAt: row.published_at,
    fetchedAt: row.fetched_at,
  };
}

function mapWorkflowArticle(row: ApiNewsWorkflowArticle): NewsWorkflowArticle {
  return {
    ...mapArticle(row),
    status: row.status,
    authorId: row.author_id,
    authorName: row.author_name,
    reviewerId: row.reviewer_id,
    reviewerName: row.reviewer_name,
    reviewNote: row.review_note,
    submittedAt: row.submitted_at,
    reviewedAt: row.reviewed_at,
    expiresAt: row.expires_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function fetchNews(params: {
  offset?: number;
  limit?: number;
  topic?: NewsTopic;
  query?: string;
}): Promise<NewsPageResult> {
  const search = new URLSearchParams();
  search.set("offset", String(params.offset ?? 0));
  search.set("limit", String(params.limit ?? 12));
  if (params.topic) search.set("topic", params.topic);
  if (params.query?.trim()) search.set("q", params.query.trim());
  const response = await api.get<ApiNewsList<ApiNewsArticle>>(`/news?${search.toString()}`);
  return { items: response.items.map(mapArticle), total: response.total };
}

export async function fetchNewsArticle(id: number): Promise<NewsArticle> {
  return mapArticle(await api.get<ApiNewsArticle>(`/news/${id}`));
}

export async function fetchMyNews(status?: NewsStatus): Promise<NewsPageResult<NewsWorkflowArticle>> {
  const search = new URLSearchParams({ limit: "100" });
  if (status) search.set("status", status);
  const response = await api.get<ApiNewsList<ApiNewsWorkflowArticle>>(`/sale/news?${search.toString()}`);
  return { items: response.items.map(mapWorkflowArticle), total: response.total };
}

export async function createNewsDraft(payload: NewsDraftPayload): Promise<NewsWorkflowArticle> {
  return mapWorkflowArticle(await api.post<ApiNewsWorkflowArticle>("/sale/news", payload));
}

export async function updateNewsDraft(id: number, payload: NewsDraftPayload): Promise<NewsWorkflowArticle> {
  return mapWorkflowArticle(await api.put<ApiNewsWorkflowArticle>(`/sale/news/${id}`, payload));
}

export async function submitNewsDraft(id: number): Promise<NewsWorkflowArticle> {
  return mapWorkflowArticle(await api.post<ApiNewsWorkflowArticle>(`/sale/news/${id}/submit`));
}

export async function deleteNewsDraft(id: number): Promise<void> {
  await api.delete<void>(`/sale/news/${id}`);
}

export async function uploadNewsImage(file: File): Promise<string> {
  const body = new FormData();
  body.append("image", file);
  const response = await api.postForm<{ image_url: string }>("/sale/news/images", body);
  return response.image_url;
}

export async function fetchAdminNews(status?: NewsStatus): Promise<NewsPageResult<NewsWorkflowArticle>> {
  const search = new URLSearchParams({ limit: "100" });
  if (status) search.set("status", status);
  const response = await api.get<ApiNewsList<ApiNewsWorkflowArticle>>(`/admin/news?${search.toString()}`);
  return { items: response.items.map(mapWorkflowArticle), total: response.total };
}

async function reviewAction(
  id: number,
  action: "approve" | "request-changes" | "reject" | "archive",
  note: string | null,
): Promise<NewsWorkflowArticle> {
  return mapWorkflowArticle(
    await api.post<ApiNewsWorkflowArticle>(`/admin/news/${id}/${action}`, { note }),
  );
}

export const approveNews = (id: number, note: string | null) => reviewAction(id, "approve", note);
export const requestNewsChanges = (id: number, note: string) => reviewAction(id, "request-changes", note);
export const rejectNews = (id: number, note: string) => reviewAction(id, "reject", note);
export const archiveNews = (id: number, note: string | null) => reviewAction(id, "archive", note);
