export interface ApiHealth {
  status: string;
  time: string;
}

export interface ApiConflict {
  conflict_id: string;
  target_id: string;
  left_observation_id: string;
  right_observation_id: string;
  classification_marking: string;
  distance_meters: number;
  status: string;
  conflict_reason: string;
  created_at: string;
}

export interface ApiRecentObservation {
  observation_id: string;
  target_id: string;
  source_id: string;
  source_type: string;
  classification_marking: string;
  observed_at: string;
  lat: number;
  lon: number;
  unit_type: string;
}

export interface ApiRequestOptions {
  baseUrl?: string;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 8000;

function resolveBaseUrl(explicitBaseUrl?: string): string {
  const envBaseUrl = import.meta.env.VITE_SHAKTI_API_BASE_URL as string | undefined;
  return (explicitBaseUrl ?? envBaseUrl ?? "").trim();
}

function resolveAuthHeaders(): Record<string, string> {
  const bearerToken = (import.meta.env.VITE_SHAKTI_BEARER_TOKEN as string | undefined)?.trim() ?? "";
  if (bearerToken) {
    return { Authorization: `Bearer ${bearerToken}` };
  }

  const claims = (import.meta.env.VITE_SHAKTI_AUTH_CLAIMS as string | undefined)?.trim() ?? "";
  const signature =
    (import.meta.env.VITE_SHAKTI_AUTH_SIGNATURE as string | undefined)?.trim() ?? "";
  if (claims && signature) {
    return {
      "X-Auth-Claims": claims,
      "X-Auth-Signature": signature,
    };
  }
  return {};
}

async function fetchJson<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const baseUrl = resolveBaseUrl(options.baseUrl);
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = baseUrl ? `${baseUrl}${normalizedPath}` : normalizedPath;

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...resolveAuthHeaders(),
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchApiHealth(options?: ApiRequestOptions): Promise<ApiHealth> {
  return fetchJson<ApiHealth>("/healthz", options);
}

export async function fetchPendingConflicts(
  limit = 100,
  options?: ApiRequestOptions,
): Promise<ApiConflict[]> {
  const safeLimit = Math.max(1, Math.min(limit, 500));
  return fetchJson<ApiConflict[]>(`/v1/conflicts/pending?limit=${safeLimit}`, options);
}

export async function fetchRecentObservations(
  limit = 200,
  options?: ApiRequestOptions,
): Promise<ApiRecentObservation[]> {
  const safeLimit = Math.max(1, Math.min(limit, 500));
  return fetchJson<ApiRecentObservation[]>(`/v1/observations/recent?limit=${safeLimit}`, options);
}
