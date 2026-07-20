export type User = {
  id: string;
  email: string;
  display_name?: string | null;
  created_at: string;
};

export type AuthResponse = {
  user: User;
  access_token: string;
  token_type: string;
};

const TOKEN_KEY = "finance_agent_token";
const USER_KEY = "finance_agent_user";

function parseApiError(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const data = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail) && data.detail[0]?.msg) {
      return data.detail.map((item) => item.msg).filter(Boolean).join("；");
    }
  } catch {
    // keep raw text below
  }
  if (text.includes("Not Found") || text.includes("404")) {
    return "后端接口不存在，请关闭旧的后端窗口后重新运行 scripts/start.ps1";
  }
  if (text.includes("Failed to fetch") || text.includes("NetworkError")) {
    return "无法连接后端 API，请确认 FastAPI 已在 8000 端口启动";
  }
  return text.length > 200 ? fallback : text;
}

export function getApiBase(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000/api"
  );
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function saveAuth(auth: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, auth.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export async function register(
  email: string,
  password: string,
  displayName?: string,
): Promise<AuthResponse> {
  const res = await fetch(`${getApiBase()}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName || undefined,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(text, "注册失败"));
  }
  const data = (await res.json()) as AuthResponse;
  saveAuth(data);
  return data;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${getApiBase()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(text, "登录失败"));
  }
  const data = (await res.json()) as AuthResponse;
  saveAuth(data);
  return data;
}

export async function fetchCurrentUser(): Promise<User | null> {
  const token = getStoredToken();
  if (!token) return null;

  const res = await fetch(`${getApiBase()}/auth/me`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    clearAuth();
    return null;
  }

  const user = (await res.json()) as User;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  return user;
}
