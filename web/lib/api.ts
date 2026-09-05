export const API_BASE =
  process.env.NEXT_PUBLIC_SDEBRIS_API_URL ?? "http://127.0.0.1:8000";

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

export async function streamSse<T>(
  path: string,
  onEvent: (event: T) => void,
  signal: AbortSignal
) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    signal
  });
  if (!response.ok || !response.body) throw new Error("Progress stream unavailable");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const data = frame.split("\n").find((line) => line.startsWith("data: "));
      if (data) onEvent(JSON.parse(data.slice(6)) as T);
    }
  }
}
