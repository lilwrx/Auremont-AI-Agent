import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import type { UserRole } from "../types";

interface ProtectedRouteProps {
  /** Omit to require only authentication, with no role restriction. One role or several
   * (e.g. a page shared by Sale and Customer). */
  allowedRole?: UserRole | UserRole[];
  children: ReactNode;
}

export function ProtectedRoute({ allowedRole, children }: ProtectedRouteProps) {
  const { isAuthenticated, role } = useAuth();

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  const allowed = allowedRole === undefined ? null : Array.isArray(allowedRole) ? allowedRole : [allowedRole];
  // Wrong role: redirect to home instead of bouncing back to the login screen.
  if (allowed && (!role || !allowed.includes(role))) return <Navigate to="/home" replace />;

  return <>{children}</>;
}
