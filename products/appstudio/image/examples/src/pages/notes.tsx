import { Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { SignInRequired } from "@/components/sign-in-required";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useUser } from "@/lib/use-user";

type Note = { id: number; body: string; createdAt: string };

// A list the user adds to and deletes from, stored in PostgreSQL: loading,
// empty and error states included.
export function NotesPage() {
  const user = useUser();
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) api<Note[]>("/notes").then(setNotes, () => setError("Could not load your notes."));
  }, [user]);

  if (user === undefined) return null;
  if (user === null) return <SignInRequired />;

  async function add(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const note = await api<Note>("/notes", { method: "POST", body: JSON.stringify({ body: draft }) });
      setNotes((current) => [note, ...(current ?? [])]);
      setDraft("");
    } catch {
      setError("Could not save the note. Try again.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    await fetch(`/api/notes/${id}`, { method: "DELETE" });
    setNotes((current) => current?.filter((n) => n.id !== id) ?? null);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted-foreground">Only you can see your notes.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>New note</CardTitle>
          <CardDescription>Saved to the app's database.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={add} className="flex flex-col gap-3">
            <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="What's on your mind?" />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="self-end" disabled={!draft.trim() || saving}>
              {saving ? "Saving…" : "Add note"}
            </Button>
          </form>
        </CardContent>
      </Card>
      {notes === null ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : notes.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No notes yet. Your first one will show up here.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {notes.map((note) => (
            <li key={note.id} className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
              <div className="flex flex-col gap-1">
                <p className="text-sm whitespace-pre-wrap">{note.body}</p>
                <p className="text-xs text-muted-foreground">{new Date(note.createdAt).toLocaleString()}</p>
              </div>
              <Button variant="ghost" size="icon" aria-label="Delete note" onClick={() => remove(note.id)}>
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
