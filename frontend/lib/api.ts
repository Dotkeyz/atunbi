import { getAuthHeaders } from "@/lib/auth";
import { API_URL } from "@/lib/constants";

export { API_URL };

export async function login(username: string, password: string) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Login failed");
  }
  const data = await res.json();
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("username", username);
  return data;
}

export async function register(username: string, password: string) {
  const res = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Registration failed");
  }
  const data = await res.json();
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("username", username);
  return data;
}

export async function getStats() {
  const res = await fetch(`${API_URL}/api/v1/stats`, { headers: getAuthHeaders() });
  return res.json();
}

export function streamStats(onStats: (stats: any) => void): () => void {
  let controller = new AbortController();
  let stopped = false;
  let retryDelay = 1000;

  async function waitForServer(): Promise<boolean> {
    for (let attempt = 0; attempt < 10 && !stopped; attempt++) {
      try {
        const res = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(2000) });
        if (res.ok) return true;
      } catch {}
      if (!stopped) await sleep(Math.min(retryDelay * Math.pow(1.5, attempt), 8000));
    }
    return false;
  }

  async function connect() {
    while (!stopped) {
      const alive = await waitForServer();
      if (!alive || stopped) break;

      try {
        controller = new AbortController();
        const headers = getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/stats/stream`, { headers, signal: controller.signal });
        if (!res.ok || !res.body) { retryDelay = Math.min(retryDelay * 2, 30000); await sleep(retryDelay); continue; }

        retryDelay = 1000;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try { onStats(JSON.parse(line.slice(6))); } catch {}
            }
          }
        }
      } catch {
        retryDelay = Math.min(retryDelay * 2, 30000);
      }
      if (!stopped) await sleep(retryDelay);
    }
  }

  connect();

  return () => { stopped = true; controller.abort(); };
}

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

export async function getConfig() {
  const res = await fetch(`${API_URL}/api/v1/config`, { headers: getAuthHeaders() });
  return res.json();
}

export async function updateConfig(config: any) {
  const res = await fetch(`${API_URL}/api/v1/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(config),
  });
  return res.json();
}

export async function triggerDream() {
  const res = await fetch(`${API_URL}/api/v1/dream`, { method: "POST", headers: getAuthHeaders() });
  return res.json();
}

export async function triggerDreamStream(onStep: (step: {step: string, detail: string, pruned?: number, retained?: number, episodes_created?: number, facts_extracted?: number, progress?: number, total?: number, cluster?: number, total_eligible?: number}) => void): Promise<any> {
  const res = await fetch(`${API_URL}/api/v1/dream/stream`, { method: "POST", headers: getAuthHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: any = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onStep(data);
          if (data.step === "done") finalResult = data;
        } catch {}
      }
    }
  }
  return finalResult;
}

export async function streamChat(message: string, conversationId: string | null, onToken: (token: string) => void, signal?: AbortSignal, onAgentStep?: (step: {action: string, detail: string}) => void): Promise<string> {
  const body: any = { message };
  if (conversationId) body.conversation_id = conversationId;

  const res = await fetch(`${API_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(body),
    signal,
  });
  const reader = res.body?.getReader();
  if (!reader) return "";
  const decoder = new TextDecoder();
  let buffer = "";
  let capturedConvId = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        const lines = buffer.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") return capturedConvId;
            if (data.startsWith("[CONVERSATION_ID] ")) { capturedConvId = data.slice(18); continue; }
            if (data !== "") onToken(data);
          }
        }
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes("\n\n")) {
        const eventEnd = buffer.indexOf("\n\n");
        const event = buffer.substring(0, eventEnd);
        buffer = buffer.substring(eventEnd + 2);

        const lines = event.split("\n");
        let eventData = "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            eventData += (eventData ? "\n" : "") + line.slice(6);
          }
        }
        if (eventData === "[DONE]") return capturedConvId;
        if (eventData.startsWith("[CONVERSATION_ID] ")) { capturedConvId = eventData.slice(18); continue; }
        if (eventData.startsWith("[AGENT_STEP] ") && onAgentStep) {
          try { onAgentStep(JSON.parse(eventData.slice(13))); } catch {}
          continue;
        }
        if (eventData !== "") onToken(eventData);
      }
    }
  } finally { reader.releaseLock(); }
  return capturedConvId;
}

export async function getConversations() {
  const res = await fetch(`${API_URL}/api/v1/history`, { headers: getAuthHeaders() });
  return res.json();
}

export async function getConversationMessages(convId: string) {
  const res = await fetch(`${API_URL}/api/v1/history/${convId}`, { headers: getAuthHeaders() });
  return res.json();
}

export async function deleteConversation(convId: string) {
  const res = await fetch(`${API_URL}/api/v1/history/${convId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  return res.json();
}
