import { createContext } from "react";
import type { UserRole } from "../types";

export interface AuthContextValue {
  isAuthenticated: boolean;
  role: UserRole | null;
  username: string | null;
  login: (accessToken: string, refreshToken: string, role: UserRole, username: string) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
