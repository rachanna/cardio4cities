// The API client (LLD-4 §2-3). Same origin, so the session cookie goes with every
// request, the event stream included (LLD-4 ID-01). Types come from the OpenAPI
// document (`poe types`); never edit lib/api-types.ts by hand.
import type { components } from "./api-types";

type S = components["schemas"];
export type FactCard = S["FactCard"];
export type SlotRow = S["SlotRow"];
export type SlotInfo = S["SlotInfo"];
export type CareItem = S["CareItem"];
export type BriefResponse = S["BriefResponse"];
export type CityItem = S["CityItem"];
export type PlaceCandidate = S["PlaceCandidate"];
export type ResolveResponse = S["ResolveResponse"];
export type StartRunResponse = S["StartRunResponse"];
export type FindingsResponse = S["FindingsResponse"];
export type EntitiesResponse = S["EntitiesResponse"];
export type EntityResponse = S["EntityResponse"];
export type EntityEdge = S["EntityEdgeOut"];
export type EvidenceResponse = S["EvidenceResponse"];
export type AskResponse = S["AskResponse"];
export type AnswerSentence = S["AnswerSentenceOut"];
export type SessionInfo = S["SessionInfo"];
export type DiagramResponse = S["DiagramResponse"];
export type BadgeCard = S["BadgeCard"];

export const API = "/api/v1";

/** The error envelope (LLD-4 §6): a code for code, a message for people. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API + path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "The service cannot be reached. Check the connection.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "error",
      error.message ?? "Something went wrong. Try again.",
      error.details ?? {},
    );
  }
  return data as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
export const del = <T>(path: string) => request<T>("DELETE", path);

export function query(params: Record<string, string | number | undefined | null>): string {
  const pairs = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return pairs.length ? "?" + new URLSearchParams(pairs.map(([k, v]) => [k, String(v)])).toString() : "";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "date not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export const DIMENSIONS: Record<string, string> = {
  D1: "Governance",
  D2: "Burden",
  D3: "Programmes",
  D4: "Policy",
  D5: "Stakeholders",
  D6: "Data",
};
