import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

interface Flash {
  notice: string;
  error: string;
  setNotice: (message: string) => void;
  setError: (message: string) => void;
  clear: () => void;
}

const FlashContext = createContext<Flash | null>(null);

// One place for the green "notice" and red "error" messages; cleared when the screen changes.
export function FlashProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const { pathname } = useLocation();
  const clear = useCallback(() => {
    setNotice("");
    setError("");
  }, []);
  useEffect(clear, [pathname, clear]);
  const value = useMemo(
    () => ({ notice, error, setNotice, setError, clear }),
    [notice, error, clear],
  );
  return <FlashContext.Provider value={value}>{children}</FlashContext.Provider>;
}

export function useFlash(): Flash {
  const value = useContext(FlashContext);
  if (!value) throw new Error("useFlash must be used inside FlashProvider");
  return value;
}
