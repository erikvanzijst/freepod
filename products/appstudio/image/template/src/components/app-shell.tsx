import { Link, Outlet } from "react-router";
import { HostedOnFreepod } from "@/components/hosted-on-freepod";
import { appName } from "@/config";
import { useUser } from "@/lib/use-user";

// Every page renders inside this frame: header, page content, footer.
export function AppShell() {
  const user = useUser();
  return (
    <div className="relative flex min-h-svh flex-col">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-96 bg-[radial-gradient(60%_100%_at_50%_0%,color-mix(in_oklch,var(--brand-from)_14%,transparent),transparent)]"
      />
      <header className="sticky top-0 z-40 border-b bg-background/75 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-4 px-6">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
            <span
              aria-hidden
              className="grid size-7 place-items-center rounded-md bg-gradient-to-br from-brand-from to-brand-to text-sm text-white shadow-sm"
            >
              {appName.charAt(0)}
            </span>
            {appName}
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            {user && <span className="text-muted-foreground">{user.name || user.email}</span>}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
        <Outlet />
      </main>
      <footer className="border-t">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6 text-xs text-muted-foreground">
          <span>
            © {new Date().getFullYear()} {appName}
          </span>
          <HostedOnFreepod />
        </div>
      </footer>
    </div>
  );
}
