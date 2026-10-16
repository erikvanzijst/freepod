import { Sparkles } from "lucide-react";
import { appName } from "@/config";

// A neutral first page, shown until the app has its own. Replace it.
export function HomePage() {
  return (
    <section className="flex flex-col items-center gap-6 py-16 text-center">
      <span className="inline-flex items-center gap-2 rounded-full border bg-background/60 px-3 py-1 text-xs text-muted-foreground">
        <Sparkles className="size-3.5 text-primary" />
        Getting ready
      </span>
      <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        <span className="bg-gradient-to-r from-brand-from to-brand-to bg-clip-text text-transparent">{appName}</span>{" "}
        is on its way
      </h1>
      <p className="max-w-lg text-balance text-muted-foreground">This is where the app will appear.</p>
    </section>
  );
}
