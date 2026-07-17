export function getAccessToken(): string | null {
  return localStorage.getItem("access_token");
}

export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
