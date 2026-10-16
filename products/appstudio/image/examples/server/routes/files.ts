import { randomUUID } from "node:crypto";
import { GetObjectCommand, ListObjectsV2Command, PutObjectCommand } from "@aws-sdk/client-s3";
import { Hono } from "hono";
import { requireUser, type AuthEnv } from "../auth";
import { bucket, s3 } from "../storage";

// Files go to the app's S3 bucket, never to local disk (it does not survive a
// restart). Uploads and downloads pass through the API, so the browser needs
// no S3 access of its own. Each user's files live under their own prefix.
export const filesRoutes = new Hono<AuthEnv>();

filesRoutes.use(requireUser);

filesRoutes.get("/", async (c) => {
  const prefix = `${c.get("user")!.id}/`;
  const listed = await s3.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix }));
  const files = (listed.Contents ?? []).map((o) => ({
    key: o.Key!.slice(prefix.length),
    name: o.Key!.slice(prefix.length + 37),
    size: o.Size ?? 0,
    uploadedAt: o.LastModified,
  }));
  return c.json(files);
});

filesRoutes.post("/", async (c) => {
  const form = await c.req.parseBody();
  const file = form.file;
  if (!(file instanceof File)) return c.json({ error: "Choose a file to upload." }, 400);
  const key = `${randomUUID()}-${file.name}`;
  await s3.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: `${c.get("user")!.id}/${key}`,
      Body: Buffer.from(await file.arrayBuffer()),
      ContentType: file.type || "application/octet-stream",
    }),
  );
  return c.json({ key, name: file.name, size: file.size }, 201);
});

filesRoutes.get("/:key", async (c) => {
  const object = await s3.send(
    new GetObjectCommand({ Bucket: bucket, Key: `${c.get("user")!.id}/${c.req.param("key")}` }),
  );
  return new Response(object.Body!.transformToWebStream(), {
    headers: {
      "content-type": object.ContentType ?? "application/octet-stream",
      "content-disposition": `attachment; filename="${c.req.param("key").slice(37)}"`,
    },
  });
});
