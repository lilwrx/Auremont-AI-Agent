import { useCallback, useMemo, useState, type ReactNode } from "react";
import { AuthContext } from "./auth-context";
import { api } from "../api/client";
import type { UserRole } from "../types";

function read(key: string): string | null {
  return localStorage.getItem(key);
}

function isTokenValid(token: string | null): boolean {
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1])) as { exp: number };
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

function clearStoredSession() {
  ["access_token", "refresh_token", "role", "username"].forEach((k) => localStorage.removeItem(k));
}

/**
 * App-wide auth state — the navbar and every page read from this single source,
 * so logging out anywhere updates them all at once.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(() => {
    // An access token can still sit in localStorage after expiring (e.g. from an old
    // test session); checking only for its presence would set isAuthenticated=true,
    // send the user to /home, then bounce them back to /login on the first 401 —
    // they would never see Landing. Validate expiry up front instead.
    if (!isTokenValid(read("access_token"))) {
      clearStoredSession();
      return { isAuthenticated: false, role: null, username: null };
    }
    return {
      isAuthenticated: true,
      role: read("role") as UserRole | null,
      username: read("username"),
    };
  });

  const login = useCallback(
    (accessToken: string, refreshToken: string, role: UserRole, username: string) => {
      localStorage.setItem("access_token", accessToken);
      localStorage.setItem("refresh_token", refreshToken);
      localStorage.setItem("role", role);
      localStorage.setItem("username", username);
      setState({ isAuthenticated: true, role, username });
    },
    [],
  );

  const logout = useCallback(() => {
    // Notify the server for audit logging, but don't await it: JWTs are stateless,
    // so clearing the client-side token is what actually ends the session. A network
    // error here must never block logout.
    api.post("/auth/logout").catch(() => {});
    clearStoredSession();
    setState({ isAuthenticated: false, role: null, username: null });
  }, []);

  const value = useMemo(() => ({ ...state, login, logout }), [state, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
