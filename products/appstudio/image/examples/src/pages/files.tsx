import { Download, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SignInRequired } from "@/components/sign-in-required";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useUser } from "@/lib/use-user";

type StoredFile = { key: string; name: string; size: number; uploadedAt: string };

const formatSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

// Uploads to the app's S3 bucket through the API (multipart form data), and
// downloads back through it.
export function FilesPage() {
  const user = useUser();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<StoredFile[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => api<StoredFile[]>("/files").then(setFiles, () => setError("Could not load your files."));

  useEffect(() => {
    if (user) load();
  }, [user]);

  if (user === undefined) return null;
  if (user === null) return <SignInRequired />;

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    // Not api(): the browser sets the multipart content type itself.
    const res = await fetch("/api/files", { method: "POST", body: form });
    if (!res.ok) setError("Upload failed. Try again.");
    await load();
    setUploading(false);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Files</h1>
          <p className="text-sm text-muted-foreground">Stored in the app's private bucket.</p>
        </div>
        <input
          ref={input}
          type="file"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
        <Button onClick={() => input.current?.click()} disabled={uploading}>
          <Upload />
          {uploading ? "Uploading…" : "Upload"}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {files === null ? (
        <Skeleton className="h-24" />
      ) : files.length === 0 ? (
        <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">
          No files yet. Upload one to see it here.
        </div>
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {files.map((file) => (
            <li key={file.key} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{file.name}</p>
                <p className="text-xs text-muted-foreground">{formatSize(file.size)}</p>
              </div>
              <Button asChild variant="outline" size="sm">
                <a href={`/api/files/${encodeURIComponent(file.key)}`}>
                  <Download />
                  Download
                </a>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
