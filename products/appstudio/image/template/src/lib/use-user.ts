import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type User = { id: string; email: string; name: string };

// The signed-in user (see server/auth.ts): undefined while loading, then the
// user or null.
export function useUser() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => {
    api<{ user: User | null }>("/me").then((r) => setUser(r.user), () => setUser(null));
  }, []);
  return user;
}
