import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, setUnauthorizedHandler, type CurrentUser } from "../api";

type AuthStatus = "checking" | "signed-in" | "signed-out";

interface AuthValue {
  status: AuthStatus;
  user: CurrentUser | null;
  isAdmin: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<CurrentUser | null>(null);

  // Ask the server who we are rather than trusting anything stored locally:
  // the session lives in an HttpOnly cookie this code cannot read.
  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((current) => {
        if (!cancelled) {
          setUser(current);
          setStatus("signed-in");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
          setStatus("signed-out");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Any 401 from anywhere returns the whole app to the login screen once.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus("signed-out");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const current = await api.login(email, password);
    setUser(current);
    setStatus("signed-in");
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setStatus("signed-out");
    }
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    setUser(await api.changePassword(current, next));
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      isAdmin: user?.role === "admin",
      signIn,
      signOut,
      changePassword,
    }),
    [status, user, signIn, signOut, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside an AuthProvider");
  }
  return value;
}
