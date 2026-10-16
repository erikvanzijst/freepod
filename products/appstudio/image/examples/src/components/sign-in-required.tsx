import { LogIn } from "lucide-react";
import { useLocation } from "react-router";
import { Button } from "@/components/ui/button";

// Shown instead of a page that needs a signed-in user. Signing in is a link to
// the platform, which returns to this page afterwards (Sign in with Freepod
// must be enabled for the deployment).
export function SignInRequired() {
  const { pathname } = useLocation();
  return (
    <div className="flex flex-col items-center gap-4 rounded-xl border bg-card px-6 py-12 text-center">
      <h2 className="text-lg font-semibold">Sign in to continue</h2>
      <p className="max-w-sm text-sm text-muted-foreground">This page shows your own data, so it needs to know who you are.</p>
      <Button asChild>
        <a href={`/.freepod/auth/login?rd=${encodeURIComponent(pathname)}`}>
          <LogIn />
          Sign in with Freepod
        </a>
      </Button>
    </div>
  );
}
