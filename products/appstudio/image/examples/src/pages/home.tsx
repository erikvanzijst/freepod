import { ArrowRight, FileUp, NotebookPen } from "lucide-react";
import { Link } from "react-router";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { appName } from "@/config";

const features = [
  { to: "/notes", icon: NotebookPen, title: "Notes", text: "Your own records, stored in PostgreSQL." },
  { to: "/files", icon: FileUp, title: "Files", text: "Uploads kept in the app's S3 bucket." },
];

// A landing page: a heading over a grid of entry points.
export function HomePage() {
  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-3 pt-6">
        <h1 className="text-4xl font-semibold tracking-tight text-balance">
          Welcome to{" "}
          <span className="bg-gradient-to-r from-brand-from to-brand-to bg-clip-text text-transparent">{appName}</span>
        </h1>
        <p className="max-w-xl text-muted-foreground">Pick where to start.</p>
      </section>
      <section className="grid gap-4 sm:grid-cols-2">
        {features.map(({ to, icon: Icon, title, text }) => (
          <Link key={to} to={to} className="group">
            <Card className="h-full transition-colors group-hover:border-primary/40">
              <CardHeader>
                <span className="mb-2 grid size-9 place-items-center rounded-lg bg-accent text-accent-foreground">
                  <Icon className="size-4.5" />
                </span>
                <CardTitle className="flex items-center gap-1.5">
                  {title}
                  <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-100" />
                </CardTitle>
                <CardDescription>{text}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </section>
    </div>
  );
}
